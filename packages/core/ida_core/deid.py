"""De-identification of real course material.  The text-level half of the intake gate.

``docs/sensitive-material.md`` (D-49) makes **cleaning on intake** the gate:
cleaned material may live in our database, be used as task content, be sent to a
model provider and appear in public results; uncleaned material may do none of
those things.  This module is the cleaning.  :mod:`ida_core.intake` is the gate
that decides whether a given piece of material has been through it.

It lives in ``ida_core`` for the same reason
:func:`~ida_core.contracts._target_leaks_into_metadata` does: a rule that binds
only when someone remembers to call a CLI binds nowhere.  Everything that can
reach material -- the API, the runner, the harness, a human at a terminal --
imports from here.

Nothing in this module talks to a model, reads a file or holds state.  It is a
pure function from text to text plus a report.

--------------------------------------------------------------------------
WHAT THIS CATCHES, AND WHAT IT HONESTLY DOES NOT
--------------------------------------------------------------------------

**Catches**, reliably, by pattern: email addresses, US phone numbers, US SSNs,
labelled identifier fields (``Student ID:``, ``CWID:``, ``NetID:``), bare 8-10
digit identifier runs, ``@handle`` usernames, labelled submission timestamps,
honorific-led names (``Dr. Achterberg``), labelled name fields (``Student:``),
and -- **when a roster is supplied** -- every roster name anywhere in the text,
including the ``Last, First`` form.

**Does not catch.**  This is a redaction pass, not a proof of anonymity:

* **Re-identification by content.**  ``tasks/SCHEMA.md`` § 1 states the standard
  plainly -- de-identification is *higher than deleting a name*, because a
  short-answer response is often re-identifiable from what it says.  "The
  student who missed the midterm for the away game in Baton Rouge" survives this
  module intact.  No regex closes that gap; a human read does.
* **Free-text personal names with no roster.**  Without a roster, a name in the
  middle of a sentence is just a capitalised word.  Supply a roster, or accept
  that names remain.  The report says which happened, every time.
* **Non-US phone formats, international student numbers, and identifier schemes
  this file has never seen.**  Extend :data:`DeidConfig.extra_patterns` rather
  than assuming coverage.
* **Anything outside the text**: a filename, a PDF's author metadata, an image
  of a signature, a spreadsheet's second sheet.  Cleaning the string you pass in
  says nothing about the container you got it from.

The consequence is written into the output rather than left to memory:
:attr:`DeidReport.residual_risk` carries these warnings on **every** call, so a
caller storing a report also stores the reasons it is not a clean bill of
health.

**It over-redacts on purpose.**  A bare eight-digit number becomes
``[REDACTED:STUDENT_ID]`` whether it was a CWID or a count of something.  For a
privacy gate that is the correct direction to be wrong in, and the negative
fixtures in ``packages/core/tests/_synthetic_pii.py`` pin how far it goes: a
year, a decimal, a section number and a point allocation all survive untouched.
Set ``redact_bare_numeric_ids=False`` when the material is known to be numeric
data rather than a roster export.

Two false positives are worth naming rather than discovering:

* a labelled field takes its **whole value**, so ``Criterion name: clarity``
  loses "clarity" -- the ``name:`` label cannot tell a person from a property.
  Harmless in prose, destructive in structured material, so clean the *values*
  of a structured document rather than its serialised form;
* a bare digit run of identifier length is removed wherever it sits, so material
  that is genuinely a table of long numbers needs
  ``redact_bare_numeric_ids=False``.

Both are visible in the output -- a placeholder is conspicuous -- which is the
argument for erring this way: over-redaction is a thing a reader notices and
can undo from the source, and under-redaction is a thing nobody notices at all.

--------------------------------------------------------------------------
IDEMPOTENCY IS STRUCTURAL, NOT INCIDENTAL
--------------------------------------------------------------------------

Cleaning already-clean material must be a no-op -- material gets re-ingested,
re-imported and re-processed, and a pipeline that mangles its own output on the
second pass corrupts the corpus quietly.

It is guaranteed by construction rather than by hoping no detector matches a
placeholder: every span already matching :data:`PLACEHOLDER_RE` is marked
**protected** before detection runs, and any detection overlapping a protected
span is discarded.  So a placeholder is inert input no matter what label
precedes it, and the second pass reports zero detections rather than merely
producing the same bytes.  ``TestIdempotency`` asserts both.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

DEID_RULESET_VERSION = "1"
"""Which set of detectors produced a redaction.

Recorded on every :class:`DeidReport` and carried into the database by
:class:`~ida_core.intake.CleanedMaterial`.  When a detector improves, rows
cleaned by an older ruleset are still cleaned -- but cleaned by *weaker* rules,
and this field is the only way to find them and re-run.  Bump it whenever a
detector is added, widened or fixed; a version that never moves is a version
nobody can act on.
"""


class PiiKind(StrEnum):
    """The categories this module can redact.

    The *name* of the member is what appears in a placeholder, so these are part
    of the on-disk format: renaming one invalidates every previously cleaned
    document, because its placeholders stop being recognised as placeholders.
    Add members freely; rename them only with a migration.
    """

    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    STUDENT_ID = "student_id"
    USERNAME = "username"
    NAME = "name"
    SUBMISSION_TIMESTAMP = "submission_timestamp"


PLACEHOLDER_RE = re.compile(r"\[REDACTED:[A-Z_]+\]")
"""What a redaction looks like once applied -- and what a later pass protects.

Deliberately matches ``[REDACTED:ANYTHING]``, not only today's
:class:`PiiKind` members: material cleaned by a *future* ruleset with a category
this build has never heard of must still be treated as already-cleaned here,
rather than having its unfamiliar placeholders picked apart.
"""


def placeholder_for(kind: PiiKind) -> str:
    """The replacement text for ``kind``.

    Typed rather than a bare ``[REDACTED]`` because a reader of cleaned material
    needs to know *what* was removed -- "a name was here" and "an eight-digit
    number was here" support very different downstream judgements, and a
    reviewer checking the pass needs to see the shape of what went.
    """
    return f"[REDACTED:{kind.name}]"


# --------------------------------------------------------------------------
# Roster
# --------------------------------------------------------------------------


class Roster:
    """Known personal names, used to find them in free prose.

    **A roster is itself PII.**  It is a list of the people in a course.  It must
    never be committed, never be logged, and never be serialised into an
    artefact -- which is why this is a plain object with a redacting
    :meth:`__repr__` rather than a pydantic model: a ``BaseModel`` would
    cheerfully render every name into a validation error or a ``model_dump``,
    and the failure would look like ordinary debugging output.

    Supplying one is what turns name detection from a heuristic into an exact
    match.  Without it, ``deidentify`` still runs -- it just cannot see a name
    that is not preceded by a label or an honorific, and says so in the report.
    """

    __slots__ = ("_name_count", "_terms")

    def __init__(self, names: Iterable[str]) -> None:
        supplied = [n for n in names if n and n.strip()]
        self._name_count = len(supplied)
        self._terms = self._expand(supplied)

    @staticmethod
    def _expand(names: Iterable[str]) -> tuple[str, ...]:
        """Every written form of every name, longest first.

        A roster holds ``"Marisol Vandersteen"``; material writes
        ``Vandersteen, Marisol`` in an export, ``Marisol`` in prose and
        ``Vandersteen`` in a comment.  All four have to go.

        Parts shorter than three characters are expanded only inside a full
        name, never on their own: a roster containing ``"Bo Achterberg"`` must
        not redact the word "bo" out of a sentence about a bo staff.  That is
        the one place this class steps back from over-redacting, because a
        two-letter match shreds ordinary prose rather than merely coarsening it.
        """
        terms: set[str] = set()
        for raw in names:
            name = " ".join(raw.split())
            if not name:
                continue
            parts = name.split(" ")
            terms.add(name)
            if len(parts) >= 2:
                # The `Last, First` form used by every gradebook export.
                terms.add(f"{parts[-1]}, {' '.join(parts[:-1])}")
            for part in parts:
                if len(part) >= 3:
                    terms.add(part)
                # `Okonkwo-Ramesh` is also written as either half alone.
                for piece in part.split("-"):
                    if len(piece) >= 3:
                        terms.add(piece)
        # Longest first so `Marisol Vandersteen` wins over `Marisol`, which
        # keeps one name one placeholder instead of two adjacent ones.
        return tuple(sorted(terms, key=lambda t: (-len(t), t)))

    @property
    def terms(self) -> tuple[str, ...]:
        """Match terms, longest first.  Still PII -- do not log this either."""
        return self._terms

    def __bool__(self) -> bool:
        return bool(self._terms)

    def __len__(self) -> int:
        """The number of NAMES supplied, not the number of expanded terms.

        A caller asking ``len(roster)`` wants "how many people", which is the
        number they can check against a class list; the term count is an
        implementation detail of :meth:`_expand`.
        """
        return self._name_count

    def __repr__(self) -> str:
        """Counts only.  The names are the thing this class exists to protect."""
        return f"Roster(<{self._name_count} names, {len(self._terms)} match terms, redacted>)"

    __str__ = __repr__


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


class DeidConfig(BaseModel):
    """Knobs for the two decisions that are genuinely material-dependent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    redact_bare_numeric_ids: bool = True
    """Redact unlabelled digit runs of :attr:`bare_numeric_id_lengths`.

    On by default because a gradebook export writes ids with no label at all,
    and missing those is the failure that matters.  Turn it off for material
    that is known to be numeric *data* -- a dataset of account numbers, a table
    of populations -- where the same rule destroys the content.
    """

    bare_numeric_id_lengths: tuple[int, int] = (8, 10)
    """Inclusive ``(min, max)`` digit count treated as a bare identifier.

    Eight is the floor because it is the shortest run that is implausible as a
    quantity in course prose and plausible as a CWID; ten is the ceiling because
    a longer run is a phone-with-country-code or a data value, and the phone
    detector already has the former.
    """

    extra_patterns: tuple[tuple[str, str], ...] = ()
    """``(kind_name, regex)`` pairs appended to the detector list.

    The escape hatch for an identifier scheme this file has never seen -- a
    non-US student number, a lab-notebook code.  ``kind_name`` must name a
    :class:`PiiKind` member.  Group 1, when the pattern has one, is what gets
    replaced; otherwise the whole match does.
    """


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------

# Ordered by priority: an earlier detector's span wins any overlap. Email before
# username so `a@b.edu` is one email rather than an address plus an `@b` handle;
# labelled detectors before bare ones so `Student ID: 12345678` is reported once,
# as a student id, with its label intact.

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_SSN = re.compile(r"(?<![0-9\-])\d{3}-\d{2}-\d{4}(?![0-9\-])")

_PHONE = re.compile(
    r"(?<![0-9A-Za-z])(?:\+?1[.\-\s]?)?"
    r"(?:\(\d{3}\)\s?|\d{3}[.\-\s])\d{3}[.\-\s]\d{4}"
    r"(?![0-9A-Za-z])"
)

_TIMESTAMP = (
    r"(?:\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"
    r"|\d{1,2}/\d{1,2}/\d{2,4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)"
    r"(?:\s?(?:[AaPp]\.?[Mm]\.?))?(?:\s?(?:Z|UTC|[A-Z]{2,4}T))?"
)

_SUBMISSION_TIMESTAMP = re.compile(
    r"(?i)\b(?:submitted|submission(?:\s+(?:time|date))?|turned\s+in"
    r"|last\s+modified|attempt\s+date|date\s+submitted)\b"
    rf"\s*(?:on|at)?\s*[:=]?\s*({_TIMESTAMP})"
)

_LABELLED_STUDENT_ID = re.compile(
    r"(?i)\b(?:cwid|banner\s*id|student\s*(?:id|number|no\.?|#)"
    r"|id\s*(?:number|#)|campus\s*id)\b\s*[:=#]?\s*([A-Za-z]{0,3}[\-0-9]{4,14})"
)

_LABELLED_USERNAME = re.compile(
    r"(?i)\b(?:netid|net\s*id|username|user\s*name|login|handle|screen\s*name)\b"
    r"\s*[:=]?\s*([A-Za-z][A-Za-z0-9._\-]{2,})"
)

_LABELLED_NAME = re.compile(
    r"(?i)\b(?:name|student|author|instructor|submitted\s+by|graded\s+by"
    r"|prepared\s+by|teaching\s+assistant)\b\s*[:=]\s*([^\n,;()]{2,60})"
)

_HONORIFIC_NAME = re.compile(
    r"\b(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss)\.?\s+([A-Z][a-z]+(?:[\-'][A-Z][a-z]+)*"
    r"(?:\s+[A-Z][a-z]+(?:[\-'][A-Z][a-z]+)*){0,2})"
)

_HANDLE = re.compile(r"(?<![A-Za-z0-9._%+\-])@([A-Za-z][A-Za-z0-9._\-]{2,})")


class _Span:
    """One detection: a category and where it sits.  **Never the value.**

    The absence of a ``value`` attribute is the design.  A span that carried
    what it matched would flow straight into :class:`DeidReport`, and a report
    is the artefact most likely to be logged or filed beside the row -- so a
    "helpful" value field re-publishes exactly what the redaction removed.
    ``TestReportCarriesNoPii`` pins this.
    """

    __slots__ = ("end", "kind", "start")

    def __init__(self, kind: PiiKind, start: int, end: int) -> None:
        self.kind = kind
        self.start = start
        self.end = end


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink ``[start, end)`` off surrounding whitespace.

    ``Student: Marisol Vandersteen \\n`` captures the trailing space; replacing
    it too would glue the placeholder to the newline and, worse, make the output
    depend on incidental spacing -- which shows up as a spurious diff every time
    the same material is re-ingested.
    """
    while end > start and text[end - 1].isspace():
        end -= 1
    while start < end and text[start].isspace():
        start += 1
    return start, end


def _detect(text: str, *, roster: Roster | None, config: DeidConfig) -> list[_Span]:
    """Every span to redact, in priority order, non-overlapping.

    Placeholders already present are collected FIRST and used as an exclusion
    mask -- that, and nothing else, is what makes a second pass a no-op.
    """
    protected = [m.span() for m in PLACEHOLDER_RE.finditer(text)]

    def blocked(start: int, end: int, taken: list[_Span]) -> bool:
        if any(start < p_end and p_start < end for p_start, p_end in protected):
            return True
        return any(start < s.end and s.start < end for s in taken)

    spans: list[_Span] = []

    def add(kind: PiiKind, start: int, end: int) -> None:
        start, end = _trimmed_span(text, start, end)
        if start >= end or blocked(start, end, spans):
            return
        spans.append(_Span(kind, start, end))

    # 1. Unambiguous by pattern alone.
    for match in _SSN.finditer(text):
        add(PiiKind.SSN, *match.span())
    for match in _EMAIL.finditer(text):
        add(PiiKind.EMAIL, *match.span())
    for match in _PHONE.finditer(text):
        add(PiiKind.PHONE, *match.span())

    # 2. Labelled fields -- the label survives, only the value goes.
    for match in _SUBMISSION_TIMESTAMP.finditer(text):
        add(PiiKind.SUBMISSION_TIMESTAMP, *match.span(1))
    for match in _LABELLED_STUDENT_ID.finditer(text):
        add(PiiKind.STUDENT_ID, *match.span(1))
    for match in _LABELLED_USERNAME.finditer(text):
        add(PiiKind.USERNAME, *match.span(1))
    for match in _LABELLED_NAME.finditer(text):
        add(PiiKind.NAME, *match.span(1))

    # 3. Names: exact when a roster exists, heuristic otherwise.
    if roster:
        for term in roster.terms:
            pattern = re.compile(
                rf"(?<![A-Za-z0-9_\-]){re.escape(term)}(?![A-Za-z0-9_\-])", re.IGNORECASE
            )
            for match in pattern.finditer(text):
                add(PiiKind.NAME, *match.span())
    for match in _HONORIFIC_NAME.finditer(text):
        add(PiiKind.NAME, *match.span(1))

    # 4. Bare, unlabelled identifiers -- last, so a labelled reading wins.
    if config.redact_bare_numeric_ids:
        low, high = config.bare_numeric_id_lengths
        bare = re.compile(rf"(?<![0-9A-Za-z._\-])\d{{{low},{high}}}(?![0-9A-Za-z._\-])")
        for match in bare.finditer(text):
            add(PiiKind.STUDENT_ID, *match.span())
    for match in _HANDLE.finditer(text):
        add(PiiKind.USERNAME, *match.span())

    # 5. Caller-supplied schemes this file has never seen.
    for kind_name, pattern_source in config.extra_patterns:
        kind = PiiKind[kind_name] if kind_name in PiiKind.__members__ else PiiKind(kind_name)
        pattern = re.compile(pattern_source)
        for match in pattern.finditer(text):
            span = match.span(1) if match.re.groups else match.span()
            add(kind, *span)

    return sorted(spans, key=lambda s: s.start)


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------

_CONTENT_RISK = (
    "content-based re-identification is not detectable by pattern matching: a "
    "short answer can identify its author through what it says (tasks/SCHEMA.md "
    "§ 1). A human must read cleaned material before it is published."
)

_NO_ROSTER_RISK = (
    "no roster was supplied, so personal names were found only where a label or "
    "an honorific marked them; names written mid-sentence remain."
)

_CONTAINER_RISK = (
    "only the text passed in was cleaned. Filenames, document metadata, "
    "embedded images and other sheets or pages were not seen by this pass."
)

_BARE_ID_RISK = (
    "bare digit runs were redacted without a label, so a numeric data value of "
    "the same length would also have been removed; check the cleaned text is "
    "still usable material."
)


class DeidReport(BaseModel):
    """What a cleaning pass did -- **counts and categories, never values**.

    This is the object that ends up in a log line, a database column and a
    ticket, so it is built to be safe there.  It answers "was anything removed,
    of what kinds, under which rules, and what does this pass still not
    guarantee" without answering "what was it".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ruleset_version: str = DEID_RULESET_VERSION
    counts: dict[str, int] = Field(default_factory=dict)
    """Non-zero redaction counts, keyed by :class:`PiiKind` value.

    Absent rather than zero: ``counts`` reads as a list of what was found, and a
    wall of zeroes buries the one category that fired.
    """

    roster_supplied: bool = False
    residual_risk: tuple[str, ...] = ()
    """Everything this pass did **not** guarantee, restated on every call.

    Not a constant a caller could read once and forget: it travels with the
    material, so whoever finds the report later also finds the caveats.  See
    this module's docstring for the full list.
    """

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def changed(self) -> bool:
        """True when the pass removed something."""
        return self.total > 0


class DeidResult(BaseModel):
    """Cleaned text plus the report describing how it got that way."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    report: DeidReport


def deidentify(
    text: str,
    *,
    roster: Roster | None = None,
    config: DeidConfig | None = None,
) -> DeidResult:
    """Redact personal identifiers from ``text``.

    One pass, deterministic, and idempotent by construction -- see this module's
    docstring for how, and for the honest list of what it does not catch.

    ``roster`` is optional but strongly recommended: it is the difference
    between exact name matching and label-driven guessing, and the report
    records which of the two happened.

    Returns a :class:`DeidResult`; the input string is never mutated and never
    stored.

    >>> deidentify("Email: a@b.example.edu\\n").text
    'Email: [REDACTED:EMAIL]\\n'
    >>> deidentify(deidentify("Email: a@b.example.edu\\n").text).report.changed
    False
    """
    config = config or DeidConfig()
    spans = _detect(text, roster=roster, config=config)

    out: list[str] = []
    cursor = 0
    counts: dict[str, int] = {}
    for span in spans:
        out.append(text[cursor : span.start])
        out.append(placeholder_for(span.kind))
        counts[span.kind.value] = counts.get(span.kind.value, 0) + 1
        cursor = span.end
    out.append(text[cursor:])

    risks = [_CONTENT_RISK, _CONTAINER_RISK]
    if not roster:
        risks.insert(0, _NO_ROSTER_RISK)
    if config.redact_bare_numeric_ids and counts.get(PiiKind.STUDENT_ID.value):
        risks.append(_BARE_ID_RISK)

    return DeidResult(
        text="".join(out),
        report=DeidReport(
            ruleset_version=DEID_RULESET_VERSION,
            counts=counts,
            roster_supplied=bool(roster),
            residual_risk=tuple(risks),
        ),
    )


def contains_detectable_pii(
    text: str,
    *,
    roster: Roster | None = None,
    config: DeidConfig | None = None,
) -> bool:
    """True when :func:`deidentify` would still remove something from ``text``.

    A tripwire, not a certificate.  ``False`` means "this pass finds nothing
    left", which is exactly as strong as the detector list above -- it is **not**
    a statement that the text is anonymous.  Use it to fail a check loudly, never
    to conclude that material is safe to publish.
    """
    return deidentify(text, roster=roster, config=config).report.changed
