"""The intake gate: provenance, the cleaned/uncleaned flag, and the seam.

Every fixture is synthetic -- see ``_synthetic_pii``'s module docstring.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from _synthetic_pii import (
    FREE_TEXT_ANSWER,
    MUST_NOT_SURVIVE,
    NO_PII_STATISTICS_PROSE,
    SUBMISSION_HEADER,
    SYNTHETIC_ROSTER,
)

from ida_core.contracts import TaskSample
from ida_core.deid import Roster
from ida_core.intake import (
    INTAKE_PIPELINE_VERSION,
    CleanedMaterial,
    Cleanliness,
    IntakePipeline,
    RawMaterial,
    SourceProvenance,
    UncleanedMaterialError,
    require_cleaned,
)

REFERENCE = "MIS 200 Fall 2024, midterm item 12 (synthetic fixture)"


@pytest.fixture
def pipeline() -> IntakePipeline:
    return IntakePipeline(roster=Roster(SYNTHETIC_ROSTER))


@pytest.fixture
def cleaned(pipeline: IntakePipeline) -> CleanedMaterial:
    return pipeline.ingest_text(reference=REFERENCE, text=SUBMISSION_HEADER)


# --------------------------------------------------------------------------
# Provenance: a pointer, never the content
# --------------------------------------------------------------------------


class TestProvenance:
    def test_sha256_is_of_the_raw_source(self, cleaned: CleanedMaterial) -> None:
        expected = hashlib.sha256(SUBMISSION_HEADER.encode("utf-8")).hexdigest()
        assert cleaned.provenance.sha256 == expected

    def test_provenance_never_holds_the_raw_text(self, cleaned: CleanedMaterial) -> None:
        """The hash exists so the content does not have to.

        ``docs/sensitive-material.md`` § 4: name the source by reference and
        SHA-256, never by content.  Serialised provenance is the artefact that
        travels -- into sample metadata, into a DB column, into a ticket -- so
        the assertion is over its JSON, not over the object.
        """
        blob = cleaned.provenance.model_dump_json()
        for token in MUST_NOT_SURVIVE:
            assert token not in blob

    def test_reference_must_be_a_citation_not_a_blob(self) -> None:
        with pytest.raises(ValueError, match="one line"):
            SourceProvenance.of_text(reference="line one\nline two", text="x")
        with pytest.raises(ValueError, match="citation"):
            SourceProvenance.of_text(reference="x" * 400, text="x")

    def test_reference_must_not_be_empty(self) -> None:
        """Unattributable material is not provenanced material."""
        with pytest.raises(ValueError):
            SourceProvenance.of_text(reference="   ", text="x")

    def test_sha256_must_be_lowercase_hex(self) -> None:
        with pytest.raises(ValueError, match="sha256"):
            SourceProvenance(reference=REFERENCE, sha256="not-a-hash", byte_length=1)

    def test_byte_length_is_of_the_encoded_source(self) -> None:
        text = "café\n"  # 6 bytes in UTF-8, 5 characters
        provenance = SourceProvenance.of_text(reference=REFERENCE, text=text)
        assert provenance.byte_length == 6

    def test_retrieved_at_is_carried_when_supplied(self) -> None:
        when = datetime(2024, 10, 3, 14, 22, 11, tzinfo=UTC)
        provenance = SourceProvenance.of_text(reference=REFERENCE, text="x", retrieved_at=when)
        assert provenance.retrieved_at == when


# --------------------------------------------------------------------------
# The gate: not cleaned -> not usable
# --------------------------------------------------------------------------


class TestTheGate:
    def test_cleaned_material_passes(self, cleaned: CleanedMaterial) -> None:
        assert require_cleaned(cleaned, purpose="model call") is cleaned

    def test_raw_material_is_refused(self) -> None:
        raw = RawMaterial(reference=REFERENCE, text=SUBMISSION_HEADER)
        with pytest.raises(UncleanedMaterialError) as excinfo:
            require_cleaned(raw, purpose="model call")
        assert "model call" in str(excinfo.value)

    @pytest.mark.parametrize("candidate", ["a bare string", None, 42, {"text": "x"}])
    def test_anything_that_did_not_come_through_the_pipeline_is_refused(
        self, candidate: object
    ) -> None:
        """A ``str`` is the dangerous case, not an exotic one.

        The natural mistake is to pass task text straight through -- so the
        gate refuses ``str`` explicitly rather than duck-typing on ``.text``.
        """
        with pytest.raises(UncleanedMaterialError):
            require_cleaned(candidate, purpose="task content")

    def test_the_error_names_the_policy(self) -> None:
        with pytest.raises(UncleanedMaterialError, match="sensitive-material"):
            require_cleaned("uncleaned", purpose="task content")

    def test_cleanliness_flags(self, cleaned: CleanedMaterial) -> None:
        raw = RawMaterial(reference=REFERENCE, text=SUBMISSION_HEADER)
        assert raw.cleanliness is Cleanliness.NOT_CLEANED
        assert cleaned.cleanliness is Cleanliness.CLEANED

    def test_raw_material_repr_does_not_leak_its_content(self) -> None:
        """Uncleaned material must not reach a log through a stack trace.

        ``RawMaterial`` exists to be held for the few milliseconds before
        cleaning; a pydantic default repr would print the whole education
        record into any exception that carried it.
        """
        raw = RawMaterial(reference=REFERENCE, text=SUBMISSION_HEADER)
        for token in MUST_NOT_SURVIVE:
            assert token not in repr(raw)
            assert token not in str(raw)
        assert "redacted" in repr(raw)

    def test_raw_material_exposes_provenance_before_cleaning(self) -> None:
        """The hash is computable without cleaning -- provenance is not the gate."""
        raw = RawMaterial(reference=REFERENCE, text=SUBMISSION_HEADER)
        assert raw.provenance.sha256 == (
            hashlib.sha256(SUBMISSION_HEADER.encode("utf-8")).hexdigest()
        )


# --------------------------------------------------------------------------
# Idempotency at the material level
# --------------------------------------------------------------------------


class TestIdempotency:
    def test_ingesting_cleaned_material_returns_it_unchanged(
        self, pipeline: IntakePipeline, cleaned: CleanedMaterial
    ) -> None:
        assert pipeline.ingest(cleaned) is cleaned

    def test_re_ingesting_preserves_the_original_source_hash(
        self, pipeline: IntakePipeline, cleaned: CleanedMaterial
    ) -> None:
        """Provenance points at the RAW source, and re-cleaning must not move it.

        If a second pass re-stamped provenance with the hash of the cleaned
        text, the pointer would stop resolving to the item it came from -- and
        the pointer is the entire reason the content can stay out.
        """
        again = pipeline.ingest(cleaned)
        assert again.provenance == cleaned.provenance

    def test_cleaning_already_clean_text_records_nothing_removed(
        self, pipeline: IntakePipeline
    ) -> None:
        material = pipeline.ingest_text(reference=REFERENCE, text=NO_PII_STATISTICS_PROSE)
        assert material.text == NO_PII_STATISTICS_PROSE
        assert material.report.total == 0

    def test_stronger_rules_may_still_clean_already_cleaned_material(self) -> None:
        """Re-ingestion is a no-op only when there is genuinely nothing left.

        The realistic case, not a contrived one: material cleaned before the
        roster was available keeps its mid-sentence names, because without a
        roster a name is just a capitalised word.  Re-ingesting it through a
        pipeline that HAS the roster must find them.

        So "already cleaned" must not mean "exempt from a better detector" --
        the rows most in need of re-cleaning are exactly the ones already
        marked clean.  Provenance still points at the raw source.
        """
        rosterless = IntakePipeline()
        first = rosterless.ingest_text(reference=REFERENCE, text=FREE_TEXT_ANSWER)
        assert "Marisol here" in first.text  # the roster is what would catch this

        with_roster = IntakePipeline(roster=Roster(SYNTHETIC_ROSTER))
        again = with_roster.ingest(first)

        assert again is not first
        assert "Marisol" not in again.text
        assert again.provenance == first.provenance
        assert again.report.roster_supplied is True


# --------------------------------------------------------------------------
# The integration seam
# --------------------------------------------------------------------------


class TestTaskContentSeam:
    def test_to_task_sample_produces_a_valid_sample(self, cleaned: CleanedMaterial) -> None:
        sample = cleaned.to_task_sample("item-12")
        assert isinstance(sample, TaskSample)
        assert sample.id == "item-12"
        assert sample.input == cleaned.text

    def test_the_sample_carries_the_provenance_pointer(self, cleaned: CleanedMaterial) -> None:
        """§ 4 of the policy, mechanised: reference + SHA-256 in ``metadata``."""
        sample = cleaned.to_task_sample("item-12")
        assert sample.metadata["provenance"] == "de-identified"
        assert sample.metadata["source_ref"] == REFERENCE
        assert sample.metadata["source_sha256"] == cleaned.provenance.sha256

    def test_the_sample_body_carries_no_pii(self, cleaned: CleanedMaterial) -> None:
        sample = cleaned.to_task_sample("item-12")
        blob = sample.model_dump_json()
        for token in MUST_NOT_SURVIVE:
            assert token not in blob

    def test_caller_metadata_cannot_overwrite_provenance(self, cleaned: CleanedMaterial) -> None:
        """Provenance is the record, not a default the caller may edit.

        Silently accepting ``{"source_sha256": ...}`` would let a caller point
        a sample at a source it did not come from -- a forged pointer is worse
        than no pointer, because it reads as verified.
        """
        with pytest.raises(ValueError, match="source_sha256"):
            cleaned.to_task_sample("item-12", metadata={"source_sha256": "0" * 64})

    def test_caller_metadata_is_otherwise_merged(self, cleaned: CleanedMaterial) -> None:
        sample = cleaned.to_task_sample("item-12", metadata={"skill": "weighted-mean"})
        assert sample.metadata["skill"] == "weighted-mean"
        assert sample.metadata["source_ref"] == REFERENCE

    def test_provenance_sentence_is_one_line_and_hash_bearing(
        self, cleaned: CleanedMaterial
    ) -> None:
        sentence = cleaned.provenance_sentence()
        assert "\n" not in sentence
        assert cleaned.provenance.sha256 in sentence


class TestPipelineRecord:
    def test_pipeline_version_is_recorded(self, cleaned: CleanedMaterial) -> None:
        assert cleaned.pipeline_version == INTAKE_PIPELINE_VERSION

    def test_cleaned_sha256_is_of_the_cleaned_text(self, cleaned: CleanedMaterial) -> None:
        """Two rows cleaned from different sources to the same text are equal.

        The cleaned hash is the dedup and cache key; the source hash is the
        provenance pointer.  They answer different questions and both are kept.
        """
        assert cleaned.cleaned_sha256 == hashlib.sha256(cleaned.text.encode("utf-8")).hexdigest()
        assert cleaned.cleaned_sha256 != cleaned.provenance.sha256

    def test_cleaned_material_is_immutable(self, cleaned: CleanedMaterial) -> None:
        with pytest.raises(ValueError):
            cleaned.text = "anything"  # type: ignore[misc]

    def test_report_travels_with_the_material(self, cleaned: CleanedMaterial) -> None:
        assert cleaned.report.total > 0
        assert cleaned.report.roster_supplied is True

    def test_ingest_rejects_a_bare_string(self, pipeline: IntakePipeline) -> None:
        """``ingest`` takes material; ``ingest_text`` is the entry point for text.

        Two names because the difference matters: text arriving with no
        reference has no provenance, and provenance is not optional.
        """
        with pytest.raises(TypeError):
            pipeline.ingest(SUBMISSION_HEADER)  # type: ignore[arg-type]
