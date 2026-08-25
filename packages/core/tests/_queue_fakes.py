"""A faithful in-process stand-in for the Redis commands the queue uses.

⚠ UNIQUELY NAMED ON PURPOSE, like ``_runner_helpers``. CI runs ONE ``pytest``
from the repo root across five distributions that each own a ``tests/``
directory, so a module called ``fakes`` here and a module called ``fakes``
anywhere else would be the same import name.

WHY A FAKE AND NOT A LIVE SERVER
--------------------------------
The python CI job runs no Redis service container (see ``.github/workflows``);
only the ``migrations`` job gets a service, and it gets Postgres. So the choice
is not "fake or real" -- it is "fake, or the reliable-queue path is untested in
CI". :class:`FakeRedis` is therefore written to be *faithful* rather than
convenient, because a double that has quietly drifted from the thing it doubles
is worse than no double at all. In particular:

* **Everything is stored as bytes.** Redis encodes ``str`` and ``bytes`` to the
  same value, so a message pushed as ``str`` is removable by ``LREM`` with the
  ``bytes`` a read handed back. A fake that stored them as distinct Python
  objects would let an ack silently fail to match -- and pass, while the real
  system leaked a claim on every single job.
* **``LREM`` removes at most ``count`` occurrences**, from the head, and returns
  how many it removed.
* **``LTRIM`` uses Redis's inclusive-end, negative-index slicing**, so
  ``LTRIM key -1000 -1`` genuinely means "keep the last 1000".
* **``LMOVE`` is atomic**: read-and-take is one operation, which is the entire
  safety argument for lock-free recovery.
* **An emptied list key stops existing**, as it does in Redis. A fake that left
  empty lists behind would keep answering ``EXISTS`` and ``SCAN`` for consumers
  that have been fully drained.

The one deliberate departure: ``BLMOVE`` does not block. Nothing in these tests
wants a thread to sleep, and the queue only calls it with a positive timeout on
a path whose blocking behaviour is Redis's problem, not the queue's. It is
called out here rather than left for a reader to discover.

HOW MUCH THIS FAKE IS ACTUALLY TRUSTED
--------------------------------------
Precisely as much as the real server corroborates, and no more. When
``IDA_TEST_REDIS_URL`` is set, ``test_queue.py``'s ``TestQueueParity`` runs the
**same** assertions over this fake AND over a real ``RedisQueue``, so a
divergence between the two fails the fake's leg rather than silently weakening
every test built on it. (Verified by deliberately breaking the str->bytes
encoding below: the fake's leg went red while the real one stayed green.)

``test_queue_redis_integration.py`` covers, separately, the handful of things no
fake can honestly stand in for -- a real ``SCAN`` cursor and a key TTL genuinely
elapsing.

Without that env var both files skip their real-Redis work and this fake is
carrying the guarantee alone. That is the everyday CI position today, and it is
why fidelity here is worth the effort rather than being a nicety.
"""

from __future__ import annotations

import fnmatch


def _b(value) -> bytes:
    """Encode exactly as Redis does: everything on the wire is bytes."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return str(value).encode()


class FakeRedis:
    """The subset of the Redis command surface :mod:`ida_core.queue` uses."""

    def __init__(self) -> None:
        self.lists: dict[str, list[bytes]] = {}
        self.strings: dict[str, bytes] = {}
        self.commands: list[str] = []
        """Every command name, in order.  Lets a test assert on *how* something
        was done (e.g. that recovery used LMOVE and not LRANGE-then-LREM)."""

    # ------------------------------------------------------------- lists --

    def rpush(self, key, *values) -> int:
        target = self.lists.setdefault(str(key), [])
        target.extend(_b(v) for v in values)
        self.commands.append("rpush")
        return len(target)

    def lpush(self, key, *values) -> int:
        target = self.lists.setdefault(str(key), [])
        for value in values:
            target.insert(0, _b(value))
        self.commands.append("lpush")
        return len(target)

    def llen(self, key) -> int:
        self.commands.append("llen")
        return len(self.lists.get(str(key), []))

    def lrange(self, key, start, end) -> list[bytes]:
        self.commands.append("lrange")
        items = self.lists.get(str(key), [])
        return items[start : len(items) if end == -1 else end + 1]

    def ltrim(self, key, start, end) -> bool:
        """Redis semantics: inclusive end, negative indices from the tail."""
        self.commands.append("ltrim")
        name = str(key)
        items = self.lists.get(name, [])
        size = len(items)
        lo = start + size if start < 0 else start
        hi = end + size if end < 0 else end
        lo = max(lo, 0)
        hi = min(hi, size - 1)
        self._store_list(name, [] if lo > hi else items[lo : hi + 1])
        return True

    def lrem(self, key, count, value) -> int:
        """Remove up to ``count`` occurrences from the head.  Returns how many."""
        self.commands.append("lrem")
        name = str(key)
        items = self.lists.get(name, [])
        needle = _b(value)
        removed = 0
        kept: list[bytes] = []
        for item in items:
            if item == needle and (count == 0 or removed < count):
                removed += 1
                continue
            kept.append(item)
        self._store_list(name, kept)
        return removed

    def lmove(self, source, destination, src="LEFT", dest="RIGHT"):
        """Atomically take one element from ``source`` and put it on ``destination``."""
        self.commands.append("lmove")
        items = self.lists.get(str(source), [])
        if not items:
            return None
        value = items.pop(0) if src.upper() == "LEFT" else items.pop()
        self._store_list(str(source), items)
        target = self.lists.setdefault(str(destination), [])
        if dest.upper() == "RIGHT":
            target.append(value)
        else:
            target.insert(0, value)
        return value

    def blmove(self, source, destination, timeout=0, src="LEFT", dest="RIGHT"):
        """Non-blocking here -- see the module docstring."""
        self.commands.append("blmove")
        return self.lmove(source, destination, src, dest)

    def _store_list(self, name: str, items: list[bytes]) -> None:
        """Write a list back, deleting the key when it empties -- as Redis does."""
        if items:
            self.lists[name] = items
        else:
            self.lists.pop(name, None)

    # ----------------------------------------------------------- strings --

    def set(self, key, value, ex=None) -> bool:
        self.commands.append("set")
        self.strings[str(key)] = _b(value)
        return True

    def exists(self, *keys) -> int:
        self.commands.append("exists")
        return sum(1 for key in keys if str(key) in self.strings or str(key) in self.lists)

    def delete(self, *keys) -> int:
        self.commands.append("delete")
        removed = 0
        for key in keys:
            removed += self.strings.pop(str(key), None) is not None
            removed += self.lists.pop(str(key), None) is not None
        return removed

    def expire_now(self, key) -> None:
        """Drop a key as if its TTL had just elapsed.

        The whole point of the fake: a heartbeat key vanishing is *exactly* what
        a runner pod dying looks like from Redis's side, and it is the only way
        to reach the recovery path without waiting 90 real seconds.
        """
        self.strings.pop(str(key), None)

    # -------------------------------------------------------------- keys --

    def scan_iter(self, match=None, count=None):
        self.commands.append("scan_iter")
        pattern = match if isinstance(match, str) else (match.decode() if match else "*")
        for name in sorted({*self.lists, *self.strings}):
            if fnmatch.fnmatch(name, pattern):
                yield name.encode()

    def ping(self) -> bool:
        return True

    # ---------------------------------------------------------- pipeline --

    def pipeline(self, transaction=True):
        return _FakePipeline(self)


class _FakePipeline:
    """Buffers commands and applies them on ``execute()``, as redis-py does."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list = []

    def rpush(self, key, *values):
        self._ops.append(lambda: self._redis.rpush(key, *values))
        return self

    def lpush(self, key, *values):
        self._ops.append(lambda: self._redis.lpush(key, *values))
        return self

    def ltrim(self, key, start, end):
        self._ops.append(lambda: self._redis.ltrim(key, start, end))
        return self

    def lrem(self, key, count, value):
        self._ops.append(lambda: self._redis.lrem(key, count, value))
        return self

    def execute(self) -> list:
        results = [op() for op in self._ops]
        self._ops.clear()
        return results


class BrokenPipelineRedis(FakeRedis):
    """A Redis whose pipelines refuse.  Models "Redis is in trouble" precisely."""

    def pipeline(self, transaction=True):
        raise ConnectionError("redis is down")
