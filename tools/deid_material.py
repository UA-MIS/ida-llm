#!/usr/bin/env python3
"""De-identify a file of real course material.  The human front door to intake.

``docs/sensitive-material.md`` (D-49) makes cleaning on intake the gate, and
:mod:`ida_core.intake` implements it -- but there is no automated ingest
endpoint in this repository yet.  Today intake is *a person with an export*, so
this is the tool that person runs.  When the endpoint arrives it calls the same
:class:`~ida_core.intake.IntakePipeline`; this stays useful for one-off imports.

    tools/deid_material.py raw.txt --reference "MIS 200 F24 midterm" -o cleaned/item12

writes ``cleaned/item12.txt`` (the cleaned text) and
``cleaned/item12.provenance.json`` (reference, SHA-256 of the RAW source, and
the cleaning report -- never the raw content), then prints what was removed.

    tools/deid_material.py suspect.txt --check

exits non-zero if the file still contains anything the detectors recognise.
That is the form to put in a pre-commit hook or a CI job.

--------------------------------------------------------------------------
THREE THINGS THIS DELIBERATELY REFUSES TO DO
--------------------------------------------------------------------------

**It never prints the material.**  Not the input, not a diff, not an "example of
what was removed".  A terminal is scrollback, a CI job is a public log, and a
tool whose output has to be handled as carefully as its input is a tool that
will eventually be run in the wrong window.  Counts only.

**It refuses to write under ``tasks/``.**  The repo rule is stricter than the
database rule: ``tasks/SCHEMA.md`` § "No real student work" forbids real student
material in ``tasks/`` *even de-identified*, because a short answer is
re-identifiable from its content.  Cleaning is what lets material into the
DATABASE; a synthetic stand-in plus a provenance pointer is what goes in the
repo.  The guard exists because that distinction is exactly the one a tired
person collapses at 2am, and the flag to override it is deliberately absent.

**It does not overwrite.**  The input is the only copy of the raw material the
operator holds, and a de-identifier that can clobber its own source with its
output is one typo away from destroying the thing the hash is supposed to point
at.

Exit codes: 0 clean/success, 1 PII found in ``--check``, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ida_core.deid import DEID_RULESET_VERSION, DeidConfig, Roster, contains_detectable_pii
from ida_core.intake import INTAKE_PIPELINE_VERSION, CleanedMaterial, IntakePipeline

OK = "  ok"
BAD = "FAIL"


class UsageError(Exception):
    """A problem with what the operator asked for, reported without a traceback."""


def _load_roster(path: Path | None) -> Roster | None:
    """Read a roster file: one name per line, ``#`` comments ignored.

    **A roster file is PII and must never be committed.**  It is passed by path
    rather than by argument so it does not land in shell history, and it is
    never echoed -- see :class:`~ida_core.deid.Roster`, whose repr is redacted
    for the same reason.
    """
    if path is None:
        return None
    if not path.is_file():
        raise UsageError(f"roster file not found: {path}")
    names = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return Roster(names)


def _guard_output_path(out_base: Path) -> None:
    """Refuse to write cleaned real material into ``tasks/``.

    Walks the resolved path rather than matching a prefix string, so
    ``a/../tasks/x`` and a symlink both land in the same place the check does.
    """
    resolved = out_base.resolve()
    if any(part == "tasks" for part in resolved.parts):
        raise UsageError(
            f"refusing to write under a 'tasks/' directory: {resolved}\n"
            "  tasks/SCHEMA.md forbids real student material in tasks/ even de-identified, "
            "because a short answer is re-identifiable from its content. Cleaning admits "
            "material to the DATABASE; the repo takes a synthetic stand-in plus a "
            "provenance pointer (docs/sensitive-material.md § 4)."
        )


def _report_lines(material: CleanedMaterial) -> list[str]:
    """Counts and caveats.  Never a value, never an excerpt."""
    lines = [
        f"{OK}  cleaned {material.provenance.byte_length} bytes "
        f"(source sha256 {material.provenance.sha256[:12]}...)",
        f"      pipeline v{material.pipeline_version}, "
        f"deid ruleset v{material.report.ruleset_version}",
    ]
    if material.report.changed:
        for kind, count in sorted(material.report.counts.items()):
            lines.append(f"      removed {count:>4}  {kind}")
    else:
        lines.append("      removed    0  (nothing the detectors recognise was present)")
    lines.append("")
    lines.append("  This pass does NOT guarantee anonymity:")
    lines.extend(f"    * {risk}" for risk in material.report.residual_risk)
    return lines


def _run_check(text: str, roster: Roster | None, config: DeidConfig, source: Path) -> int:
    found = contains_detectable_pii(text, roster=roster, config=config)
    if found:
        print(f"{BAD}  {source}: detectable personal identifiers present", file=sys.stderr)
        print(
            "      Run without --check to clean it. Nothing is printed about what "
            "was found, by design.",
            file=sys.stderr,
        )
        return 1
    print(f"{OK}  {source}: no detectable personal identifiers")
    print(
        "      NOT a certificate of anonymity -- only that these detectors "
        "(ruleset v" + DEID_RULESET_VERSION + ") find nothing. A human still reads it."
    )
    return 0


def _run_clean(
    text: str,
    *,
    reference: str,
    roster: Roster | None,
    config: DeidConfig,
    out_base: Path,
) -> int:
    _guard_output_path(out_base)
    text_path = out_base.with_suffix(".txt")
    provenance_path = out_base.with_suffix(".provenance.json")
    for path in (text_path, provenance_path):
        if path.exists():
            raise UsageError(f"refusing to overwrite {path}: move it aside or choose another -o")

    material = IntakePipeline(roster=roster, config=config).ingest_text(
        reference=reference, text=text
    )

    out_base.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(material.text, encoding="utf-8")
    provenance_path.write_text(
        json.dumps(
            {
                "provenance": material.provenance.model_dump(mode="json"),
                "cleaned_sha256": material.cleaned_sha256,
                "cleanliness": material.cleanliness.value,
                "report": material.report.model_dump(mode="json"),
                "provenance_sentence": material.provenance_sentence(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\n".join(_report_lines(material)))
    print()
    print(f"  cleaned text  -> {text_path}")
    print(f"  provenance    -> {provenance_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source", type=Path, help="file of raw material to clean")
    parser.add_argument(
        "--reference",
        help="one-line citation of where the material came from (required unless --check)",
    )
    parser.add_argument("-o", "--out", type=Path, help="output path WITHOUT extension")
    parser.add_argument(
        "--roster",
        type=Path,
        help="file of known names, one per line. PII -- never commit one",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether identifiers remain; write nothing. Exit 1 if any are found",
    )
    parser.add_argument(
        "--keep-bare-numeric-ids",
        action="store_true",
        help="do not redact unlabelled 8-10 digit runs (use for numeric DATA, not rosters)",
    )
    args = parser.parse_args(argv)

    try:
        if not args.source.is_file():
            raise UsageError(f"source file not found: {args.source}")
        text = args.source.read_text(encoding="utf-8")
        roster = _load_roster(args.roster)
        config = DeidConfig(redact_bare_numeric_ids=not args.keep_bare_numeric_ids)

        if args.check:
            return _run_check(text, roster, config, args.source)
        if not args.reference:
            raise UsageError(
                "--reference is required: material nobody can attribute is material "
                "nobody can withdraw (docs/sensitive-material.md § 4)"
            )
        if not args.out:
            raise UsageError("-o/--out is required when cleaning")
        return _run_clean(
            text,
            reference=args.reference,
            roster=roster,
            config=config,
            out_base=args.out,
        )
    except UsageError as exc:
        print(f"{BAD}  {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeDecodeError) as exc:
        # Never `exc` alone in a message that might carry file content; OSError
        # and UnicodeDecodeError both stringify to a path plus a reason, which
        # is safe, but be explicit about which errors are allowed through here.
        print(f"{BAD}  could not read {args.source}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    print(
        f"ida de-identification -- intake pipeline v{INTAKE_PIPELINE_VERSION}, "
        f"deid ruleset v{DEID_RULESET_VERSION}\n",
        file=sys.stderr,
    )
    sys.exit(main())
