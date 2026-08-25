"""Identifier helpers.

Every durable entity in Capstone-IDA carries a **string** primary key that is
readable in logs and safe in URLs.  We deliberately do not use database
sequences: a run id is minted by the *caller* (the API) before the row exists,
so the enqueue path can hand the id back to the client and put the very same id
on the queue message.  See :mod:`ida_core.queue`.

Format: ``<prefix>_<26-char lowercase base32 ULID-ish>``.  We use a monotonic
timestamp prefix + random suffix so ids sort roughly by creation time, which
makes ``ORDER BY id`` a usable cheap fallback for ``ORDER BY created_at``.
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, no i/l/o/u


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    """Mint a new sortable identifier with ``prefix``.

    >>> new_id("run").startswith("run_")
    True
    >>> len(new_id("run")) == len("run_") + 26
    True
    """
    if not prefix or "_" in prefix:
        raise ValueError("prefix must be non-empty and contain no underscore")
    timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")
    return f"{prefix}_{_encode(timestamp_ms, 10)}{_encode(randomness, 16)}"


def new_run_id() -> str:
    """Mint a ``run_...`` id.  Minted by the API at enqueue time."""
    return new_id("run")


def new_result_id() -> str:
    """Mint a ``res_...`` id.  Minted by the runner, one per scored sample."""
    return new_id("res")
