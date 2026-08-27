"""Fabricated PII-laden fixtures for the de-identification tests.

**EVERY STRING IN THIS FILE WAS INVENTED FOR THIS FILE.**  No real student, no
real roster, no real submission, no real course export.  That is not a courtesy
note -- it is the condition under which a de-identification test suite is
allowed to exist at all: a test corpus for a FERPA control cannot itself be an
education record, and the only way to guarantee that is to write the corpus by
hand.  Same reasoning, and the same standard, as ``tasks/SCHEMA.md``
§ "No real student work".

Three deliberate choices keep it unmistakably synthetic:

* names are implausible-in-combination inventions, not common-name pairs that
  might collide with a real person on the roster;
* every email domain is under ``example.edu`` -- reserved by RFC 2606 and
  therefore incapable of resolving to a real mailbox;
* the identifiers are sequential nonsense (``12345678``), not plausible CWIDs.

If you add a fixture, hold that line.  A "realistic" fixture pulled from a real
export is the exact failure this module exists to prevent.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Roster
# --------------------------------------------------------------------------

SYNTHETIC_ROSTER = [
    "Marisol Vandersteen",
    "Bo Achterberg",
    "Jian-Wei Okonkwo-Ramesh",
]
"""Invented names.  A roster is itself PII -- a real one never enters this repo."""


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

SUBMISSION_HEADER = """\
Student: Marisol Vandersteen
Student ID: 12345678
Email: mvandersteen@crimson.example.edu
NetID: mvander7
Submitted: 2024-10-03 14:22:11
Graded by: Dr. Achterberg
"""
"""The shape of an LMS submission header: every field is a labelled identifier."""

FREE_TEXT_ANSWER = """\
Marisol here. I worked on this with Bo Achterberg and Jian-Wei Okonkwo-Ramesh.
If the numbers look wrong please reach me at 205-555-0142 or @marisol_v on the
class Discord, or mvandersteen@crimson.example.edu.

My answer: the sample mean is 74.5 and the standard deviation is 12.25, so a
95% interval is roughly 74.5 +/- 2.02.
"""
"""Free prose: names and contact details appear mid-sentence, not in fields."""

GRADEBOOK_ROW = """\
Vandersteen, Marisol,12345678,mvandersteen@crimson.example.edu,88
Achterberg, Bo,87654321,bachterberg@crimson.example.edu,91
"""
"""A CSV-ish export -- the "Last, First" name form plus bare numeric ids."""

SSN_AND_PHONE = """\
Emergency contact on file: 205-555-0199. SSN 123-45-6789 (do not store this).
"""
"""Identifiers that are unambiguous by pattern alone."""

NO_PII_STATISTICS_PROSE = """\
For the 2024 cohort we observed n = 42 complete responses. The mean was
3.14159, the median 3.0, and the variance 12345678.90. A chi-square of 18.31 on
10 degrees of freedom gives p = 0.0325, so we reject at alpha = 0.05.

Section 004 met on Tuesdays. The rubric allocates 25 points to method and 15 to
interpretation.
"""
"""Course prose with NO personal identifier in it.

Load-bearing as a NEGATIVE fixture: it is full of the numbers a statistics
course is made of -- a year, a count, decimals, a section number, point
allocations, and an eight-digit-plus-decimal variance -- and a de-identifier
that mangles any of them has destroyed the material it was supposed to save.
"""

ALREADY_CLEAN = """\
Student: [REDACTED:NAME]
Student ID: [REDACTED:STUDENT_ID]
Email: [REDACTED:EMAIL]

The candidate argued that [REDACTED:NAME] should have used a paired test.
"""
"""Output-shaped input: what a second pass over cleaned text must not touch."""


PII_BEARING_DOCUMENTS = [
    SUBMISSION_HEADER,
    FREE_TEXT_ANSWER,
    GRADEBOOK_ROW,
    SSN_AND_PHONE,
]
"""The fixtures with identifiers planted in them.

Split out from :data:`ALL_DOCUMENTS` for the "must not survive" assertion, and
the reason is a real ambiguity rather than bookkeeping: the negative fixture
contains ``12345678.90``, a variance, whose first eight characters are also the
planted student id.  Asserting the *substring* ``12345678`` is absent from the
whole corpus would demand that a decimal be mangled -- exactly the destruction
:data:`MUST_SURVIVE_IN_PROSE` exists to forbid.  So the two properties are
asserted over the two corpora they actually apply to.
"""

ALL_DOCUMENTS = [
    *PII_BEARING_DOCUMENTS,
    NO_PII_STATISTICS_PROSE,
    ALREADY_CLEAN,
]
"""Every fixture, for the properties that must hold over all of them."""


# --------------------------------------------------------------------------
# The strings that must never survive cleaning
# --------------------------------------------------------------------------

MUST_NOT_SURVIVE = [
    "Marisol",
    "Vandersteen",
    "Achterberg",
    "Okonkwo-Ramesh",
    "12345678",
    "87654321",
    "mvandersteen@crimson.example.edu",
    "bachterberg@crimson.example.edu",
    "mvander7",
    "205-555-0142",
    "205-555-0199",
    "123-45-6789",
    "marisol_v",
    "2024-10-03 14:22:11",
]
"""Every identifier token planted in the fixtures above.

The suite asserts none of these appears in cleaned output, and -- separately --
that none appears in a :class:`~ida_core.deid.DeidReport`.  The second check is
the one people forget: a report that names what it removed re-publishes it.
"""

MUST_SURVIVE_IN_PROSE = [
    "2024",
    "42",
    "3.14159",
    "12345678.90",
    "0.0325",
    "Section 004",
    "25 points",
]
"""Values in :data:`NO_PII_STATISTICS_PROSE` that cleaning must leave alone."""
