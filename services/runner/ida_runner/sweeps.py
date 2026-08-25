"""Scheduled sweeps -- the CronJob entry points.

All three CronJobs run THIS module from the same image the runner uses, choosing
behaviour by argv (`ida-sweep <name>`). One image, three schedules.

⚠ EVERY SWEEP MUST BE IDEMPOTENT AND MUST EXIT NON-ZERO ON FAILURE. A CronJob
that exits 0 after failing looks successful forever, and nobody notices a nightly
job silently doing nothing until the numbers are needed.
"""

from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger("ida.sweep")

SWEEPS = {
    "rebenchmark": "Re-run the full suite against every non-deferred model.",
    "model-sweep": "Run one task suite across all models to compare them head to head.",
    "judge-calibration": "Re-score a held-out sample to check judge drift.",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheduled benchmark sweeps.")
    parser.add_argument("sweep", choices=sorted(SWEEPS), help="which sweep to run")
    parser.add_argument("--dry-run", action="store_true", help="log the plan, change nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("sweep=%s dry_run=%s -- %s", args.sweep, args.dry_run, SWEEPS[args.sweep])
    log.info("SCAFFOLD: no work performed yet")
    # Returns 0 because doing nothing successfully IS the current contract. The
    # moment real work lands here, propagate its failure -- see the module note.
    return 0


if __name__ == "__main__":
    sys.exit(main())
