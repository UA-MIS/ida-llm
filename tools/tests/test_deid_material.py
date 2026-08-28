"""Tests for the intake CLI -- the seam a human actually touches.

The detector RULES are covered in depth by ``packages/core/tests/test_deid.py``
and the gate by ``test_intake.py``.  What is asserted here is what only the CLI
can get wrong: that it writes the two files, that it never prints the material,
and that its three refusals (``tasks/``, overwrite, missing reference) actually
refuse.

Driven as a subprocess, the way an operator runs it, so the exit codes are
tested rather than assumed.  Every fixture is synthetic -- written here, for
here, exactly as ``packages/core/tests/_synthetic_pii.py`` explains.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "tools" / "deid_material.py"

RAW = """\
Student: Marisol Vandersteen
Student ID: 12345678
Email: mvandersteen@crimson.example.edu

The candidate argued the paired test was appropriate because the two samples
were the same people measured twice.
"""

PLANTED = ["Marisol", "Vandersteen", "12345678", "mvandersteen@crimson.example.edu"]

REFERENCE = "MIS 200 Fall 2024, midterm item 12 (synthetic fixture)"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def raw_file(tmp_path: Path) -> Path:
    path = tmp_path / "raw.txt"
    path.write_text(RAW, encoding="utf-8")
    return path


def test_the_cli_exists() -> None:
    assert CLI.is_file()


class TestCleaning:
    def test_it_writes_cleaned_text_and_a_provenance_sidecar(
        self, raw_file: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out" / "item12"
        result = _run(str(raw_file), "--reference", REFERENCE, "-o", str(out))

        assert result.returncode == 0, result.stderr
        cleaned = (tmp_path / "out" / "item12.txt").read_text(encoding="utf-8")
        sidecar = json.loads((tmp_path / "out" / "item12.provenance.json").read_text())

        for token in PLANTED:
            assert token not in cleaned
        assert sidecar["cleanliness"] == "cleaned"
        assert len(sidecar["provenance"]["sha256"]) == 64
        assert sidecar["report"]["counts"]

    def test_the_sidecar_holds_a_pointer_not_the_content(
        self, raw_file: Path, tmp_path: Path
    ) -> None:
        """The sidecar is the artefact that gets committed or filed alongside.

        It records where the material came from so the material does not have
        to travel with it -- so the one thing it must never contain is the
        material, cleaned or otherwise.
        """
        out = tmp_path / "item12"
        _run(str(raw_file), "--reference", REFERENCE, "-o", str(out))
        blob = (tmp_path / "item12.provenance.json").read_text(encoding="utf-8")

        for token in PLANTED:
            assert token not in blob
        assert "paired test" not in blob  # not even the cleaned body

    def test_it_never_prints_the_material(self, raw_file: Path, tmp_path: Path) -> None:
        """Scrollback and CI logs are places material does not come back from.

        Counts and caveats on stdout; nothing that was in the file, cleaned or
        raw.  A tool whose output needs the same care as its input gets run in
        the wrong window eventually.
        """
        out = tmp_path / "item12"
        result = _run(str(raw_file), "--reference", REFERENCE, "-o", str(out))
        combined = result.stdout + result.stderr

        for token in PLANTED:
            assert token not in combined
        assert "paired test" not in combined
        assert "student_id" in combined  # the COUNT line, which is a category name

    def test_it_reports_the_residual_risk(self, raw_file: Path, tmp_path: Path) -> None:
        """The caveats reach the operator, not just the JSON they may not open."""
        result = _run(str(raw_file), "--reference", REFERENCE, "-o", str(tmp_path / "x"))
        assert "does NOT guarantee anonymity" in result.stdout
        assert "re-identif" in result.stdout

    def test_a_roster_file_improves_detection_and_is_not_echoed(self, tmp_path: Path) -> None:
        """The roster is PII too: it must work without ever being printed."""
        source = tmp_path / "prose.txt"
        source.write_text("Marisol wrote a strong answer about paired tests.\n", encoding="utf-8")
        roster = tmp_path / "roster.txt"
        roster.write_text("# one name per line\nMarisol Vandersteen\n", encoding="utf-8")

        result = _run(
            str(source),
            "--reference",
            REFERENCE,
            "-o",
            str(tmp_path / "out"),
            "--roster",
            str(roster),
        )

        assert result.returncode == 0, result.stderr
        assert "Marisol" not in (tmp_path / "out.txt").read_text(encoding="utf-8")
        assert "Marisol" not in result.stdout + result.stderr

    def test_bare_numeric_ids_can_be_kept_for_numeric_data(self, tmp_path: Path) -> None:
        source = tmp_path / "data.txt"
        source.write_text("Account balances: 10000000 and 20000000.\n", encoding="utf-8")
        result = _run(
            str(source),
            "--reference",
            REFERENCE,
            "-o",
            str(tmp_path / "out"),
            "--keep-bare-numeric-ids",
        )
        assert result.returncode == 0, result.stderr
        assert "10000000" in (tmp_path / "out.txt").read_text(encoding="utf-8")


class TestRefusals:
    def test_it_refuses_to_write_under_tasks(self, raw_file: Path, tmp_path: Path) -> None:
        """The repo rule is stricter than the database rule, and this is where it binds.

        ``tasks/SCHEMA.md`` forbids real student material in ``tasks/`` even
        de-identified.  There is deliberately no override flag.
        """
        out = tmp_path / "tasks" / "midterm" / "item12"
        result = _run(str(raw_file), "--reference", REFERENCE, "-o", str(out))

        assert result.returncode == 2
        assert "tasks/" in result.stderr
        assert not out.with_suffix(".txt").exists()

    def test_the_tasks_guard_survives_a_traversal(self, raw_file: Path, tmp_path: Path) -> None:
        """Checked on the RESOLVED path, so ``a/../tasks/x`` is caught too."""
        out = tmp_path / "elsewhere" / ".." / "tasks" / "item12"
        result = _run(str(raw_file), "--reference", REFERENCE, "-o", str(out))
        assert result.returncode == 2
        assert "tasks/" in result.stderr

    def test_it_refuses_to_overwrite(self, raw_file: Path, tmp_path: Path) -> None:
        """The input may be the only copy of the raw material the operator has."""
        out = tmp_path / "item12"
        assert _run(str(raw_file), "--reference", REFERENCE, "-o", str(out)).returncode == 0
        again = _run(str(raw_file), "--reference", REFERENCE, "-o", str(out))
        assert again.returncode == 2
        assert "overwrite" in again.stderr

    def test_reference_is_required_when_cleaning(self, raw_file: Path, tmp_path: Path) -> None:
        result = _run(str(raw_file), "-o", str(tmp_path / "out"))
        assert result.returncode == 2
        assert "--reference is required" in result.stderr

    def test_a_missing_source_is_a_usage_error_not_a_traceback(self, tmp_path: Path) -> None:
        result = _run(str(tmp_path / "nope.txt"), "--check")
        assert result.returncode == 2
        assert "Traceback" not in result.stderr


class TestCheckMode:
    def test_check_fails_on_material_with_identifiers(self, raw_file: Path) -> None:
        result = _run(str(raw_file), "--check")
        assert result.returncode == 1
        for token in PLANTED:
            assert token not in result.stdout + result.stderr

    def test_check_passes_on_cleaned_output(self, raw_file: Path, tmp_path: Path) -> None:
        """Round trip: clean, then check the result.  This is the idempotency claim.

        The property proved in ``test_deid.py`` restated end-to-end through the
        tool an operator actually runs -- a pipeline whose second pass finds
        work to do would fail here.
        """
        out = tmp_path / "item12"
        assert _run(str(raw_file), "--reference", REFERENCE, "-o", str(out)).returncode == 0
        result = _run(str(out.with_suffix(".txt")), "--check")
        assert result.returncode == 0

    def test_check_writes_nothing(self, raw_file: Path, tmp_path: Path) -> None:
        before = sorted(p.name for p in tmp_path.iterdir())
        _run(str(raw_file), "--check")
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    def test_check_does_not_claim_anonymity(self, raw_file: Path, tmp_path: Path) -> None:
        """A green check is "these detectors find nothing", never "this is safe".

        The distinction is the whole honesty of the tool: an operator who reads
        exit 0 as a clearance will publish a re-identifiable short answer.
        """
        clean = tmp_path / "clean.txt"
        clean.write_text("The mean was 3.14 and the median 3.0.\n", encoding="utf-8")
        result = _run(str(clean), "--check")
        assert result.returncode == 0
        assert "NOT a certificate" in result.stdout
