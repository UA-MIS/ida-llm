"""The de-identification engine: what it removes, what it keeps, and idempotency.

Every fixture is synthetic -- see ``_synthetic_pii``'s module docstring.
"""

from __future__ import annotations

import pytest
from _synthetic_pii import (
    ALL_DOCUMENTS,
    ALREADY_CLEAN,
    FREE_TEXT_ANSWER,
    GRADEBOOK_ROW,
    MUST_NOT_SURVIVE,
    MUST_SURVIVE_IN_PROSE,
    NO_PII_STATISTICS_PROSE,
    PII_BEARING_DOCUMENTS,
    SSN_AND_PHONE,
    SUBMISSION_HEADER,
    SYNTHETIC_ROSTER,
)

from ida_core.deid import (
    DEID_RULESET_VERSION,
    PLACEHOLDER_RE,
    DeidConfig,
    PiiKind,
    Roster,
    contains_detectable_pii,
    deidentify,
    placeholder_for,
)


@pytest.fixture
def roster() -> Roster:
    return Roster(SYNTHETIC_ROSTER)


# --------------------------------------------------------------------------
# What must be removed
# --------------------------------------------------------------------------


class TestRedaction:
    @pytest.mark.parametrize("token", MUST_NOT_SURVIVE)
    def test_no_planted_identifier_survives(self, token: str, roster: Roster) -> None:
        """The whole point, stated as one assertion per planted identifier."""
        cleaned = "\n".join(deidentify(doc, roster=roster).text for doc in PII_BEARING_DOCUMENTS)
        assert token not in cleaned

    def test_emails_are_redacted(self, roster: Roster) -> None:
        result = deidentify(SUBMISSION_HEADER, roster=roster)
        assert placeholder_for(PiiKind.EMAIL) in result.text
        assert result.report.counts[PiiKind.EMAIL] == 1

    def test_labelled_student_id_keeps_its_label(self, roster: Roster) -> None:
        """The label survives; only the value goes.

        A reader of cleaned material needs to know a student id WAS there --
        that is what makes the redaction auditable rather than a silent hole.
        """
        result = deidentify(SUBMISSION_HEADER, roster=roster)
        assert "Student ID: " + placeholder_for(PiiKind.STUDENT_ID) in result.text

    def test_bare_numeric_ids_are_redacted(self, roster: Roster) -> None:
        result = deidentify(GRADEBOOK_ROW, roster=roster)
        assert result.report.counts[PiiKind.STUDENT_ID] == 2

    def test_bare_numeric_ids_can_be_switched_off(self, roster: Roster) -> None:
        config = DeidConfig(redact_bare_numeric_ids=False)
        result = deidentify(GRADEBOOK_ROW, roster=roster, config=config)
        assert "12345678" in result.text
        assert PiiKind.STUDENT_ID not in result.report.counts

    def test_ssn_and_phone(self) -> None:
        result = deidentify(SSN_AND_PHONE)
        assert result.report.counts[PiiKind.SSN] == 1
        assert result.report.counts[PiiKind.PHONE] == 1

    def test_submission_timestamp(self, roster: Roster) -> None:
        result = deidentify(SUBMISSION_HEADER, roster=roster)
        assert result.report.counts[PiiKind.SUBMISSION_TIMESTAMP] == 1
        assert "Submitted: " + placeholder_for(PiiKind.SUBMISSION_TIMESTAMP) in result.text

    def test_username_label_and_handle(self, roster: Roster) -> None:
        header = deidentify(SUBMISSION_HEADER, roster=roster)
        prose = deidentify(FREE_TEXT_ANSWER, roster=roster)
        assert header.report.counts[PiiKind.USERNAME] == 1  # NetID: mvander7
        assert prose.report.counts[PiiKind.USERNAME] == 1  # @marisol_v

    def test_honorific_name_without_a_roster(self) -> None:
        """``Dr. Achterberg`` goes even with no roster, and the honorific stays.

        Mid-sentence, with no label in front of it: the labelled-name detector
        cannot fire here, so this exercises the honorific path specifically.
        Keeping ``Dr.`` is deliberate -- the sentence still reads, and a reader
        can see that a person was named without learning who.
        """
        result = deidentify("The second marker was Dr. Achterberg, not the TA.\n")
        assert "Achterberg" not in result.text
        assert "Dr. " + placeholder_for(PiiKind.NAME) in result.text

    def test_a_labelled_field_takes_the_honorific_too(self) -> None:
        """``Graded by: Dr. Achterberg`` redacts the whole value, honorific included.

        The labelled-name detector wins the overlap, so the honorific goes with
        the name.  Over-redaction, and the right way round: a label already
        tells the reader what was removed, so nothing is lost by taking more.
        """
        result = deidentify("Graded by: Dr. Achterberg\n")
        assert result.text == "Graded by: " + placeholder_for(PiiKind.NAME) + "\n"

    def test_roster_catches_names_in_free_prose(self) -> None:
        """The roster is what makes mid-sentence names reliable.

        Without one, ``Marisol here.`` is indistinguishable from any other
        capitalised word -- which is precisely why the report warns.
        """
        without = deidentify(FREE_TEXT_ANSWER)
        with_roster = deidentify(FREE_TEXT_ANSWER, roster=Roster(SYNTHETIC_ROSTER))
        assert "Marisol here" in without.text
        assert "Marisol" not in with_roster.text

    def test_last_comma_first_form(self, roster: Roster) -> None:
        result = deidentify(GRADEBOOK_ROW, roster=roster)
        assert "Vandersteen" not in result.text
        assert "Marisol" not in result.text


# --------------------------------------------------------------------------
# What must be kept
# --------------------------------------------------------------------------


class TestPreservation:
    @pytest.mark.parametrize("token", MUST_SURVIVE_IN_PROSE)
    def test_statistics_prose_is_untouched(self, token: str, roster: Roster) -> None:
        result = deidentify(NO_PII_STATISTICS_PROSE, roster=roster)
        assert token in result.text

    def test_clean_prose_is_returned_byte_identical(self, roster: Roster) -> None:
        result = deidentify(NO_PII_STATISTICS_PROSE, roster=roster)
        assert result.text == NO_PII_STATISTICS_PROSE
        assert result.report.total == 0
        assert result.report.changed is False


# --------------------------------------------------------------------------
# Idempotency -- the property the story names
# --------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.parametrize("document", ALL_DOCUMENTS)
    def test_cleaning_twice_equals_cleaning_once(self, document: str, roster: Roster) -> None:
        once = deidentify(document, roster=roster).text
        twice = deidentify(once, roster=roster).text
        assert twice == once

    @pytest.mark.parametrize("document", ALL_DOCUMENTS)
    def test_second_pass_finds_nothing(self, document: str, roster: Roster) -> None:
        """Not just "stable" -- the second pass must report ZERO detections.

        Stability alone would be satisfied by a pass that redacts a placeholder
        into itself.  Zero detections is what proves the first pass finished.
        """
        once = deidentify(document, roster=roster)
        again = deidentify(once.text, roster=roster)
        assert again.report.total == 0
        assert again.report.changed is False

    def test_already_clean_input_is_a_no_op(self, roster: Roster) -> None:
        result = deidentify(ALREADY_CLEAN, roster=roster)
        assert result.text == ALREADY_CLEAN
        assert result.report.total == 0

    def test_placeholders_are_never_re_redacted(self, roster: Roster) -> None:
        """A placeholder is inert input, whatever label sits in front of it."""
        text = "Name: [REDACTED:NAME]\nCWID: [REDACTED:STUDENT_ID]\n"
        assert deidentify(text, roster=roster).text == text


# --------------------------------------------------------------------------
# The report must not re-publish what it removed
# --------------------------------------------------------------------------


class TestReportCarriesNoPii:
    @pytest.mark.parametrize("token", MUST_NOT_SURVIVE)
    def test_no_identifier_reaches_the_report(self, token: str, roster: Roster) -> None:
        """A report that names what it removed hands the PII back.

        Reports are the thing most likely to be logged, stored beside the row,
        or attached to a ticket -- so the report carries COUNTS and OFFSETS
        only, never values.
        """
        blob = "\n".join(
            deidentify(doc, roster=roster).report.model_dump_json() for doc in ALL_DOCUMENTS
        )
        assert token not in blob

    def test_report_records_the_ruleset_version(self, roster: Roster) -> None:
        """Cleaned-by-which-rules is part of the record, not folklore.

        When a detector improves, previously-cleaned rows were cleaned by the
        OLD ruleset; without this field there is no way to find them.
        """
        assert deidentify(SUBMISSION_HEADER, roster=roster).report.ruleset_version == (
            DEID_RULESET_VERSION
        )

    def test_report_warns_when_no_roster_was_supplied(self) -> None:
        report = deidentify(FREE_TEXT_ANSWER).report
        assert report.roster_supplied is False
        assert any("roster" in warning for warning in report.residual_risk)

    def test_report_always_warns_about_content_re_identification(self, roster: Roster) -> None:
        """The limit the policy itself names, restated at every call site.

        ``tasks/SCHEMA.md`` § 1: the de-identification standard is higher than
        deleting a name, because short-answer text is re-identifiable from its
        content.  No regex closes that gap, so the report says so every time.
        """
        report = deidentify(NO_PII_STATISTICS_PROSE, roster=roster).report
        assert any("re-identif" in warning for warning in report.residual_risk)


class TestRosterIsItselfPii:
    def test_roster_repr_does_not_leak_names(self) -> None:
        """A roster in a traceback or a log line is a roster disclosure."""
        roster = Roster(SYNTHETIC_ROSTER)
        assert "Vandersteen" not in repr(roster)
        assert "Vandersteen" not in str(roster)
        assert "3" in repr(roster)

    def test_empty_roster_is_allowed(self) -> None:
        assert deidentify(SUBMISSION_HEADER, roster=Roster([])).report.roster_supplied is False

    def test_short_name_parts_are_not_matched_alone(self) -> None:
        """``Bo`` alone would redact the word "bo" wherever it appeared.

        Two-character parts are matched only inside the full name, never on
        their own -- over-redaction is the safe direction, but not so far that
        it shreds ordinary prose.
        """
        roster = Roster(["Bo Achterberg"])
        result = deidentify("The bo staff is a martial arts weapon.\n", roster=roster)
        assert result.text == "The bo staff is a martial arts weapon.\n"


class TestPlaceholders:
    @pytest.mark.parametrize("kind", list(PiiKind))
    def test_every_placeholder_is_inert(self, kind: PiiKind) -> None:
        """Structural guarantee behind idempotency, checked per kind.

        If a new detector ever matched inside a placeholder, idempotency would
        break for that kind only -- and probably in a fixture nobody added.
        """
        placeholder = placeholder_for(kind)
        assert PLACEHOLDER_RE.fullmatch(placeholder)
        assert deidentify(placeholder).text == placeholder


class TestConfigurability:
    def test_bare_numeric_id_lengths_are_configurable(self) -> None:
        """The default window is a judgement call, so it has to be movable.

        An institution whose ids are six digits gets nothing from a rule that
        starts at eight -- and would be silently under-redacting, which is the
        failure direction that matters.
        """
        text = "Ref 123456 and 1234.\n"
        assert deidentify(text).text == text  # six digits: outside the default window
        widened = DeidConfig(bare_numeric_id_lengths=(6, 10))
        assert deidentify(text, config=widened).report.counts[PiiKind.STUDENT_ID] == 1

    def test_extra_patterns_add_a_scheme_this_file_never_saw(self) -> None:
        """The escape hatch, exercised -- an untested escape hatch is a closed door."""
        config = DeidConfig(
            extra_patterns=(("STUDENT_ID", r"\bLAB-([A-Z]{2}\d{4})\b"),),
        )
        result = deidentify("Notebook LAB-QX8842 belongs to the section.\n", config=config)
        assert "QX8842" not in result.text
        assert "LAB-" + placeholder_for(PiiKind.STUDENT_ID) in result.text

    def test_extra_patterns_without_a_group_replace_the_whole_match(self) -> None:
        config = DeidConfig(extra_patterns=(("USERNAME", r"\buser-[a-z]+\b"),))
        result = deidentify("Contact user-abc today.\n", config=config)
        assert result.text == "Contact " + placeholder_for(PiiKind.USERNAME) + " today.\n"

    def test_extra_patterns_stay_idempotent(self) -> None:
        """A caller-supplied detector must not break the property either.

        Placeholder protection is applied to every detector, including ones
        this file has never seen -- so extending the config cannot quietly cost
        idempotency.
        """
        config = DeidConfig(extra_patterns=(("STUDENT_ID", r"\bLAB-[A-Z]{2}\d{4}\b"),))
        once = deidentify("Notebook LAB-QX8842.\n", config=config).text
        assert deidentify(once, config=config).text == once


class TestContainsDetectablePii:
    def test_true_when_identifiers_remain(self, roster: Roster) -> None:
        assert contains_detectable_pii(SUBMISSION_HEADER, roster=roster) is True

    def test_false_on_cleaned_output(self, roster: Roster) -> None:
        cleaned = deidentify(SUBMISSION_HEADER, roster=roster).text
        assert contains_detectable_pii(cleaned, roster=roster) is False

    def test_false_on_prose_that_never_had_any(self) -> None:
        assert contains_detectable_pii(NO_PII_STATISTICS_PROSE) is False
