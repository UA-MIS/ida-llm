"""The curriculum map, and the tag rule that keeps SLO results attributable.

The tests that matter here are the NEGATIVE ones. Loading a well-formed file is
easy to get right; what this module exists to guarantee is that a task claiming
an outcome that does not exist, or contradicting itself between its tags and
its sample metadata, is REJECTED -- because neither mistake produces any other
symptom. A run with a mistyped `slo:` tag succeeds, scores, and files its
result under a heading nothing can look up.
"""

from __future__ import annotations

import pytest
import yaml

from ida_core.config import repo_root
from ida_core.contracts import TaskSpec
from ida_core.curriculum import (
    ASSESSMENT_LEVELS,
    BENCHMARK_TAG,
    CoverageLevel,
    CurriculumMap,
    check_task_tags,
    default_curriculum_path,
    load_curriculum,
    slo_of,
    use_mode_of,
)
from ida_core.validation import ValidationError


@pytest.fixture(scope="module")
def curriculum() -> CurriculumMap:
    return load_curriculum(default_curriculum_path(repo_root()))


def _task(**overrides) -> TaskSpec:
    """A minimal valid verifiable task, with SLO tagging applied by default."""
    document = {
        "version": 1,
        "id": "t/one",
        "title": "One",
        "kind": "verifiable",
        "scorer": {"kind": "exact_match"},
        "tags": [BENCHMARK_TAG, "slo:SLO2", "use-mode:capability"],
        "samples": [
            {
                "id": "s1",
                "input": "q",
                "target": "a",
                "metadata": {"slo": "SLO2", "use_mode": "capability"},
            }
        ],
    }
    document.update(overrides)
    return TaskSpec.model_validate(document)


class TestTheShippedCurriculum:
    """The real file, not a fixture. It is the thing every task tags against."""

    def test_it_loads(self, curriculum: CurriculumMap) -> None:
        assert curriculum.version == 1
        assert len(curriculum.outcomes) == 9
        assert curriculum.outcome_ids() == [f"SLO{n}" for n in range(1, 10)]

    def test_teamwork_and_oral_communication_are_marked_unbenchmarkable(
        self, curriculum: CurriculumMap
    ) -> None:
        """The two outcomes a single-turn text benchmark cannot reach.

        Pinned as a test rather than left to the file because it is the claim a
        reader is most entitled to check: this benchmark covers seven of nine
        outcomes, and the two it omits are omitted on the record.
        """
        assert curriculum.text_benchmarkable_ids() == [
            "SLO1",
            "SLO2",
            "SLO3",
            "SLO4",
            "SLO6",
            "SLO7",
            "SLO9",
        ]
        for outcome_id in ("SLO5", "SLO8"):
            outcome = curriculum.get(outcome_id)
            assert outcome.text_benchmarkable is False
            assert outcome.benchmark_note.strip(), "an omission must carry its reason"

    def test_mis_200_carries_the_trio_the_first_live_run_targets(
        self, curriculum: CurriculumMap
    ) -> None:
        """MIS 200 is the target course, and these three levels drive the plan.

        SLO2 at `A` is why the quantitative family is the deepest one authored.
        """
        assert curriculum.outcomes_for_course("MIS 200") == {
            "SLO1": CoverageLevel.REINFORCED,
            "SLO2": CoverageLevel.ASSESSMENT_POINT,
            "SLO9": CoverageLevel.INTRODUCED,
        }
        assert curriculum.is_assessment_point("MIS 200", "SLO2")
        assert not curriculum.is_assessment_point("MIS 200", "SLO1")

    def test_every_benchmarkable_outcome_is_taught_somewhere(
        self, curriculum: CurriculumMap
    ) -> None:
        for outcome_id in curriculum.text_benchmarkable_ids():
            assert curriculum.courses_for_outcome(outcome_id), (
                f"{outcome_id} is benchmarkable but no course covers it"
            )

    def test_capstone_is_the_assessment_point_for_most_outcomes(
        self, curriculum: CurriculumMap
    ) -> None:
        levels = curriculum.outcomes_for_course("GBA 490")
        assert set(levels) == {"SLO1", "SLO3", "SLO5", "SLO6", "SLO7", "SLO9"}
        assert all(level in ASSESSMENT_LEVELS for level in levels.values())

    def test_only_capability_is_in_use(self, curriculum: CurriculumMap) -> None:
        assert curriculum.in_use_mode_ids() == ["capability"]
        assert set(curriculum.use_mode_ids()) == {"capability", "assistive", "instructional"}

    def test_unknown_outcome_and_course_lookups_raise(self, curriculum: CurriculumMap) -> None:
        """`courses_for_outcome` must not answer an empty mapping for a typo.

        "No course covers SLO4" and "you misspelled SLO4" are different answers
        and only one of them is ever true.
        """
        with pytest.raises(KeyError, match="SLO99"):
            curriculum.get("SLO99")
        with pytest.raises(KeyError, match="SL02"):
            curriculum.courses_for_outcome("SL02")
        with pytest.raises(KeyError, match="MIS 999"):
            curriculum.course("MIS 999")


class TestLoaderRejections:
    def _write(self, tmp_path, mutate):
        document = yaml.safe_load(default_curriculum_path(repo_root()).read_text())
        mutate(document)
        path = tmp_path / "slo.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=False))
        return path

    def test_missing_file(self, tmp_path) -> None:
        with pytest.raises(ValidationError, match="not found"):
            load_curriculum(tmp_path / "nope.yaml")

    def test_unparseable_yaml(self, tmp_path) -> None:
        path = tmp_path / "slo.yaml"
        path.write_text("outcomes: [unclosed\n")
        with pytest.raises(ValidationError, match="could not parse YAML"):
            load_curriculum(path)

    def test_non_mapping_top_level(self, tmp_path) -> None:
        path = tmp_path / "slo.yaml"
        path.write_text("- a\n- b\n")
        with pytest.raises(ValidationError, match="must be a mapping"):
            load_curriculum(path)

    def test_yaml_is_loaded_safely(self, tmp_path) -> None:
        path = tmp_path / "slo.yaml"
        path.write_text("!!python/object/apply:os.system ['echo pwned']\n")
        with pytest.raises(ValidationError):
            load_curriculum(path)

    def test_coverage_cell_naming_an_undeclared_outcome_is_rejected(self, tmp_path) -> None:
        """The pydantic layer's job: a rule the JSON Schema cannot express."""

        def mutate(document):
            document["coverage"][0]["outcomes"]["SLO7"] = "R"
            document["outcomes"] = [o for o in document["outcomes"] if o["id"] != "SLO7"]

        with pytest.raises(ValidationError, match="undeclared outcome"):
            load_curriculum(self._write(tmp_path, mutate))

    def test_duplicate_outcome_ids_are_rejected(self, tmp_path) -> None:
        def mutate(document):
            document["outcomes"].append(dict(document["outcomes"][0]))

        with pytest.raises(ValidationError, match="duplicate outcome ids"):
            load_curriculum(self._write(tmp_path, mutate))

    def test_a_map_with_no_usable_mode_is_rejected(self, tmp_path) -> None:
        def mutate(document):
            for mode in document["use_modes"]:
                mode["in_use"] = False

        with pytest.raises(ValidationError, match="no use mode"):
            load_curriculum(self._write(tmp_path, mutate))

    def test_an_unknown_coverage_level_is_rejected(self, tmp_path) -> None:
        def mutate(document):
            document["coverage"][0]["outcomes"]["SLO4"] = "probably"

        with pytest.raises(ValidationError):
            load_curriculum(self._write(tmp_path, mutate))

    def test_a_lowercase_outcome_id_is_rejected(self, tmp_path) -> None:
        """The tag spelling is exact, so the declaration's spelling must be too."""

        def mutate(document):
            document["outcomes"][0]["id"] = "slo1"

        with pytest.raises(ValidationError):
            load_curriculum(self._write(tmp_path, mutate))


class TestTagParsing:
    def test_reads_a_single_value(self) -> None:
        tags = [BENCHMARK_TAG, "slo:SLO2", "use-mode:capability", "ladder-l1"]
        assert slo_of(tags) == "SLO2"
        assert use_mode_of(tags) == "capability"

    def test_absent_is_none(self) -> None:
        assert slo_of(["ladder-l1"]) is None
        assert use_mode_of(["ladder-l1"]) is None

    def test_ambiguous_is_none_not_first_wins(self) -> None:
        """Two outcome tags is not a task measuring two outcomes."""
        assert slo_of(["slo:SLO1", "slo:SLO2"]) is None

    def test_a_prefix_only_matches_at_the_start(self) -> None:
        assert slo_of(["not-slo:SLO2"]) is None


class TestCheckTaskTags:
    def test_a_correctly_tagged_task_is_clean(self, curriculum: CurriculumMap) -> None:
        assert check_task_tags(_task(), curriculum) == []

    def test_an_untagged_task_is_not_this_benchmarks_business(
        self, curriculum: CurriculumMap
    ) -> None:
        """The demo and exemplar families predate SLO tagging and must stay valid."""
        spec = _task(
            tags=["exemplar", "ladder-l1"], samples=[{"id": "s1", "input": "q", "target": "a"}]
        )
        assert check_task_tags(spec, curriculum) == []

    def test_a_misspelled_outcome_is_rejected(self, curriculum: CurriculumMap) -> None:
        """THE test this module exists for. `SL02` is a zero, not an O."""
        spec = _task(
            tags=[BENCHMARK_TAG, "slo:SL02", "use-mode:capability"],
            samples=[
                {
                    "id": "s1",
                    "input": "q",
                    "target": "a",
                    "metadata": {"slo": "SL02", "use_mode": "capability"},
                }
            ],
        )
        problems = check_task_tags(spec, curriculum)
        assert any("names no outcome" in p for p in problems)

    def test_an_unbenchmarkable_outcome_is_rejected(self, curriculum: CurriculumMap) -> None:
        """SLO5 is Teamwork. A single-turn transcript is not teamwork."""
        spec = _task(
            tags=[BENCHMARK_TAG, "slo:SLO5", "use-mode:capability"],
            samples=[
                {
                    "id": "s1",
                    "input": "q",
                    "target": "a",
                    "metadata": {"slo": "SLO5", "use_mode": "capability"},
                }
            ],
        )
        problems = check_task_tags(spec, curriculum)
        assert any("text_benchmarkable: false" in p for p in problems)

    def test_a_mode_that_is_declared_but_not_in_use_is_rejected(
        self, curriculum: CurriculumMap
    ) -> None:
        spec = _task(
            tags=[BENCHMARK_TAG, "slo:SLO2", "use-mode:assistive"],
            samples=[
                {
                    "id": "s1",
                    "input": "q",
                    "target": "a",
                    "metadata": {"slo": "SLO2", "use_mode": "assistive"},
                }
            ],
        )
        problems = check_task_tags(spec, curriculum)
        assert any("not a use mode that is in use" in p for p in problems)

    def test_two_outcome_tags_are_rejected(self, curriculum: CurriculumMap) -> None:
        spec = _task(tags=[BENCHMARK_TAG, "slo:SLO1", "slo:SLO2", "use-mode:capability"])
        problems = check_task_tags(spec, curriculum)
        assert any("exactly one is required" in p for p in problems)

    def test_missing_benchmark_tag_is_rejected(self, curriculum: CurriculumMap) -> None:
        spec = _task(tags=["slo:SLO2", "use-mode:capability"])
        problems = check_task_tags(spec, curriculum)
        assert any(BENCHMARK_TAG in p and "does not carry" in p for p in problems)

    def test_benchmark_tag_without_an_outcome_is_rejected(self, curriculum: CurriculumMap) -> None:
        spec = _task(tags=[BENCHMARK_TAG])
        problems = check_task_tags(spec, curriculum)
        assert any("carries no 'slo:' tag" in p for p in problems)
        assert any("carries no 'use-mode:' tag" in p for p in problems)

    def test_sample_metadata_must_repeat_the_tags(self, curriculum: CurriculumMap) -> None:
        spec = _task(samples=[{"id": "s1", "input": "q", "target": "a", "metadata": {}}])
        problems = check_task_tags(spec, curriculum)
        assert any("missing 'slo'" in p for p in problems)
        assert any("missing 'use_mode'" in p for p in problems)

    def test_sample_metadata_contradicting_the_tags_is_rejected(
        self, curriculum: CurriculumMap
    ) -> None:
        """The two spellings serve two consumers; a disagreement means one lies."""
        spec = _task(
            samples=[
                {
                    "id": "s1",
                    "input": "q",
                    "target": "a",
                    "metadata": {"slo": "SLO9", "use_mode": "capability"},
                }
            ]
        )
        problems = check_task_tags(spec, curriculum)
        assert any("contradicts the task tag" in p for p in problems)

    def test_every_problem_is_reported_not_just_the_first(self, curriculum: CurriculumMap) -> None:
        """An author fixing tags should get the whole list in one pass."""
        spec = _task(
            tags=["slo:SLO5", "use-mode:assistive"],
            samples=[{"id": "s1", "input": "q", "target": "a", "metadata": {}}],
        )
        assert len(check_task_tags(spec, curriculum)) >= 4
