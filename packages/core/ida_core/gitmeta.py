"""Git provenance helpers.

D-1 requires every result to record the git SHA of the task/rubric definitions
that produced it. We read it in this order:

1. ``IDA_GIT_SHA`` env var -- set at image build time, the only source that
   works inside a container (which has no ``.git``).
2. ``git rev-parse --verify HEAD`` in the repo root -- the local dev path.
3. ``None`` -- honest absence.

**A ``None`` SHA means "unreproducible" and is never silently replaced with a
placeholder.** That rule is enforced, not merely documented: every candidate is
shape-checked by :func:`is_sha` before being returned. A repository with no
commits makes ``git rev-parse HEAD`` print the literal string ``HEAD``; a build
pipeline that forgets to substitute a variable can export ``$GITHUB_SHA``
verbatim. Both would otherwise be stored as though they were provenance, which
is worse than storing nothing -- a wrong SHA looks like a real one.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def is_sha(value: str | None) -> bool:
    """True only for a full 40-character lowercase hex SHA.

    Abbreviated SHAs are rejected on purpose: a 7-character prefix is not
    guaranteed unique over a repository's lifetime, and provenance that can
    become ambiguous later is not provenance.

    >>> is_sha("a" * 40)
    True
    >>> is_sha("HEAD"), is_sha("a" * 7), is_sha(None)
    (False, False, False)
    """
    return bool(value) and bool(_SHA_RE.match(value.strip()))


def current_git_sha(cwd: Path | str | None = None) -> str | None:
    """Return the 40-char HEAD SHA, or ``None`` if it cannot be determined.

    Anything that is not a well-formed SHA -- including the literal ``"HEAD"``
    that git prints in a repository with no commits -- yields ``None``.
    """
    from_env = os.environ.get("IDA_GIT_SHA", "").strip()
    if from_env:
        return from_env if is_sha(from_env) else None

    try:
        proc = subprocess.run(
            # S607 (partial executable path) is accepted DELIBERATELY. Pinning
            # /usr/bin/git would break on any image or platform that puts it
            # elsewhere, and the threat S607 guards against -- a planted `git`
            # earlier on PATH -- is not reachable here: this runs only in dev
            # checkouts and the CI container, never in the runtime image (which
            # has no .git, so the IDA_GIT_SHA branch above returns first).
            # S603 likewise: the argv is a fixed literal with no user input.
            ["git", "rev-parse", "--verify", "HEAD"],  # noqa: S607
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha if is_sha(sha) else None
