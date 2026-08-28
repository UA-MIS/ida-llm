"""The intake gate: provenance, the cleaned/uncleaned flag, and the seam.

``docs/sensitive-material.md`` (D-49) is ratified policy and it turns on one
sentence: *cleaning on intake is the gate*.  Cleaned material may live in our
database, be used as task content, be sent to a model provider and appear in
public results.  **Uncleaned material may do none of those things.**

:mod:`ida_core.deid` does the cleaning.  This module answers the question that
makes the cleaning enforceable rather than aspirational:

    given a piece of material, did it come through the pipeline?

The answer is carried by the *type*, not by a boolean somebody has to set.
:class:`CleanedMaterial` is constructible only by :class:`IntakePipeline`; a
``str``, a ``dict`` or a :class:`RawMaterial` is by definition **not cleaned**,
and :func:`require_cleaned` refuses all of them.  That is the "flag material
that arrived without going through it as not usable" requirement: there is no
flag to forget to set, because the absence of the type IS the flag.

--------------------------------------------------------------------------
THE THREE THINGS THIS RECORDS
--------------------------------------------------------------------------

1. **Provenance as a pointer, never as content** (§ 4 of the policy).
   :class:`SourceProvenance` holds a one-line human reference and the SHA-256 of
   the raw source -- and has no field capable of holding the source itself.
   Someone with authorised access to the original can confirm which item a task
   derives from; nobody else learns anything.  ``tasks/SCHEMA.md`` warns that
   sample ``metadata`` is served **unauthenticated**, which is exactly why the
   pointer is a hash rather than an excerpt.

2. **What the cleaning pass did** -- :class:`~ida_core.deid.DeidReport`, which
   carries counts and caveats and deliberately no values.

3. **Which rules did it** -- :data:`INTAKE_PIPELINE_VERSION` and the report's
   ruleset version.  Material cleaned in March by a weaker detector is still
   cleaned, but it is not cleaned *the same way*, and without these two fields
   there is no query that finds it.

--------------------------------------------------------------------------
WHERE THIS IS WIRED, AND WHERE IT IS NOT (READ THIS BEFORE EXTENDING IT)
--------------------------------------------------------------------------

There is **no automated intake flow in this repository yet** -- that is the gap
``docs/sensitive-material.md`` names, and it is honest to say so here rather
than imply a pipeline that does not run.  Today, intake is a person with an
export, and ``tools/deid_material.py`` is their front door.

So this module ships the gate and the seam rather than a wiring into code that
does not exist:

* **the human path**: ``tools/deid_material.py``, which cleans a file, writes a
  provenance sidecar and refuses to write into ``tasks/``;
* **the task-content seam**: :meth:`CleanedMaterial.to_task_sample`, which
  builds a :class:`~ida_core.contracts.TaskSample` carrying the provenance
  pointer § 4 requires;
* **the model-call seam**: :func:`require_cleaned`, which is the single call to
  put in front of any future ``POST /materials`` handler, ingest job or solver
  path that could be handed material.

When the intake endpoint is built, it calls :meth:`IntakePipeline.ingest_text`
and stores a :class:`CleanedMaterial`; nothing else in this module changes.

--------------------------------------------------------------------------
THE REPO IS STRICTER THAN THE DATABASE
--------------------------------------------------------------------------

Do not read "cleaned" as "committable".  The two rules are different and the
repo's is tighter:

* the **database** may hold cleaned real material (this module's subject);
* **``tasks/**.yaml``** may not hold real student work *at all*, cleaned or not
  -- ``tasks/SCHEMA.md`` § "No real student work", "not even with names
  removed", because a short answer is re-identifiable from its content.  For
  repo-committed task content the answer is a synthetic stand-in plus a
  provenance pointer, which is what ``tasks/conceptual-grading/`` already does.

:meth:`CleanedMaterial.to_task_sample` therefore builds an **in-memory** sample
for database-held material.  Serialising its output into a file under ``tasks/``
would satisfy this module and violate ``tasks/SCHEMA.md``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ida_core.contracts import TaskSample
from ida_core.deid import DeidConfig, DeidReport, Roster, deidentify

INTAKE_PIPELINE_VERSION = "1"
"""Which pipeline shape produced a :class:`CleanedMaterial`.

Distinct from :data:`~ida_core.deid.DEID_RULESET_VERSION`: the ruleset version
moves when a *detector* changes, this moves when the *pipeline* does -- a new
recorded field, a changed normalisation, a different provenance rule.  Two
numbers because "re-run the detectors" and "re-ingest the material" are
different remediations, and a single version cannot tell you which you need.
"""

_MAX_REFERENCE_LENGTH = 300

_POLICY = "docs/sensitive-material.md"


class Cleanliness(StrEnum):
    """Whether a piece of material has been through the intake pipeline.

    Two states and no third: there is no "partially cleaned" and no "probably
    fine".  The policy is binary -- cleaned material may be stored, prompted and
    published; uncleaned material may not -- so a middle value would only give
    a caller somewhere to put a judgement call the policy does not allow.

    A *serialisation* of the flag, for a database column, an API field or a log
    line.  In code the type is the flag: :class:`CleanedMaterial` is cleaned and
    everything else is not, which is why neither class lets you assign this.
    """

    CLEANED = "cleaned"
    NOT_CLEANED = "not_cleaned"


class SourceProvenance(BaseModel):
    """Where cleaned material came from -- **by pointer, never by content**.

    The class has no field that can hold the source text.  That is the control,
    not an omission: provenance travels into sample metadata, which
    ``GET /tasks/{id}`` serves unauthenticated, so a field that *could* carry an
    excerpt eventually would.

    The hash is what makes the pointer useful without the content: someone with
    authorised access to the original can recompute it and confirm the match,
    and nobody without that access learns anything from 64 hex characters.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: str
    """A one-line human citation, e.g. ``"MIS 200 Fall 2024, midterm item 12"``.

    Constrained to one line and 300 characters because the failure mode is a
    caller pasting the material in here -- the one field in this class that
    *could* hold content, defended by shape.  See :meth:`_check_reference`.
    """

    sha256: str
    """Lowercase hex SHA-256 of the **raw** source, UTF-8 encoded."""

    byte_length: int = Field(ge=0)
    """Length of the raw source in UTF-8 bytes.

    Cheap corroboration: a hash alone cannot distinguish "the file I expected"
    from "a file", and a length that is wildly off is a visible signal that the
    pointer refers to something else -- an excerpt, a re-export, a truncation.
    """

    retrieved_at: datetime | None = None

    @field_validator("reference")
    @classmethod
    def _check_reference(cls, value: str) -> str:
        """A citation, not a payload.

        Three refusals, each for a mistake that would otherwise be silent:
        empty (unattributable material is not provenanced material), multi-line
        (a pasted document), and over-long (an excerpt).  Rejecting is right
        rather than truncating -- a silently shortened citation still reads as a
        citation while having lost the part that identified the source.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("provenance reference must not be empty: name the source")
        if "\n" in stripped or "\r" in stripped:
            raise ValueError(
                "provenance reference must be one line -- it is a citation, not the material"
            )
        if len(stripped) > _MAX_REFERENCE_LENGTH:
            raise ValueError(
                f"provenance reference must be at most {_MAX_REFERENCE_LENGTH} characters; "
                f"got {len(stripped)}. It is a citation, not an excerpt -- the SHA-256 is "
                "what identifies the content."
            )
        return stripped

    @field_validator("sha256")
    @classmethod
    def _check_sha(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"sha256 must be 64 lowercase hex characters, got {value!r}")
        return value

    @classmethod
    def of_text(
        cls,
        *,
        reference: str,
        text: str,
        retrieved_at: datetime | None = None,
    ) -> SourceProvenance:
        """Hash ``text`` and build the pointer.  ``text`` is not retained."""
        encoded = text.encode("utf-8")
        return cls(
            reference=reference,
            sha256=hashlib.sha256(encoded).hexdigest(),
            byte_length=len(encoded),
            retrieved_at=retrieved_at,
        )


class RawMaterial(BaseModel):
    """Material as it arrived.  **Not usable for anything until cleaned.**

    Deliberately thin, and deliberately awkward: it exists to be held for the
    moment between reading a source and cleaning it, and to be *refused* by
    :func:`require_cleaned` everywhere else.

    Its :meth:`__repr__` is redacted.  A pydantic default repr renders every
    field, so an uncleaned education record inside a validation error, a
    ``pytest`` assertion or a logged exception would print in full -- a
    disclosure caused by debugging output rather than by any decision anyone
    made.  The reference and the hash still print, which is everything an
    operator needs to identify *which* item failed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: str
    text: str
    retrieved_at: datetime | None = None

    @property
    def cleanliness(self) -> Literal[Cleanliness.NOT_CLEANED]:
        """Always :attr:`Cleanliness.NOT_CLEANED`.  There is no way to set it."""
        return Cleanliness.NOT_CLEANED

    @property
    def provenance(self) -> SourceProvenance:
        """The pointer, computable before cleaning.

        Provenance is not what the gate withholds -- knowing where an item came
        from is safe, and useful in an error message about material that could
        not be cleaned.  What the gate withholds is *use of the content*.
        """
        return SourceProvenance.of_text(
            reference=self.reference, text=self.text, retrieved_at=self.retrieved_at
        )

    def __repr__(self) -> str:
        encoded_length = len(self.text.encode("utf-8"))
        return (
            f"RawMaterial(reference={self.reference!r}, "
            f"sha256={self.provenance.sha256!r}, "
            f"text=<redacted, {encoded_length} bytes, NOT CLEANED>)"
        )

    __str__ = __repr__


class CleanedMaterial(BaseModel):
    """Material that has been through the pipeline.  The only usable kind.

    Construct it through :class:`IntakePipeline`, never directly: an instance
    built by hand asserts a cleaning that did not happen, and every downstream
    check trusts the type.  (Python cannot forbid that construction, and
    pretending otherwise would be worse than saying so -- the seam is a
    convention backed by review, like every other "call this, not that" rule in
    this codebase.  What it does buy is that the mistake has to be *written*,
    deliberately, rather than made by forgetting a step.)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance: SourceProvenance
    """Pointer to the RAW source -- never re-stamped, however often it is re-cleaned."""

    text: str
    """The cleaned text.  Safe for the database, task content, model calls and public results."""

    report: DeidReport
    cleaned_sha256: str
    """SHA-256 of :attr:`text`.

    Answers a different question from :attr:`provenance.sha256`: this is the
    dedup and cache key (two sources that clean to the same text are the same
    content), that one is the provenance pointer (which item did this come
    from).  Both are kept because collapsing them loses one of the two answers.
    """

    pipeline_version: str = INTAKE_PIPELINE_VERSION

    @property
    def cleanliness(self) -> Literal[Cleanliness.CLEANED]:
        return Cleanliness.CLEANED

    def provenance_sentence(self) -> str:
        """One line naming the source by reference and hash, for a ``description``.

        ``tasks/SCHEMA.md`` § 3 requires a provenance sentence in prose and
        gives it nowhere machine-readable to live, so this generates the exact
        sentence rather than leaving each author to invent one.
        """
        return (
            f"Provenance: de-identified real course material; source "
            f"{self.provenance.reference} (sha256 {self.provenance.sha256}). "
            f"Cleaned by intake pipeline v{self.pipeline_version}, "
            f"deid ruleset v{self.report.ruleset_version}."
        )

    def provenance_metadata(self) -> dict[str, Any]:
        """The § 4 pointer, shaped for sample ``metadata``.

        Safe to serve unauthenticated: a reference, a hash, and the versions
        that produced the cleaning.  No content, and nothing from which content
        can be recovered.
        """
        return {
            "provenance": "de-identified",
            "source_ref": self.provenance.reference,
            "source_sha256": self.provenance.sha256,
            "deid_ruleset_version": self.report.ruleset_version,
            "intake_pipeline_version": self.pipeline_version,
        }

    def to_task_sample(
        self,
        sample_id: str,
        *,
        target: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskSample:
        """Build an in-memory :class:`~ida_core.contracts.TaskSample` from this material.

        The task-content half of the seam: cleaned material becomes a sample
        whose ``metadata`` carries the provenance pointer, which is what
        ``docs/sensitive-material.md`` § 4 asks for.

        **Do not serialise the result into ``tasks/**.yaml``.**  The repo rule is
        stricter than the database rule -- see this module's docstring -- and a
        cleaned real student answer is committable nowhere in ``tasks/``.  This
        exists for material held in our own database.

        Caller ``metadata`` is merged, but may not overwrite a provenance key:
        a sample pointing at a source it did not come from is worse than one
        with no pointer, because a forged pointer reads as verified.
        """
        provenance = self.provenance_metadata()
        merged = dict(metadata or {})
        clashes = sorted(set(merged) & set(provenance))
        if clashes:
            raise ValueError(
                f"metadata may not overwrite provenance key(s) {clashes}: these record where "
                f"this material actually came from, and are set by intake, not by the caller"
            )
        merged.update(provenance)
        return TaskSample(id=sample_id, input=self.text, target=target, metadata=merged)


class UncleanedMaterialError(RuntimeError):
    """Material that has not been through intake was about to be used.

    Raised by :func:`require_cleaned`.  A hard error rather than a warning
    because every use this guards -- storing, prompting, publishing -- is
    irreversible once it happens: a model provider has seen the text, or an
    artifact carrying it is in the object store and on the public results page.
    There is no un-sending.
    """


def require_cleaned(material: object, *, purpose: str) -> CleanedMaterial:
    """Return ``material`` if it came through intake; raise otherwise.

    **The gate.**  Put this in front of anything that stores material, sends it
    to a model, or publishes it -- ``purpose`` names which, and lands in the
    error so the failure says what was about to happen rather than only what was
    wrong.

    Refuses ``str`` explicitly rather than duck-typing on ``.text``, because a
    bare string is the realistic mistake: the natural way to write the wrong
    thing is to pass the text straight through.  Duck-typing would accept any
    object that happens to have a ``text`` attribute -- including
    :class:`RawMaterial`, which is precisely the thing to stop.

    >>> require_cleaned("some text", purpose="a model call")
    Traceback (most recent call last):
    ida_core.intake.UncleanedMaterialError: ...
    """
    if isinstance(material, CleanedMaterial):
        return material
    described = "RawMaterial" if isinstance(material, RawMaterial) else type(material).__name__
    raise UncleanedMaterialError(
        f"refusing {purpose}: material is {described}, which has not been through the "
        f"de-identification pipeline, so it is NOT cleaned material and is not usable "
        f"({_POLICY}, D-49). Run it through IntakePipeline.ingest_text() first."
    )


class IntakePipeline:
    """Cleaning on intake -- the gate, as a callable.

    Holds the roster and the detector configuration so that every piece of
    material from one source is cleaned by the same rules; construct one per
    course or per import, not one per document.
    """

    __slots__ = ("_config", "_roster")

    def __init__(self, *, roster: Roster | None = None, config: DeidConfig | None = None) -> None:
        self._roster = roster
        self._config = config or DeidConfig()

    def ingest_text(
        self,
        *,
        reference: str,
        text: str,
        retrieved_at: datetime | None = None,
    ) -> CleanedMaterial:
        """Clean ``text`` and stamp its provenance.  The entry point for new material.

        ``reference`` is required and unvalidatable by machine -- no check can
        tell a true citation from a plausible one.  It is mandatory anyway,
        because material nobody can attribute is material nobody can withdraw.
        """
        provenance = SourceProvenance.of_text(
            reference=reference, text=text, retrieved_at=retrieved_at
        )
        return self._clean(provenance, text)

    def ingest(self, material: RawMaterial | CleanedMaterial) -> CleanedMaterial:
        """Clean ``material``, idempotently.

        * :class:`RawMaterial` -> cleaned, provenance stamped from the raw text.
        * :class:`CleanedMaterial` that is still clean under **these** rules ->
          returned unchanged, the same object.  That is the no-op the story
          asks for, and it is checked rather than assumed: the text is re-run,
          and identity is returned only because nothing was found.
        * :class:`CleanedMaterial` that this pipeline can clean *further* -- a
          wider roster, a newer ruleset -- -> a new object with the additional
          redactions applied and the **original provenance preserved**.

        That last case is why re-ingestion re-runs rather than short-circuiting
        on the type.  "Already cleaned" must not mean "exempt from a better
        detector": the rows most in need of re-cleaning are exactly the ones
        already marked clean.

        A bare ``str`` is a :class:`TypeError`, not an implicit ingest -- text
        with no reference has no provenance, and provenance is not optional.
        """
        if isinstance(material, RawMaterial):
            return self._clean(material.provenance, material.text)
        if isinstance(material, CleanedMaterial):
            recleaned = self._clean(material.provenance, material.text)
            if recleaned.text == material.text:
                return material
            return recleaned
        raise TypeError(
            f"ingest() takes RawMaterial or CleanedMaterial, got {type(material).__name__}. "
            "For text, use ingest_text(reference=..., text=...) -- material without a "
            "reference has no provenance."
        )

    def _clean(self, provenance: SourceProvenance, text: str) -> CleanedMaterial:
        result = deidentify(text, roster=self._roster, config=self._config)
        return CleanedMaterial(
            provenance=provenance,
            text=result.text,
            report=result.report,
            cleaned_sha256=hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
            pipeline_version=INTAKE_PIPELINE_VERSION,
        )
