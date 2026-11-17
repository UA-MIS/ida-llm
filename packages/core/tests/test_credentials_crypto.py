"""Provider-credential crypto (AD-10, design 5.3)."""

from __future__ import annotations

import base64

import pytest

from ida_core.configdb.crypto import (
    CredentialDecryptError,
    DbCredentialResolver,
    KekConfigError,
    decrypt,
    encrypt,
    parse_kek,
    rotate_all,
)
from ida_core.configdb.tables import ProviderCredentialRow
from ida_core.db import create_all, make_engine, make_session_factory, session_scope
from ida_core.registry import MissingApiKeyError

PLANTED = "sk-PLANTED-not-a-real-key-0123456789"


def _key(seed: bytes) -> str:
    """Deterministic test KEKs: pytest-xdist workers must collect identical
    parameter ids, so nothing here may be random at import time."""
    return base64.urlsafe_b64encode((seed * 32)[:32]).decode()


K1, K0 = _key(b"\x01fixture-k1"), _key(b"\x02fixture-k0")


def test_round_trip() -> None:
    ring = parse_kek(f"k1:{K1}")
    ct, nonce, kid = encrypt(ring, credential_id="cred_1", name="mistral", plaintext=PLANTED)
    assert kid == "k1" and len(nonce) == 12
    assert PLANTED.encode() not in ct
    assert (
        decrypt(ring, credential_id="cred_1", name="mistral", ciphertext=ct, nonce=nonce, kid=kid)
        == PLANTED
    )


def test_nonces_are_fresh() -> None:
    ring = parse_kek(f"k1:{K1}")
    a = encrypt(ring, credential_id="c", name="n", plaintext=PLANTED)
    b = encrypt(ring, credential_id="c", name="n", plaintext=PLANTED)
    assert a[1] != b[1] and a[0] != b[0]


@pytest.mark.parametrize("swap", [("cred_2", "mistral"), ("cred_1", "other")])
def test_the_aad_binds_the_ciphertext_to_its_row(swap) -> None:
    ring = parse_kek(f"k1:{K1}")
    ct, nonce, kid = encrypt(ring, credential_id="cred_1", name="mistral", plaintext=PLANTED)
    with pytest.raises(CredentialDecryptError) as excinfo:
        decrypt(ring, credential_id=swap[0], name=swap[1], ciphertext=ct, nonce=nonce, kid=kid)
    assert PLANTED not in str(excinfo.value)


def test_every_kid_decrypts_and_the_first_encrypts() -> None:
    old = parse_kek(f"k0:{K0}")
    ct, nonce, kid = encrypt(old, credential_id="c", name="n", plaintext=PLANTED)
    both = parse_kek(f"k1:{K1},k0:{K0}")
    assert both.active_kid == "k1"
    assert (
        decrypt(both, credential_id="c", name="n", ciphertext=ct, nonce=nonce, kid=kid) == PLANTED
    )


def test_a_removed_kid_is_a_named_error() -> None:
    ct, nonce, kid = encrypt(parse_kek(f"k0:{K0}"), credential_id="c", name="n", plaintext=PLANTED)
    with pytest.raises(CredentialDecryptError, match="k0"):
        decrypt(
            parse_kek(f"k1:{K1}"), credential_id="c", name="n", ciphertext=ct, nonce=nonce, kid=kid
        )


@pytest.mark.parametrize(
    "raw",
    [
        "nocolon",
        f"bad kid!:{K1}",
        "k1:not*base64*at*all",
        "k1:" + base64.urlsafe_b64encode(b"short-key").decode(),
        f"k1:{K1},k1:{K0}",
    ],
)
def test_a_malformed_kek_is_refused_without_key_material(raw) -> None:
    with pytest.raises(KekConfigError) as excinfo:
        parse_kek(raw)
    message = str(excinfo.value)
    for secret in (K1, K0, "not*base64*at*all"):
        assert secret not in message


def test_empty_kek_is_none_and_repr_hides_keys() -> None:
    assert parse_kek("") is None and parse_kek(" , ") is None
    ring = parse_kek(f"k1:{K1}")
    assert K1 not in repr(ring) and "k1" in repr(ring)


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'c.db'}")
    create_all(engine)
    return make_session_factory(engine)


def _store(factory, ring, name="mistral", cid="cred_1") -> None:
    ct, nonce, kid = encrypt(ring, credential_id=cid, name=name, plaintext=PLANTED)
    with session_scope(factory) as session:
        session.add(
            ProviderCredentialRow(
                id=cid, name=name, provider="mistral", ciphertext=ct, nonce=nonce, kek_id=kid
            )
        )


def test_rotate_kek_reencrypts_under_the_active_kid(factory) -> None:
    _store(factory, parse_kek(f"k0:{K0}"))
    ring = parse_kek(f"k1:{K1},k0:{K0}")
    with session_scope(factory) as session:
        assert rotate_all(session, ring) == 1
    with session_scope(factory) as session:
        row = session.get(ProviderCredentialRow, "cred_1")
        assert row.kek_id == "k1" and row.version == 2
    # The old kid can now be removed.
    assert DbCredentialResolver(factory, parse_kek(f"k1:{K1}")).get("mistral") == PLANTED


def test_resolver_missing_kek_names_the_credential_not_the_value(factory) -> None:
    _store(factory, parse_kek(f"k1:{K1}"))
    with pytest.raises(MissingApiKeyError) as excinfo:
        DbCredentialResolver(factory, None).get("mistral")
    assert "IDA_CREDENTIALS_KEK is unset" in str(excinfo.value)
    assert "mistral" in str(excinfo.value)
    assert PLANTED not in str(excinfo.value)


def test_resolver_caches_per_version_and_touches_last_used(factory) -> None:
    ring = parse_kek(f"k1:{K1}")
    _store(factory, ring)
    resolver = DbCredentialResolver(factory, ring)
    assert resolver.get("mistral") == PLANTED
    assert PLANTED not in repr(resolver)
    with session_scope(factory) as session:
        row = session.get(ProviderCredentialRow, "cred_1")
        assert row.last_used_at is not None
        row.ciphertext, row.nonce, row.kek_id = encrypt(
            ring, credential_id="cred_1", name="mistral", plaintext="sk-ROTATED-xxxxxxxx"
        )
        row.version += 1
    assert resolver.get("mistral") == "sk-ROTATED-xxxxxxxx"


def test_unknown_credential_is_a_missing_key(factory) -> None:
    with pytest.raises(MissingApiKeyError, match="does not exist"):
        DbCredentialResolver(factory, parse_kek(f"k1:{K1}")).get("nope")


def test_unpadded_base64url_is_accepted() -> None:
    """The deployed KEKs are 43 base64url characters with no '=' padding (what
    `base64.urlsafe_b64encode(...).decode().rstrip('=')` and most generators
    emit). The parser must take both forms of the same 32 bytes."""
    padded = K1
    unpadded = K1.rstrip("=")
    assert len(unpadded) == 43
    assert parse_kek(f"k1:{unpadded}").keys == parse_kek(f"k1:{padded}").keys
