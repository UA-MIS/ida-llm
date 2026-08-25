#!/usr/bin/env python3
"""Re-render the README's mermaid diagrams to the SVGs the sprint board serves.

This is what ``make diagrams`` runs. ``README.md`` is the source of truth: the
diagrams are authored there as ```mermaid fences, GitHub renders them natively,
and the committed SVGs under ``apps/agile/public/`` are build output for the
board, which cannot run mermaid. Extracting from the README rather than from a
pair of side-by-side ``.mmd`` files is deliberate -- two copies of one drawing
drift, and the README copy is the one people edit.

THE CONFIG IS NOT OPTIONAL
--------------------------
``htmlLabels`` must be false **at the top level**, and that is the whole reason
this script exists instead of a line in a README:

    mermaid default ................................ 64 foreignObject elements
    flowchart: {htmlLabels: false} alone ........... 28 foreignObject elements
    top-level htmlLabels: false .................... 0

Mermaid puts label text inside ``<foreignObject>`` by default, and a browser
does not render foreignObject when an SVG is loaded through ``<img src>`` --
which is exactly what markdown ``![](...)`` produces. Rendered with the natural
config, both diagrams come out as boxes and arrows with **every label
invisible**, and they look fine in a browser tab, so the breakage survives a
casual check. The nested-only setting is the dangerous one: it removes most of
them and reads like it worked.

So this script asserts the invariant on its own output and fails loudly rather
than writing a subtly broken asset.

Exit codes: 0 rendered, 1 something was wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Rendered in the order they appear in the README, one output each. Adding a
# third diagram means adding a third entry here AND a third fence there; the
# count check below refuses to guess which is which.
OUTPUTS = ("architecture.svg", "workflow.svg")

MERMAID_CONFIG = {
    "theme": "base",
    # Top level, NOT only under `flowchart` -- see the module docstring.
    "htmlLabels": False,
    "flowchart": {"htmlLabels": False, "useMaxWidth": False},
}

# Chromium cannot use its sandbox in most CI containers and in some desktop
# distributions (unprivileged user namespaces disabled by AppArmor). Without
# this, mermaid-cli fails with "No usable sandbox!" and no hint that the
# diagram itself is fine.
PUPPETEER_CONFIG = {"args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]}

MERMAID_CLI = "@mermaid-js/mermaid-cli@11"

FENCE = re.compile(r"^```mermaid\n(.*?)^```", re.MULTILINE | re.DOTALL)


def extract(readme: Path) -> list[str]:
    """Every ```mermaid block in the README, in document order."""
    blocks = [m.group(1) for m in FENCE.finditer(readme.read_text(encoding="utf-8"))]
    if len(blocks) != len(OUTPUTS):
        raise SystemExit(
            f"{readme}: found {len(blocks)} mermaid block(s), expected {len(OUTPUTS)}.\n"
            f"Update OUTPUTS in {__file__} if a diagram was added or removed."
        )
    return blocks


def render(source: str, out: Path, workdir: Path, npx: str) -> None:
    """Compile one mermaid block to an SVG, then verify it is <img>-safe."""
    mmd = workdir / f"{out.stem}.mmd"
    mmd.write_text(source, encoding="utf-8")

    cfg = workdir / "mermaid.json"
    cfg.write_text(json.dumps(MERMAID_CONFIG), encoding="utf-8")
    pcfg = workdir / "puppeteer.json"
    pcfg.write_text(json.dumps(PUPPETEER_CONFIG), encoding="utf-8")

    # Render to a scratch path and publish only after the checks pass. Writing
    # `out` directly would leave a broken SVG committed-in-place on the very
    # failure this function exists to catch.
    staged = workdir / out.name
    subprocess.run(  # noqa: S603 -- fixed argv, no shell, paths are ours
        [
            npx,
            "-y",
            MERMAID_CLI,
            "-i",
            str(mmd),
            "-o",
            str(staged),
            "-c",
            str(cfg),
            "-p",
            str(pcfg),
            "-b",
            "white",
        ],
        check=True,
    )

    svg = staged.read_text(encoding="utf-8")
    if "foreignObject" in svg:
        raise SystemExit(
            f"{out.name}: rendered with <foreignObject>, so every label would be invisible "
            f"when the board loads it through <img src>. htmlLabels must be false at the TOP "
            f"level of the mermaid config, not only under `flowchart`. Nothing was written."
        )
    if not svg.lstrip().startswith("<svg"):
        raise SystemExit(f"{out.name}: does not look like an SVG. Nothing was written.")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("npx not found. Node 22+ is needed to render the diagrams.")

    readme = args.root / "README.md"
    public = args.root / "apps" / "agile" / "public"

    blocks = extract(readme)
    with tempfile.TemporaryDirectory() as tmp:
        for source, name in zip(blocks, OUTPUTS, strict=True):
            out = public / name
            render(source, out, Path(tmp), npx)
            print(f"  {out.relative_to(args.root)}")

    print(f"\n{len(blocks)} diagram(s) rendered from {readme.name}; 0 foreignObject in each.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
