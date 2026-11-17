"""Provider credentials, encrypted at rest (AD-10, design 5.3).

An admin may type a provider API key into the console instead of asking an
operator to put it in Vault.  That key is stored ONLY as AES-256-GCM ciphertext
under a key-encryption key (KEK) that lives only in the process environment
(``IDA_CREDENTIALS_KEK``, projected from Vault by ESO).  The database never holds
the plaintext, a prefix, a suffix or a hash of it, and no API response or log
line ever carries it.

THE KEK FORMAT.  ``kid:<base64url of exactly 32 bytes>``, comma-separated.  The
FIRST entry is active (it encrypts); every entry can decrypt.  Rotation is:
add the new kid FIRST in Vault -> restart -> ``python -m ida_core.configdb
rotate-kek`` -> remove the old kid.  A different KEK per environment is
intended: a prod database restored into dev cannot decrypt prod keys.

THE AAD BINDS A CIPHERTEXT TO ITS ROW.  ``ida-llm:cred:<id>:<name>`` is the
associated data, so swapping two rows' ciphertexts -- or renaming a row to
another model's credential name -- makes decryption fail rather than handing
model A's key to model B.

⚠ NO SECRET IN ANY MESSAGE.  Every exception raised here names entries by
position and kid, never by value -- the same rule ``ida_api.auth`` follows for
tokens -- because these errors land in pod logs.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ida_core.configdb.tables import ProviderCredentialRow
from ida_core.db import session_scope, utcnow
from ida_core.registry import MissingApiKeyError

log = logging.getLogger(__name__)

KEY_BYTES = 32
NONCE_BYTES = 12
_KID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
LAST_USED_GRANULARITY = timedelta(hours=1)
"""``last_used_at`` is touched at most once an hour per credential: it answers
"is this key still in use?", which does not need a write per job."""


class KekConfigError(RuntimeError):
    """``IDA_CREDENTIALS_KEK`` is malformed.  The process refuses to boot.

    ⚠ Its message goes to a pod log: it names entries by position and kid only."""


class CredentialDecryptError(RuntimeError):
    """A stored ciphertext could not be decrypted (wrong/removed KEK, tampering,
    or a swapped row).  Names the credential, never the material."""


@dataclass(frozen=True)
class KeyRing:
    """The parsed KEK list.  ``keys[0]`` is active."""

    keys: tuple[tuple[str, bytes], ...]

    @property
    def active_kid(self) -> str:
        return self.keys[0][0]

    def key_for(self, kid: str) -> bytes | None:
        for candidate, key in self.keys:
            if candidate == kid:
                return key
        return None

    def __repr__(self) -> str:  # never let a repr carry key bytes
        return f"KeyRing(kids={[k for k, _ in self.keys]!r})"


def parse_kek(raw: str) -> KeyRing | None:
    """Parse ``IDA_CREDENTIALS_KEK`` strictly.  Empty -> ``None`` (credentials
    unusable, everything else unaffected).  Malformed -> :class:`KekConfigError`."""
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not entries:
        return None
    keys: list[tuple[str, bytes]] = []
    for position, entry in enumerate(entries, start=1):
        kid, separator, encoded = entry.partition(":")
        kid = kid.strip()
        if not separator:
            raise KekConfigError(
                f"IDA_CREDENTIALS_KEK entry {position} has no ':'; expected 'kid:<base64url key>'"
            )
        if not _KID.match(kid):
            raise KekConfigError(
                f"IDA_CREDENTIALS_KEK entry {position} has an invalid kid "
                "(1-16 of letters, digits, '-', '_')"
            )
        try:
            padded = encoded.strip() + "=" * (-len(encoded.strip()) % 4)
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except (binascii.Error, ValueError, UnicodeEncodeError):
            raise KekConfigError(
                f"IDA_CREDENTIALS_KEK entry {position} (kid {kid!r}) is not valid base64url"
            ) from None
        if len(key) != KEY_BYTES:
            raise KekConfigError(
                f"IDA_CREDENTIALS_KEK entry {position} (kid {kid!r}) decodes to {len(key)} "
                f"bytes; AES-256 needs exactly {KEY_BYTES}. Generate one with: python -c "
                "\"import secrets,base64;print('k1:'+base64.urlsafe_b64encode("
                'secrets.token_bytes(32)).decode())"'
            )
        if any(existing == kid for existing, _ in keys):
            raise KekConfigError(f"IDA_CREDENTIALS_KEK repeats kid {kid!r}")
        keys.append((kid, key))
    return KeyRing(tuple(keys))


def _aad(credential_id: str, name: str) -> bytes:
    return f"ida-llm:cred:{credential_id}:{name}".encode()


def encrypt(
    ring: KeyRing, *, credential_id: str, name: str, plaintext: str
) -> tuple[bytes, bytes, str]:
    """``(ciphertext, nonce, kid)`` under the ACTIVE key.  A fresh random nonce
    every time: GCM nonce reuse under one key is catastrophic."""
    nonce = os.urandom(NONCE_BYTES)
    kid, key = ring.keys[0]
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), _aad(credential_id, name))
    return ciphertext, nonce, kid


def decrypt(
    ring: KeyRing, *, credential_id: str, name: str, ciphertext: bytes, nonce: bytes, kid: str
) -> str:
    key = ring.key_for(kid)
    if key is None:
        raise CredentialDecryptError(
            f"credential {name!r} is encrypted under kid {kid!r}, which IDA_CREDENTIALS_KEK "
            "no longer lists; restore that kid or re-enter the key"
        )
    try:
        plaintext = AESGCM(key).decrypt(bytes(nonce), bytes(ciphertext), _aad(credential_id, name))
    except InvalidTag:
        raise CredentialDecryptError(
            f"credential {name!r} failed authentication (wrong key, tampered or swapped row)"
        ) from None
    return plaintext.decode("utf-8")


def rotate_all(session: Session, ring: KeyRing) -> int:
    """Re-encrypt every credential not under the active kid.  Returns the count.

    Fresh nonce per row; ``version`` is bumped so every process's plaintext
    cache (keyed by row version) drops the old entry."""
    rotated = 0
    for row in session.scalars(select(ProviderCredentialRow)):
        if row.kek_id == ring.active_kid:
            continue
        plaintext = decrypt(
            ring,
            credential_id=row.id,
            name=row.name,
            ciphertext=row.ciphertext,
            nonce=row.nonce,
            kid=row.kek_id,
        )
        row.ciphertext, row.nonce, row.kek_id = encrypt(
            ring, credential_id=row.id, name=row.name, plaintext=plaintext
        )
        row.version += 1
        row.updated_at = utcnow()
        row.updated_by = "system:rotate-kek"
        rotated += 1
    return rotated


class DbCredentialResolver:
    """``credentials.get(name)`` -> the plaintext key, for ``resolve_api_key``.

    Caches plaintext IN MEMORY ONLY, per process, keyed by the row's id and
    ``version`` -- so a rotation (which bumps the version) is picked up on the
    next job without a restart, and an unchanged key is not decrypted per job.
    """

    def __init__(self, session_factory: sessionmaker[Session], ring: KeyRing | None) -> None:
        self._session_factory = session_factory
        self._ring = ring
        self._cache: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"DbCredentialResolver(cached={len(self._cache)})"

    def get(self, name: str) -> str:
        if self._ring is None:
            raise MissingApiKeyError(
                f"credential {name!r} cannot be decrypted: IDA_CREDENTIALS_KEK is unset"
            )
        with session_scope(self._session_factory) as session:
            row = session.scalar(
                select(ProviderCredentialRow).where(ProviderCredentialRow.name == name)
            )
            if row is None:
                raise MissingApiKeyError(f"credential {name!r} does not exist")
            cache_key = (row.id, row.version)
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached is None:
                try:
                    cached = decrypt(
                        self._ring,
                        credential_id=row.id,
                        name=row.name,
                        ciphertext=row.ciphertext,
                        nonce=row.nonce,
                        kid=row.kek_id,
                    )
                except CredentialDecryptError as exc:
                    raise MissingApiKeyError(str(exc)) from None
                with self._lock:
                    # Drop older versions of the same row: only one live copy.
                    for stale in [k for k in self._cache if k[0] == row.id]:
                        del self._cache[stale]
                    self._cache[cache_key] = cached
            now = utcnow()
            last = row.last_used_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=now.tzinfo)
            if last is None or now - last >= LAST_USED_GRANULARITY:
                row.last_used_at = now
            return cached
