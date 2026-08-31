"""What a model COSTS THE READER, in words a professor can act on.

⚠ THIS MODULE EXISTS BECAUSE TWO DIFFERENT COST NUMBERS LIVE IN THIS CODEBASE
AND ONLY ONE OF THEM IS A PRICE.

``RunRecord.total_cost_usd`` -- surfaced as ``ModelResult.total_cost_usd`` -- is
**our measurement spend**: what it cost *us* to run *our* samples through the
model on one task. It is a fact about our benchmark, not about the model. It is
``0`` on a cache hit (``ida_harness.runner``), ``0`` for every row the dev
seeder writes, and it moves whenever we add or remove samples. Reading it back
to a professor as "this model is cheap" would be handing them our invoice and
calling it their quote.

The rate card in ``models.yaml`` is the other number: **what the reader would be
billed**. It does not move when our sample counts move, it is the same figure
the provider publishes, and it is the only one of the two that belongs on a page
answering "which of these can I afford?".

⚠ WHY IT IS ITS OWN MODULE RATHER THAN LIVING WHERE IT WAS BORN. This
classification started life as ``recommend._cost_note`` and was correct there.
It is now needed by :mod:`ida_api.leaderboard` too -- and ``recommend`` already
imports *from* ``leaderboard``, so the obvious import would be a cycle. Copying
it into the second caller was the other option, and a second copy of "is this
model free, campus-hosted, or paid?" is exactly the drift the single-source rule
elsewhere in this package exists to prevent: the two would disagree the first
time a tier was added, and the disagreement would be between the recommendation
a professor is given and the price the results page shows them for the same
model.

The prose below is unchanged from that original -- it was reviewed as
professor-facing copy and this move is not the moment to re-word it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ida_core.contracts import ModelEntry


class CostNote(BaseModel):
    """One model's published price, plus how to read it.

    Deliberately not a bare pair of floats. "$0.20 in / $1.20 out per million
    tokens" is not a sentence a non-technical reader can act on, and the two
    zero-rate cases mean opposite things -- a campus model is free *because the
    university already bought the hardware*, and an unpriced third-party model is
    free only because nobody filled the field in. :attr:`tier` separates them so
    a consumer never has to infer it from the numbers being zero.
    """

    model_config = ConfigDict(extra="forbid")

    tier: Literal["free", "campus_hosted", "paid"]
    label: str
    detail: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float


def cost_note(entry: ModelEntry, residency: str) -> CostNote:
    """Classify a registry entry's rates.

    ``residency`` is :func:`ida_api.leaderboard.data_residency`'s verdict. It is
    passed in rather than recomputed so that a page showing the residency badge
    and the cost tier cannot show two answers derived from two readings of the
    same tags.
    """
    rates = entry.cost
    if rates.input_usd_per_mtok == 0 and rates.output_usd_per_mtok == 0:
        if residency == "on_campus":
            return CostNote(
                tier="campus_hosted",
                label="Free to you — runs on campus hardware",
                detail=(
                    "No per-use charge. The cost is the hardware the university already "
                    "owns, not a bill you receive."
                ),
                input_usd_per_mtok=0.0,
                output_usd_per_mtok=0.0,
            )
        return CostNote(
            tier="free",
            label="No per-token cost recorded",
            detail="The registry records no rates for this model.",
            input_usd_per_mtok=0.0,
            output_usd_per_mtok=0.0,
        )
    return CostNote(
        tier="paid",
        label=f"${rates.input_usd_per_mtok:.2f} in / ${rates.output_usd_per_mtok:.2f} out per million tokens",
        detail=(
            "A million tokens is roughly 700,000 words. For typical grading or item "
            "writing a professor's whole semester lands well inside a single-digit "
            "dollar figure — but check with your department before putting anything "
            "recurring on a card."
        ),
        input_usd_per_mtok=rates.input_usd_per_mtok,
        output_usd_per_mtok=rates.output_usd_per_mtok,
    )
