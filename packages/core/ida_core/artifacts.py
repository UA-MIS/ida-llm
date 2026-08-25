"""Object-storage conventions: where transcripts and eval logs live.

Path convention (**stable -- treat as a contract**)::

    <bucket>/runs/<run_id>/transcripts/<sample_id>.json      one SampleTranscript
    <bucket>/runs/<run_id>/transcripts/<sample_id>/r<n>.json  repetition n > 0
    <bucket>/runs/<run_id>/eval-log.json                     the whole EvalLog

Rules behind the shape:

* **Run-id prefix first.**  MinIO/S3 list operations are prefix scans, so
  everything about one run is one ``LIST`` away, and deleting a run is a single
  prefixed delete.
* **No date partitioning.**  Run ids are time-sortable (:mod:`ida_core.ids`),
  so a date prefix would be redundant and would make "everything for run X"
  require knowing when X ran.
* **Sample id is the leaf.**  Sample ids are authored in task YAML; they are
  validated path-safe by :func:`sample_key` so a hostile task file cannot write
  outside its run prefix.
* **Repetitions nest under the sample, they do not decorate it.**  Repetition
  ``n > 0`` lives at ``<sample_id>/r<n>.json`` rather than ``<sample_id>.r<n>.json``.
  The suffix form is *unsafe*: ``.`` is a legal character in a sample id, so a
  task with a sample literally named ``s1.r2`` would produce the same key as
  repetition 2 of sample ``s1`` and one transcript would silently overwrite the
  other.  Nesting cannot collide, because a sample id can never contain ``/`` --
  a suffixed key is always one path segment below ``transcripts/`` and a nested
  key is always two.

URIs are ``s3://<bucket>/<key>``.  That is what lands in
``results.transcript_uri``.  The *endpoint* (MinIO in-cluster vs AWS) is
deployment config and deliberately not part of the stored URI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol, runtime_checkable

DEFAULT_BUCKET = "ida-artifacts"

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _check_segment(name: str, what: str) -> str:
    """Reject anything that could escape the run prefix."""
    if not _SAFE_SEGMENT.match(name):
        raise ValueError(
            f"unsafe {what} {name!r}: must match {_SAFE_SEGMENT.pattern} "
            "(no slashes, no leading dot, no '..')"
        )
    return name


def run_prefix(run_id: str) -> str:
    """``runs/<run_id>/`` -- the single prefix that owns everything for a run."""
    return f"runs/{_check_segment(run_id, 'run_id')}/"


def sample_key(run_id: str, sample_id: str, repeat_index: int = 0) -> str:
    """Object key for one sample transcript.

    ``repeat_index`` 0 -- the only value the skeleton emits -- keeps the
    original ``<sample_id>.json`` leaf, so every existing object is unaffected.
    Repetitions above 0 **nest under a directory named for the sample**::

        runs/<run_id>/transcripts/add-simple.json     repeat 0
        runs/<run_id>/transcripts/add-simple/r1.json  repeat 1
        runs/<run_id>/transcripts/add-simple/r2.json  repeat 2

    **Why nesting and not a ``.r<n>`` suffix.**  ``.`` is a legal character in a
    sample id (see :data:`_SAFE_SEGMENT`), so the suffix form collides: a task
    with a sample named ``s1.r2`` would generate the identical key to repetition
    2 of a sample named ``s1``, and whichever wrote second would silently
    destroy the other's transcript.  Both are plausible -- ``.`` appears in real
    ids like ``fig.3a`` -- and the failure is invisible, because both writes
    succeed.  Nesting is collision-free by construction: ``/`` is the one
    character a sample id may never contain, so a repeat-0 key is always exactly
    one segment below ``transcripts/`` and a repeat-n key always exactly two.

    Raises ``ValueError`` for a negative ``repeat_index`` or an unsafe id.
    """
    leaf = _check_segment(sample_id, "sample_id")
    if repeat_index < 0:
        raise ValueError(f"repeat_index must be >= 0, got {repeat_index}")
    if repeat_index == 0:
        return f"{run_prefix(run_id)}transcripts/{leaf}.json"
    return f"{run_prefix(run_id)}transcripts/{leaf}/r{repeat_index}.json"


def eval_log_key(run_id: str) -> str:
    """Object key for the whole structured eval log of a run."""
    return f"{run_prefix(run_id)}eval-log.json"


def to_uri(bucket: str, key: str) -> str:
    """``s3://bucket/key`` -- the form stored in ``results.transcript_uri``."""
    return f"s3://{bucket}/{key}"


def parse_uri(uri: str) -> tuple[str, str]:
    """Inverse of :func:`to_uri`.  Raises ``ValueError`` on anything else."""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri!r}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    if not bucket or not key:
        raise ValueError(f"malformed s3 uri: {uri!r}")
    return bucket, key


@runtime_checkable
class ArtifactStore(Protocol):
    """Everything the harness and the API may assume about object storage."""

    bucket: str

    def put_json(self, key: str, payload: dict) -> str:
        """Write ``payload`` as UTF-8 JSON at ``key``; return the ``s3://`` URI."""

    def get_json(self, key: str) -> dict:
        """Read back JSON.  Raises ``KeyError`` if the object is absent."""

    def exists(self, key: str) -> bool: ...

    def ensure_bucket(self) -> None:
        """Create the bucket if missing.  Idempotent; safe to call at startup."""


class S3ArtifactStore:
    """MinIO / S3 implementation.  MinIO is S3-API-compatible, so this is both."""

    def __init__(self, client, bucket: str = DEFAULT_BUCKET) -> None:
        self._client = client
        self.bucket = bucket

    @classmethod
    def from_settings(
        cls,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str = DEFAULT_BUCKET,
        region: str = "us-east-1",
    ) -> S3ArtifactStore:
        import boto3  # lazy: keeps ida_core importable without boto3 configured

        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        return cls(client, bucket=bucket)

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def put_json(self, key: str, payload: dict) -> str:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(payload, indent=2, sort_keys=True, default=str).encode(),
            ContentType="application/json",
        )
        return to_uri(self.bucket, key)

    def get_json(self, key: str) -> dict:
        from botocore.exceptions import ClientError

        try:
            obj = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:  # pragma: no cover - needs a live endpoint
            raise KeyError(key) from exc
        return json.loads(obj["Body"].read().decode())

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


class LocalArtifactStore:
    """Filesystem-backed :class:`ArtifactStore` rooted at a directory.

    A real implementation, not a mock -- it enforces the same key convention and
    round-trips the same JSON.  Used by tests, by the in-process tracer bullet,
    and as a no-MinIO fallback for a laptop dev loop.  ``bucket`` is retained so
    the ``s3://`` URIs it emits are indistinguishable from production's.
    """

    def __init__(self, root: str | Path, bucket: str = DEFAULT_BUCKET) -> None:
        self._root = Path(root)
        self.bucket = bucket

    def _path(self, key: str) -> Path:
        path = (self._root / self.bucket / key).resolve()
        root = (self._root / self.bucket).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"key escapes store root: {key!r}")
        return path

    def ensure_bucket(self) -> None:
        (self._root / self.bucket).mkdir(parents=True, exist_ok=True)

    def put_json(self, key: str, payload: dict) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return to_uri(self.bucket, key)

    def get_json(self, key: str) -> dict:
        path = self._path(key)
        if not path.exists():
            raise KeyError(key)
        return json.loads(path.read_text())

    def exists(self, key: str) -> bool:
        return self._path(key).exists()
