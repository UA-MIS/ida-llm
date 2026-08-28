"""The SLO 6 and SLO 7 task families, held to the rules that make them useful.

These two families are the benchmark's coverage of two BScBA core Student
Learning Outcomes: SLO 6 (ethical reasoning) and SLO 7 (written communication).
Both are subjective, rubric-scored through the LLM judge, and both are authored
content rather than code -- which is exactly why they need tests. A task family
degrades silently: a folded block scalar instead of a literal one, an anchor
quietly replaced by an adjective, a rubric id edited in place, and nothing
fails, but every grade produced afterwards is noisier than the one before and
no longer comparable with the ones already stored.

Scope note. Every assertion here is deliberately scoped to the ``slo-6-`` and
``slo-7-`` id prefixes rather than to ``slo-`` generally. Other SLO families are
being authored in parallel by other people; a test in this file that policed
*their* conventions would fail on their branches, for a rule they never agreed
to. If these conventions are later adopted family-wide, widening the prefix is
a one-line change and should be made deliberately.

Nothing here reaches a network. The end-to-end grading test drives the
in-process mock-model service through ``httpx.MockTransport``, exactly as
``test_judge.py`` does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ida_core.contracts import ScorerKind, TaskKind
from ida_harness.judge import LLMJudge, aggregate, build_criterion_messages
from ida_harness.tasks import TaskCatalog

TASKS_DIR = Path(__file__).resolve().parents[3] / "tasks"

SLO6_PREFIX = "slo-6-ethical-reasoning/"
SLO7_PREFIX = "slo-7-written-communication/"

#: The tag a dashboard groups on, per family. Colon-delimited tag strings rather
#: than top-level YAML keys, because ``task.schema.json`` sets
#: ``additionalProperties: false`` and ``tags`` is the only free-form field the
#: schema exposes -- see the PR description. If the schema later grows real
#: ``slo``/``use_mode`` fields, this mapping is what has to move.
SLO_TAG = {SLO6_PREFIX: "slo:SLO6", SLO7_PREFIX: "slo:SLO7"}

#: Every task in both families is a capability probe, not a use-mode simulation.
USE_MODE_TAG = "use_mode:capability"

RUNGS = ("l1", "l2", "l3", "l4", "l5")

#: Sample ``metadata`` is published UNAUTHENTICATED by ``GET /tasks/{id}``
#: (tasks/SCHEMA.md, "Dataset hygiene"). Only keys that are safe to publish and
#: useful to a consumer belong there; author's notes and expected verdicts live
#: in YAML comments. Pinning the allowed key set is what stops a future edit
#: from parking an expected answer in a published field.
PUBLISHABLE_METADATA_KEYS = {"probe", "genre", "provenance"}

ANCHOR_LINE = re.compile(r"^\s*(1\.0|0\.5|0\.0) --", re.MULTILINE)


@pytest.fixture(scope="module")
def catalog() -> TaskCatalog:
    return TaskCatalog.from_directory(TASKS_DIR)


def _family(catalog: TaskCatalog, prefix: str) -> list:
    return sorted((t for t in catalog.all() if t.id.startswith(prefix)), key=lambda t: t.id)


@pytest.fixture(scope="module")
def slo_tasks(catalog: TaskCatalog) -> list:
    return _family(catalog, SLO6_PREFIX) + _family(catalog, SLO7_PREFIX)


def _prefix_of(task) -> str:
    return SLO6_PREFIX if task.id.startswith(SLO6_PREFIX) else SLO7_PREFIX


class TestBothFamiliesArePresent:
    """Guards the guard. Every test below iterates over a list; if the families
    were renamed or moved, those loops would pass over nothing and this file
    would go green while asserting about no tasks at all."""

    def test_each_family_has_five_rungs(self, catalog: TaskCatalog) -> None:
        for prefix in (SLO6_PREFIX, SLO7_PREFIX):
            tasks = _family(catalog, prefix)
            assert len(tasks) == 5, f"{prefix}: expected a five-rung ladder"

    def test_the_rungs_are_numbered_l1_to_l5(self, catalog: TaskCatalog) -> None:
        for prefix in (SLO6_PREFIX, SLO7_PREFIX):
            leaves = [t.id.removeprefix(prefix) for t in _family(catalog, prefix)]
            assert [leaf.split("-")[0] for leaf in leaves] == list(RUNGS), (
                f"{prefix}: rungs are not l1..l5 exactly once each"
            )

    def test_there_is_a_file_named_for_every_task_id(self, catalog: TaskCatalog) -> None:
        """SCHEMA.md: the filename matches the part of the id after the prefix.
        Nothing enforces it, and a reviewer chasing a result row needs it."""
        for prefix in (SLO6_PREFIX, SLO7_PREFIX):
            directory = TASKS_DIR / prefix.rstrip("/")
            assert directory.is_dir(), f"{directory} is missing"
            for task in _family(catalog, prefix):
                expected = directory / f"{task.id.removeprefix(prefix)}.yaml"
                assert expected.exists(), f"{task.id}: expected to be authored in {expected.name}"

    def test_the_families_carry_the_expected_volume(self, slo_tasks: list) -> None:
        assert len(slo_tasks) == 10
        assert sum(len(t.rubric.criteria) for t in slo_tasks) >= 38
        assert sum(len(t.samples) for t in slo_tasks) >= 40


class TestTheSubjectiveContract:
    def test_every_task_is_subjective_and_judge_scored(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert task.kind is TaskKind.SUBJECTIVE, f"{task.id}: a family shares one kind"
            assert task.scorer.kind is ScorerKind.LLM_JUDGE, f"{task.id}"

    def test_the_scorer_points_at_the_rubric_it_ships_with(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert task.scorer.rubric_id == task.rubric.id, f"{task.id}: rubric_id mismatch"

    def test_no_sample_carries_a_target(self, slo_tasks: list) -> None:
        """A gold answer on a subjective sample is a category error: there is
        nothing for a programmatic scorer to compare it against."""
        for task in slo_tasks:
            for sample in task.samples:
                assert sample.target is None, (
                    f"{task.id}/{sample.id}: subjective sample has a target"
                )

    def test_these_tasks_report_as_not_yet_scorable(self, slo_tasks: list) -> None:
        """``is_scorable`` means "gradable with no judge configured". For these
        it must be False, so a run with no judge records a blank rather than a
        zero -- a zero would read as a failing model."""
        for task in slo_tasks:
            assert task.is_scorable is False, f"{task.id}"

    def test_every_task_steers_the_response_with_a_system_prompt(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert task.system_prompt and task.system_prompt.strip(), f"{task.id}"


class TestTheDashboardTagContract:
    """The tags a dashboard groups on. These are a cross-team interface: the SLO
    families are authored separately and only line up on the dashboard if the
    tag spellings match exactly, so they are pinned rather than left to
    convention."""

    def test_every_task_declares_its_slo(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            expected = SLO_TAG[_prefix_of(task)]
            assert expected in task.tags, f"{task.id}: missing {expected!r}; has {task.tags}"

    def test_no_task_declares_two_slos(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            declared = [t for t in task.tags if t.startswith("slo:")]
            assert declared == [SLO_TAG[_prefix_of(task)]], f"{task.id}: {declared}"

    def test_every_task_declares_the_capability_use_mode(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert USE_MODE_TAG in task.tags, f"{task.id}: missing {USE_MODE_TAG!r}"

    def test_the_ladder_tag_agrees_with_the_id(self, slo_tasks: list) -> None:
        """``ladder-l3`` in tags and ``l3-`` in the id are the same claim written
        twice; if they disagree the catalog sorts one way and groups another."""
        for task in slo_tasks:
            rung = task.id.rsplit("/", 1)[1].split("-")[0]
            assert f"ladder-{rung}" in task.tags, f"{task.id}: tags say {task.tags}"

    def test_every_task_is_tagged_with_its_family(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert _prefix_of(task).rstrip("/") in task.tags, f"{task.id}"


class TestRubricIdentity:
    def test_rubric_ids_are_versioned(self, slo_tasks: list) -> None:
        """SCHEMA.md: version rubric ids rather than editing them in place. A
        grade is only comparable to grades from the same rubric, and editing one
        in place makes an already-finished run un-regradable."""
        for task in slo_tasks:
            assert re.search(r"-v\d+$", task.rubric.id), (
                f"{task.id}: {task.rubric.id!r} is unversioned"
            )

    def test_no_rubric_id_is_shared_with_any_other_task_in_the_repository(
        self, catalog: TaskCatalog, slo_tasks: list
    ) -> None:
        """Checked against the WHOLE catalog, not just these families: reusing an
        id another family already owns silently pools two different rubrics'
        grades."""
        mine = {t.id: t.rubric.id for t in slo_tasks}
        others = [t for t in catalog.all() if t.id not in mine and t.rubric is not None]
        for task_id, rubric_id in mine.items():
            clash = [t.id for t in others if t.rubric.id == rubric_id]
            assert not clash, f"{task_id}: rubric id {rubric_id!r} is already used by {clash}"
        assert len(set(mine.values())) == len(mine), "two of these tasks share a rubric id"

    def test_the_scale_is_usable(self, slo_tasks: list) -> None:
        """A rubric with no criteria, or with scale_min == scale_max, is refused
        at grading time rather than scored 0.0."""
        for task in slo_tasks:
            assert task.rubric.criteria, f"{task.id}: empty rubric"
            assert task.rubric.scale_min != task.rubric.scale_max, f"{task.id}: degenerate scale"


class TestTheAnchorsAreAnchors:
    """ "An anchor is a description of observable behaviour at a score level. An
    adjective is not an anchor." The anchors live inside the description string
    because the schema has no per-level field, so their structure is only ever
    one careless edit from being lost -- which is what these tests watch."""

    def test_every_criterion_states_all_three_levels(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                found = set(ANCHOR_LINE.findall(criterion.description))
                assert found == {"1.0", "0.5", "0.0"}, (
                    f"{task.id}/{criterion.name}: anchor levels present are {sorted(found)}"
                )

    def test_the_anchors_survived_as_separate_lines(self, slo_tasks: list) -> None:
        """The literal-vs-folded trap. A folded scalar (``>-``) runs the three
        anchors into one paragraph and destroys the structure the judge reads;
        the file would still validate and the grades would just get noisier. The
        only durable evidence of ``|-`` is that the newlines are still there."""
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                lines = [ln for ln in criterion.description.splitlines() if ln.strip()]
                assert len(lines) >= 4, (
                    f"{task.id}/{criterion.name}: description collapsed to "
                    f"{len(lines)} line(s) -- folded scalar instead of literal?"
                )
                for level in ("1.0", "0.5", "0.0"):
                    starts = [ln for ln in lines if ln.strip().startswith(f"{level} --")]
                    assert len(starts) == 1, (
                        f"{task.id}/{criterion.name}: {level} anchor not on its own line"
                    )

    def test_every_criterion_opens_with_the_question_it_answers(self, slo_tasks: list) -> None:
        """The template's first element: one question the judge is answering.
        A criterion that opens straight into anchors gives the judge no frame."""
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                head = criterion.description.split("1.0 --")[0].strip()
                assert "?" in head, f"{task.id}/{criterion.name}: no question before the anchors"


class TestWeightsAndTension:
    def test_every_weight_is_positive(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                assert criterion.weight > 0, f"{task.id}/{criterion.name}"

    def test_every_rubric_carries_an_equally_weighted_pair_at_the_top(
        self, slo_tasks: list
    ) -> None:
        """ "If the real task has a tension in it, put the tension in the rubric."
        Both families were authored around a pull -- name the principle against
        do not shotgun, be complete against be brief, be clear against keep the
        relationship. The mechanism that makes a pull binding is two criteria at
        EQUAL top weight, so neither can be bought with the other. A rubric
        whose heaviest criterion is unique has lost its tension."""
        for task in slo_tasks:
            weights = [c.weight for c in task.rubric.criteria]
            top = max(weights)
            assert weights.count(top) >= 2, (
                f"{task.id}: only one criterion at the top weight {top} -- "
                "the tension pair has been broken"
            )

    def test_no_rubric_is_dominated_by_a_single_criterion(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            weights = [c.weight for c in task.rubric.criteria]
            assert max(weights) / sum(weights) <= 0.5, (
                f"{task.id}: one criterion carries the rubric"
            )


class TestCriterionNamesStayJudgeSafe:
    """Each criterion is graded in its own model call, which must see no other
    criterion. ``test_judge.py`` asserts that repository-wide by checking no
    other criterion's NAME appears in a criterion's prompt -- which means a
    criterion named with a bare English word (``clarity``, ``tone``) would trip
    that guard the moment the word appeared in a scenario or another anchor.
    Multi-word hyphenated slugs cannot occur in prose, so the naming convention
    is load-bearing rather than cosmetic, and it is asserted here at the point
    where it is chosen."""

    def test_names_are_multi_word_hyphenated_slugs(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                assert re.fullmatch(r"[a-z]+(-[a-z]+){2,}", criterion.name), (
                    f"{task.id}/{criterion.name}: expected a lowercase hyphenated slug "
                    "of at least three words"
                )

    def test_names_are_unique_within_a_rubric(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            names = [c.name for c in task.rubric.criteria]
            assert len(set(names)) == len(names), f"{task.id}: duplicate criterion name"

    def test_no_criterion_name_appears_in_a_sample_a_judge_will_see(self, slo_tasks: list) -> None:
        """The specific way the repository-wide guard would break for a
        generative family: the sample text is in the prompt, so a criterion
        named after a word the scenario uses leaks into every sibling's call."""
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                for sample in task.samples:
                    assert criterion.name not in sample.input, (
                        f"{task.id}/{criterion.name}: name occurs in sample {sample.id}"
                    )


class TestDatasetHygiene:
    """Everything under ``tasks/`` is committed to a public repository and
    published by an unauthenticated API. Both families are entirely invented --
    business ethics scenarios and business-writing prompts are exactly the
    content where a real case or a real student submission would be easiest to
    reach for, and FERPA makes that a bright line rather than a preference."""

    def test_every_task_states_its_provenance(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert task.description, f"{task.id}: no description"
            assert "synthetic" in task.description.lower(), (
                f"{task.id}: description carries no provenance statement"
            )

    def test_every_sample_declares_synthetic_provenance(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for sample in task.samples:
                assert sample.metadata.get("provenance") == "synthetic", (
                    f"{task.id}/{sample.id}: provenance is {sample.metadata.get('provenance')!r}"
                )

    def test_sample_metadata_carries_only_publishable_keys(self, slo_tasks: list) -> None:
        """Targets are redacted by the API; metadata is not. Author's notes,
        expected verdicts and derivations belong in YAML comments, which never
        leave the repository."""
        for task in slo_tasks:
            for sample in task.samples:
                extra = set(sample.metadata) - PUBLISHABLE_METADATA_KEYS
                assert not extra, (
                    f"{task.id}/{sample.id}: unexpected published metadata keys {extra}"
                )


class TestSampleCoverage:
    def test_every_task_spans_at_least_four_cases(self, slo_tasks: list) -> None:
        """ "Coverage matters more than volume": a clean case, a borderline one, a
        trap, and one where the honest answer is the undramatic one."""
        for task in slo_tasks:
            assert len(task.samples) >= 4, f"{task.id}: {len(task.samples)} sample(s)"

    def test_every_sample_declares_what_it_probes(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for sample in task.samples:
                assert sample.metadata.get("probe"), f"{task.id}/{sample.id}: no probe declared"

    def test_no_task_repeats_a_probe(self, slo_tasks: list) -> None:
        """Four samples all probing the same thing is one sample averaged four
        times, and averages away the profile the platform exists to report."""
        for task in slo_tasks:
            probes = [s.metadata["probe"] for s in task.samples]
            assert len(set(probes)) == len(probes), f"{task.id}: repeated probe in {probes}"

    def test_sample_ids_are_path_safe_and_unique(self, slo_tasks: list) -> None:
        """A sample id becomes the leaf of its transcript's object key."""
        for task in slo_tasks:
            ids = [s.id for s in task.samples]
            assert len(set(ids)) == len(ids), f"{task.id}: duplicate sample id"
            for sample_id in ids:
                assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", sample_id), (
                    f"{task.id}/{sample_id}: not path-safe"
                )

    def test_every_sample_is_a_substantial_scenario(self, slo_tasks: list) -> None:
        """Both rubrics ask the judge whether the response engaged the specific
        facts. A one-line scenario has no specific facts to engage."""
        for task in slo_tasks:
            for sample in task.samples:
                assert len(sample.input.split()) >= 40, (
                    f"{task.id}/{sample.id}: {len(sample.input.split())} words is too thin "
                    "to carry the judgement the rubric asks for"
                )


class TestTheseRubricsReachTheJudge:
    """The authored file is one thing; what the judge actually receives is
    another. These drive the real prompt builder and the real judge over the
    real files."""

    def test_every_anchor_survives_into_the_judge_prompt(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                user = build_criterion_messages(
                    task=task,
                    sample=task.samples[0],
                    completion="A plausible response.",
                    criterion=criterion,
                    rubric=task.rubric,
                )[-1].content
                assert criterion.description.strip() in user, (
                    f"{task.id}/{criterion.name}: anchors did not survive into the prompt"
                )

    def test_no_criterion_sees_its_siblings(self, slo_tasks: list) -> None:
        """Criterion order must not be able to move a score. Asserted here for
        these families specifically because their criterion names are long and
        their sample text is prose, which is the combination most likely to
        produce an accidental collision."""
        for task in slo_tasks:
            names = [c.name for c in task.rubric.criteria]
            for criterion in task.rubric.criteria:
                body = build_criterion_messages(
                    task=task,
                    sample=task.samples[0],
                    completion="A plausible response.",
                    criterion=criterion,
                    rubric=task.rubric,
                )[-1].content.split("## The one criterion you are grading")[1]
                for other in (
                    n for n in names if n != criterion.name and n not in criterion.description
                ):
                    assert other not in body, f"{task.id}: {other!r} leaked into {criterion.name!r}"

    def test_no_criterion_prompt_leaks_a_weight(self, slo_tasks: list) -> None:
        """A judge told a criterion is "worth 3" grades it more harshly. Weight
        is aggregation metadata applied afterwards, and these rubrics lean on
        weights heavily -- the equal-weight tension pairs are the mechanism -- so
        the leak would be costlier here than elsewhere."""
        for task in slo_tasks:
            for criterion in task.rubric.criteria:
                body = build_criterion_messages(
                    task=task,
                    sample=task.samples[0],
                    completion="A plausible response.",
                    criterion=criterion,
                    rubric=task.rubric,
                )[-1].content.split("## The one criterion you are grading")[1]
                assert "weight" not in body.lower(), f"{task.id}/{criterion.name}: weight leaked"

    @pytest.mark.parametrize(
        "task_id",
        [
            "slo-6-ethical-reasoning/l1-principle-identification",
            "slo-6-ethical-reasoning/l5-law-and-ethics-distinction",
            "slo-7-written-communication/l1-routine-message",
            "slo-7-written-communication/l5-channel-and-restraint",
        ],
    )
    def test_a_task_from_each_family_grades_end_to_end(
        self, catalog: TaskCatalog, judge_entry, task_id: str
    ) -> None:
        """The floor and the ceiling of each ladder, through the real judge and
        the real mock-model service answering the real protocol.

        What this proves is that these files GRADE -- every criterion round-trips
        to a number, the weighted aggregate matches, and no sample errors. It
        proves nothing about the scores themselves: the mock is a deterministic
        canned-answer service, not a language model, so its score carries no
        information about the task's quality. Asserting a score threshold here
        would be asserting a property of the mock.
        """
        from ida_harness.client import OpenAICompatibleClient
        from ida_mock_model.testing import make_transport

        task = catalog.get(task_id)
        client = OpenAICompatibleClient(judge_entry, transport=make_transport())
        with LLMJudge(entry=judge_entry, client=client, owns_client=True) as judge:
            verdict = judge.grade(
                task=task,
                sample=task.samples[0],
                completion="A response that engages the scenario in a few sentences.",
            )

        assert verdict.error is None, f"{task_id}: {verdict.error}"
        assert verdict.score is not None
        assert len(verdict.score.criteria) == len(task.rubric.criteria)
        assert 0.0 <= verdict.score.value <= 1.0
        assert verdict.score.value == pytest.approx(aggregate(verdict.score.criteria))
