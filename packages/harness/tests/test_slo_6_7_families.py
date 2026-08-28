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

#: The SLO a dashboard groups on, per family. Colon-delimited tag strings rather
#: than top-level YAML keys, because ``task.schema.json`` sets
#: ``additionalProperties: false`` and ``tags`` is the only free-form field the
#: schema exposes. The uppercase ``SLO6``/``SLO7`` spelling is load-bearing:
#: ``make lint-tasks`` fails a ``slo:`` tag naming an SLO absent from
#: ``curriculum/slo.yaml``.
SLO_TAG = {SLO6_PREFIX: "slo:SLO6", SLO7_PREFIX: "slo:SLO7"}

#: The SLO id on its own, as it appears in sample metadata.
SLO_ID = {SLO6_PREFIX: "SLO6", SLO7_PREFIX: "SLO7"}

#: Every task across all five SLO families carries this, so the benchmark can be
#: selected as one body of work.
BENCHMARK_TAG = "slo-benchmark"

#: Every task in both families is a capability probe, not a use-mode simulation.
#:
#: HYPHEN in the tag, UNDERSCORE in the sample metadata key below. That is not a
#: typo and not a preference: tags are a flat string list whose convention is
#: ``key:value`` with hyphenated keys, while metadata is a dict whose keys are
#: un-prefixed snake_case. The two spellings are pinned separately here because
#: the shapes are agreed across five independently authored SLO families and a
#: silent drift in either one degroups this family on the dashboard without
#: failing anything else.
USE_MODE_TAG = "use-mode:capability"
USE_MODE_METADATA = ("use_mode", "capability")

RUNGS = ("l1", "l2", "l3", "l4", "l5")

#: Sample ``metadata`` is published UNAUTHENTICATED by ``GET /tasks/{id}``
#: (tasks/SCHEMA.md, "Dataset hygiene"). Only keys that are safe to publish and
#: useful to a consumer belong there; author's notes and expected verdicts live
#: in YAML comments. Pinning the allowed key set is what stops a future edit
#: from parking an expected answer in a published field.
PUBLISHABLE_METADATA_KEYS = {"slo", "use_mode", "probe", "genre", "provenance"}

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

    def test_the_use_mode_tag_is_hyphenated_not_underscored(self, slo_tasks: list) -> None:
        """The exact failure this pins: ``use_mode:capability`` in ``tags`` reads
        fine, validates fine, and silently drops the task out of the dashboard's
        grouping. The underscore spelling belongs in sample metadata, not here."""
        for task in slo_tasks:
            assert "use_mode:capability" not in task.tags, (
                f"{task.id}: tag must be {USE_MODE_TAG!r} (hyphen); the underscore "
                "spelling is the sample-metadata key, not the tag"
            )

    def test_every_task_carries_the_benchmark_family_tag(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            assert BENCHMARK_TAG in task.tags, f"{task.id}: missing {BENCHMARK_TAG!r}"

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

    def test_every_sample_repeats_its_slo_and_use_mode_for_drill_down(
        self, slo_tasks: list
    ) -> None:
        """Task ``tags`` group the dashboard; sample ``metadata`` is what a
        drill-down reads, and it is served to everyone unauthenticated. Both
        carry the same two facts, so they have to be asserted to agree -- a
        sample that disagrees with its own task is worse than one that omits
        the keys, because it reads as authoritative."""
        key, value = USE_MODE_METADATA
        for task in slo_tasks:
            expected_slo = SLO_ID[_prefix_of(task)]
            for sample in task.samples:
                assert sample.metadata.get("slo") == expected_slo, (
                    f"{task.id}/{sample.id}: metadata slo is "
                    f"{sample.metadata.get('slo')!r}, task is {expected_slo!r}"
                )
                assert sample.metadata.get(key) == value, (
                    f"{task.id}/{sample.id}: metadata {key} is {sample.metadata.get(key)!r}"
                )

    def test_sample_metadata_uses_the_underscore_spelling(self, slo_tasks: list) -> None:
        """The mirror of the tag test above, and the other half of the trap."""
        for task in slo_tasks:
            for sample in task.samples:
                assert "use-mode" not in sample.metadata, (
                    f"{task.id}/{sample.id}: metadata key must be 'use_mode' (underscore); "
                    "the hyphen spelling is the tag, not the metadata key"
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


#: Verdict vocabulary that must never reach a PUBLISHED sample field.
#:
#: ``GET /tasks/{id}`` returns each sample's ``id`` and ``metadata`` verbatim and
#: unauthenticated, and it returns the whole ``rubric`` too -- only ``target`` is
#: redacted. So an id or a metadata value that STATES the expected answer
#: ("no-issue-present", "brevity-is-the-answer", "trap-permitted-but-wrong") is a
#: public contamination leak: a scraper gets the scenario and the verdict
#: together, and a future training corpus gets the answer key this endpoint's
#: redaction exists to protect.
#:
#: The design role each sample plays is genuinely useful to an author, so it
#: still lives beside the sample -- in a YAML COMMENT, which is not parsed, is
#: not part of ``content_sha`` and never leaves the repository. That is the
#: placement SCHEMA.md prescribes for expected verdicts, and this list is what
#: keeps it there.
LEAKY_VERDICT_TOKENS = (
    "trap",
    "clean-",
    "no-issue",
    "nothing",
    "correct",
    "wrong",
    "defensible",
    "convergence",
    "objectionable",
    "aligned",
    "brevity-is",
    "minimal-adaptation",
    "no-artefact",
    "already-requires",
    "thin-evidence",
    "should-narrow",
    "cannot-be-offered",
    "both-wrong",
)


class TestPublishedSampleFieldsDoNotCarryTheVerdict:
    """The answer must not be reachable from the fields the API publishes."""

    def test_no_sample_id_states_the_expected_answer(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for sample in task.samples:
                for token in LEAKY_VERDICT_TOKENS:
                    assert token not in sample.id, (
                        f"{task.id}/{sample.id}: sample id carries the verdict token "
                        f"{token!r}; sample ids are published unauthenticated"
                    )

    def test_no_metadata_value_states_the_expected_answer(self, slo_tasks: list) -> None:
        for task in slo_tasks:
            for sample in task.samples:
                for key, value in sample.metadata.items():
                    for token in LEAKY_VERDICT_TOKENS:
                        assert token not in str(value), (
                            f"{task.id}/{sample.id}: metadata.{key} is {value!r}, which "
                            f"carries the verdict token {token!r}; metadata is published "
                            "verbatim and unauthenticated"
                        )


#: The sample in each task whose correct answer is the UNDRAMATIC one, and the
#: criteria whose 1.0 anchor had to be widened to admit it.
#:
#: Every family here mandates a counterweight sample -- one where the honest
#: answer is "there is no issue", "nothing transmits", "no message should be
#: written". A rubric whose top criterion demands a positive existence ("names a
#: principle", "the artefact could be sent as written") scores that CORRECT
#: answer 0.0, which silently inverts the measurement: the models that get it
#: right are marked down. Each anchor below now carries an explicit alternative
#: branch, and this table is what stops one being dropped in a later edit.
#:
#: It lives in the test file rather than in sample metadata on purpose -- naming
#: the counterweight in metadata would publish the very thing the leak guard
#: above removes.
COUNTERWEIGHT_BRANCHES = {
    "slo-6-ethical-reasoning/l1-principle-identification": {
        "does-not-shotgun-extra-principles": "where the facts raise no principle",
        "quotes-or-cites-a-specific-fact": "where the facts raise no principle",
    },
    "slo-6-ethical-reasoning/l3-framework-application": {
        "keeps-the-three-analyses-unmerged": "converge on the same recommendation",
    },
    "slo-6-ethical-reasoning/l2-stakeholder-analysis": {
        "ranks-the-stakes-against-each-other": "genuinely small and comparable",
    },
    "slo-6-ethical-reasoning/l5-law-and-ethics-distinction": {
        "does-not-treat-legality-as-settling-the-ethics": "reach the same answer",
    },
    "slo-7-written-communication/l2-audience-adaptation": {
        "speaks-the-named-readers-language": "specialist in the source's",
    },
    "slo-7-written-communication/l3-negative-message": {
        "promises-nothing-the-sender-cannot-deliver": "no future possibility at all",
    },
    "slo-7-written-communication/l5-channel-and-restraint": {
        "keeps-out-of-writing-what-should-not-be-written-down": "nothing should be written",
        "the-artefact-itself-is-well-written": "no artefact should be written",
    },
}


class TestTheUndramaticAnswerCanStillScoreFull:
    """A correct "nothing to report" answer must be able to reach 1.0."""

    def test_each_widened_anchor_still_carries_its_alternative_branch(
        self, slo_tasks: list
    ) -> None:
        by_id = {task.id: task for task in slo_tasks}
        for task_id, criteria in COUNTERWEIGHT_BRANCHES.items():
            task = by_id[task_id]
            named = {c.name: c for c in task.rubric.criteria}
            for criterion_name, branch in criteria.items():
                assert criterion_name in named, f"{task_id}: no criterion {criterion_name!r}"
                flat = " ".join(named[criterion_name].description.split())
                assert branch in flat, (
                    f"{task_id}/{criterion_name}: the alternative branch that lets the "
                    f"undramatic answer reach 1.0 is gone (looked for {branch!r})"
                )

    def test_the_widened_anchors_reach_the_judge_intact(self, slo_tasks: list) -> None:
        """A branch that does not survive into the prompt is not a fix."""
        by_id = {task.id: task for task in slo_tasks}
        for task_id, criteria in COUNTERWEIGHT_BRANCHES.items():
            task = by_id[task_id]
            named = {c.name: c for c in task.rubric.criteria}
            for criterion_name, branch in criteria.items():
                prompt = build_criterion_messages(
                    task=task,
                    sample=task.samples[0],
                    completion="A plausible response.",
                    criterion=named[criterion_name],
                    rubric=task.rubric,
                )[-1].content
                assert branch in " ".join(prompt.split()), (
                    f"{task_id}/{criterion_name}: the alternative branch did not survive "
                    "into the judge prompt"
                )


#: Surnames these scenarios were renamed AWAY from.
#:
#: The SLO 6 scenarios describe misconduct -- expense padding, an altered safety
#: filing, an anonymous allegation -- and they carry it off with roles alone ("a
#: top performer", "a manager"), which is the right pattern. The SLO 7 scenarios
#: originally paired a first name with a realistic surname, and several of those
#: are adverse personnel or customer matters: a refused promotion, a declined
#: refund, a rejected proposal. A published benchmark should not attach an
#: adverse account to a full name that could match a real individual, so the
#: surnames are gone and the scenarios run on first name plus role.
#:
#: Checked whitespace-insensitively against the raw file text, because a name
#: wrapped across two lines of a folded scalar is exactly how the equivalent
#: check was fooled once already.
TASKS_DIR = Path(__file__).resolve().parents[3] / "tasks"

REMOVED_SURNAMES = (
    "Reyes",
    "Reid",
    "Faraj",
    "Iyer",
    "Sørensen",
    "Sorensen",
    "Vandenberg",
    "Ostrowski",
    "Whitfield",
    "Okafor",
    "Okonjo",
    "Bramley",
    "Raman",
    "Alvarez",
    "Beaufort",
    "Halloran",
    "Adeyemi",
)


class TestScenariosDoNotNameAPlausibleRealIndividual:
    def test_no_removed_surname_comes_back(self, slo_tasks: list) -> None:
        offenders = []
        for path in sorted(TASKS_DIR.glob("slo-*/*.yaml")):
            text = path.read_text()
            for surname in REMOVED_SURNAMES:
                for match in re.finditer(rf"\b{re.escape(surname)}\b", text, re.IGNORECASE):
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line} {match.group(0)!r}")
        assert not offenders, (
            "these scenarios run on first name plus role so that no adverse account is "
            "attached to a plausible real individual; a surname came back: " + "; ".join(offenders)
        )
