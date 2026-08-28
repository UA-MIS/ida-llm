"""The SLO-anchored benchmark, checked against the curriculum map it claims.

``tools/validate_tasks.py`` already enforces the per-task tag contract and is
the CI gate for it; these tests cover what a per-file check cannot see -- the
properties of the benchmark taken as a whole. Every assertion here is about a
SHAPE the benchmark must keep, never about a specific list of task ids:
authoring a family is the routine contribution this repository invites, so an
equality against the current inventory would fail on every new family and teach
contributors to edit the assertion rather than read it.
"""

from __future__ import annotations

import collections

import pytest

from ida_core.config import repo_root
from ida_core.contracts import TaskKind
from ida_core.curriculum import (
    BENCHMARK_TAG,
    CurriculumMap,
    check_task_tags,
    default_curriculum_path,
    load_curriculum,
    slo_of,
    use_mode_of,
)
from ida_harness.tasks import TaskCatalog


@pytest.fixture(scope="module")
def curriculum() -> CurriculumMap:
    return load_curriculum(default_curriculum_path(repo_root()))


@pytest.fixture(scope="module")
def catalog() -> TaskCatalog:
    return TaskCatalog.from_directory(repo_root() / "tasks")


@pytest.fixture(scope="module")
def slo_tasks(catalog: TaskCatalog) -> list:
    return [t for t in catalog.all() if BENCHMARK_TAG in t.tags]


@pytest.fixture(scope="module")
def by_outcome(slo_tasks) -> dict[str, list]:
    grouped: dict[str, list] = collections.defaultdict(list)
    for spec in slo_tasks:
        grouped[slo_of(spec.tags)].append(spec)
    return dict(grouped)


class TestTheBenchmarkIsWellFormed:
    def test_every_shipped_task_satisfies_the_tag_contract(
        self, catalog: TaskCatalog, curriculum: CurriculumMap
    ) -> None:
        """Belt and braces with the CI gate, because this one runs in `make test`."""
        problems = [p for spec in catalog.all() for p in check_task_tags(spec, curriculum)]
        assert problems == []

    def test_the_benchmark_is_not_empty(self, slo_tasks) -> None:
        assert slo_tasks, f"no task carries the {BENCHMARK_TAG!r} tag"

    def test_every_slo_task_declares_a_ladder_rung(self, slo_tasks) -> None:
        """The rung must be machine-readable, not only inferable from the id."""
        for spec in slo_tasks:
            assert any(t.startswith("ladder-l") for t in spec.tags), (
                f"{spec.id} carries no ladder-lN tag"
            )

    def test_every_slo_task_is_in_a_mode_that_is_in_use(self, slo_tasks, curriculum) -> None:
        in_use = set(curriculum.in_use_mode_ids())
        assert {use_mode_of(s.tags) for s in slo_tasks} <= in_use


class TestCoverageOfTheCurriculum:
    def test_the_outcomes_this_branch_owns_have_families(
        self, by_outcome, curriculum: CurriculumMap
    ) -> None:
        """This branch authors the MIS 200 trio. The other four land separately.

        The full-coverage assertion -- every ``text_benchmarkable`` outcome has
        a family -- is the one this suite eventually wants, and it is written
        below as ``test_no_benchmarkable_outcome_is_silently_uncovered``. It is
        deliberately NOT enforced as "all seven" yet, because SLO3/SLO4 and
        SLO6/SLO7 are authored on sibling branches; asserting all seven here
        would make this branch fail for work it does not contain, and the usual
        response to that is to weaken the assertion permanently.

        **When those branches land, tighten this to the full seven.** Until
        then the honest statement is: the three outcomes MIS 200 carries are
        covered, and nothing claims to cover more than it does.
        """
        owned = {"SLO1", "SLO2", "SLO9"}
        assert owned <= set(by_outcome), f"missing families for {sorted(owned - set(by_outcome))}"
        assert owned == set(curriculum.outcomes_for_course("MIS 200"))

    def test_no_benchmarkable_outcome_is_silently_uncovered(
        self, by_outcome, curriculum: CurriculumMap
    ) -> None:
        """Report the coverage gap out loud rather than letting it be invisible.

        A partial benchmark is fine; a partial benchmark nobody can see is not.
        This asserts only that every outcome WITH tasks is one the curriculum
        map marks benchmarkable -- the direction that would be a defect today --
        and prints the outstanding gap so it cannot be forgotten.
        """
        benchmarkable = set(curriculum.text_benchmarkable_ids())
        assert set(by_outcome) <= benchmarkable, (
            f"tasks exist for non-benchmarkable outcomes: {sorted(set(by_outcome) - benchmarkable)}"
        )
        outstanding = sorted(benchmarkable - set(by_outcome))
        print(
            f"\ncoverage: {len(by_outcome)}/{len(benchmarkable)} benchmarkable outcomes; "
            f"awaiting sibling branches: {outstanding or 'none'}"
        )

    def test_no_task_claims_an_outcome_a_text_benchmark_cannot_reach(
        self, by_outcome, curriculum: CurriculumMap
    ) -> None:
        """SLO5 (Teamwork) and SLO8 (Oral Communication) must stay uncovered.

        Not an oversight being pinned -- a decision. Measuring a model's ability
        to WRITE about teamwork and filing it under SLO5 would be the most
        misleading thing this repository could publish, so the absence is
        asserted rather than left to whoever authors next.
        """
        unreachable = set(curriculum.outcome_ids()) - set(curriculum.text_benchmarkable_ids())
        assert unreachable == {"SLO5", "SLO8"}
        assert not (unreachable & set(by_outcome))

    def test_the_mis_200_outcomes_are_authored_to_depth(self, by_outcome, curriculum) -> None:
        """MIS 200 is the target course for the first live run.

        Its three outcomes carry the families that have to be usable now, so
        each gets a real ladder rather than a token task. Four is the floor
        `tasks/SCHEMA.md` sets for a family; these were authored to five and six.
        """
        mis200 = curriculum.outcomes_for_course("MIS 200")
        assert set(mis200) == {"SLO1", "SLO2", "SLO9"}
        for outcome_id in mis200:
            rungs = by_outcome.get(outcome_id, [])
            assert len(rungs) >= 4, f"{outcome_id} has only {len(rungs)} rung(s)"

    def test_the_quantitative_family_is_scorable_without_a_judge(self, by_outcome) -> None:
        """SLO2 is MIS 200's assessment point, so it must produce numbers today.

        A subjective SLO2 family would report `scorable: false` until a judge
        model is configured and funded -- which would leave the one outcome the
        department actually assesses as the one this benchmark cannot score.
        """
        slo2 = by_outcome["SLO2"]
        assert all(t.kind is TaskKind.VERIFIABLE for t in slo2)
        assert all(t.is_scorable for t in slo2)

    def test_the_benchmark_spans_both_halves_of_the_taxonomy(self, slo_tasks) -> None:
        """Verifiable and subjective families both present.

        A benchmark that was all-verifiable would have quietly dropped every
        outcome whose verb is "evaluate", "construct" or "propose".
        """
        assert {t.kind for t in slo_tasks} == {TaskKind.VERIFIABLE, TaskKind.SUBJECTIVE}


class TestFamilyStructure:
    def test_each_outcomes_tasks_share_one_kind(self, by_outcome) -> None:
        """`tasks/SCHEMA.md`: a family mixing kinds is two families in a directory."""
        for outcome_id, specs in by_outcome.items():
            kinds = {t.kind for t in specs}
            assert len(kinds) == 1, f"{outcome_id} mixes kinds: {kinds}"

    def test_ladder_rungs_are_unique_within_an_outcome(self, by_outcome) -> None:
        """Two tasks on rung 3 is not a ladder, and the duplicate would be invisible."""
        for outcome_id, specs in by_outcome.items():
            rungs = [t for s in specs for t in s.tags if t.startswith("ladder-l")]
            assert len(rungs) == len(set(rungs)), f"{outcome_id} has duplicate rungs: {rungs}"

    def test_task_ids_are_prefixed_by_their_family_directory(self, by_outcome, catalog) -> None:
        """The id prefix and the directory name are the same string, so a result
        row can be traced back to a file without a lookup."""
        for specs in by_outcome.values():
            for spec in specs:
                prefix = spec.id.split("/")[0]
                assert catalog.source_of(spec.id).parent.name == prefix

    def test_every_subjective_slo_task_has_an_anchored_rubric(self, slo_tasks) -> None:
        """A rubric with one criterion, or one whose id is unversioned, is a
        rubric that cannot be compared against itself later."""
        for spec in slo_tasks:
            if spec.kind is not TaskKind.SUBJECTIVE:
                continue
            assert spec.rubric is not None
            assert spec.rubric.id.endswith("-v1") or "-v" in spec.rubric.id, (
                f"{spec.id}: rubric id {spec.rubric.id!r} is not versioned"
            )
            assert len(spec.rubric.criteria) >= 3, f"{spec.id}: too few criteria to discriminate"
            assert spec.rubric.scale_min < spec.rubric.scale_max

    def test_every_verifiable_slo_sample_has_a_target(self, slo_tasks) -> None:
        for spec in slo_tasks:
            if spec.kind is TaskKind.VERIFIABLE:
                assert all(s.target for s in spec.samples), f"{spec.id} has an empty target"

    def test_every_slo_sample_declares_synthetic_provenance(self, slo_tasks) -> None:
        """Dataset hygiene, asserted rather than trusted.

        `tasks/SCHEMA.md` requires a provenance value on every sample and
        nothing in the schema enforces it. Everything in this benchmark was
        invented for it; if a sample ever arrives without saying so, that is
        the moment to ask where it came from.
        """
        for spec in slo_tasks:
            for sample in spec.samples:
                assert sample.metadata.get("provenance") == "synthetic", (
                    f"{spec.id}/{sample.id} does not declare synthetic provenance"
                )


class TestTheScorersAdmitACorrectAnswer:
    """The check a mock run cannot perform.

    Running the tree against the mock proves the pipeline executes; it cannot
    prove the scorer would accept a RIGHT answer, because the mock never gives
    one. A normalisation or tolerance mistake therefore survives a green mock
    run and surfaces later as a real model scoring zero on items it answered
    correctly -- silently, with no error, which `tasks/SCHEMA.md` names as the
    worst way for a task to fail.

    So each verifiable sample is scored against the completion a correct model
    would emit: some reasoning, then the gold answer on the last line, which is
    the shape every one of these tasks' system prompts demands.
    """

    PREAMBLE = (
        "Restating the item first: the figures given are 12.50 and 3,400 and 7%.\n"
        "Working through it step by step gives an intermediate of 1,234.56.\n"
        "Therefore the value for the answer key is:\n"
    )

    @pytest.fixture(scope="class")
    def verifiable(self, slo_tasks) -> list:
        specs = [t for t in slo_tasks if t.kind is TaskKind.VERIFIABLE]
        assert specs, "no verifiable SLO tasks to check"
        return specs

    def test_a_correct_answer_scores_one(self, verifiable) -> None:
        from ida_harness.scoring import build_scorer

        wrong = []
        for spec in verifiable:
            scorer = build_scorer(spec.scorer)
            for sample in spec.samples:
                got = scorer.score(self.PREAMBLE + sample.target, sample.target)
                if got.value != 1.0:
                    wrong.append(f"{spec.id}/{sample.id}: scored {got.value} ({got.explanation})")
        assert wrong == [], "the scorer rejected a correct answer:\n" + "\n".join(wrong)

    def test_a_wrong_answer_scores_zero(self, verifiable) -> None:
        """A scorer that accepts everything is not measuring anything."""
        from ida_core.contracts import ScorerKind
        from ida_harness.scoring import build_scorer

        lenient = []
        for spec in verifiable:
            scorer = build_scorer(spec.scorer)
            other = "0.123456789" if spec.scorer.kind is ScorerKind.NUMERIC_MATCH else "z"
            for sample in spec.samples:
                got = scorer.score(self.PREAMBLE + other, sample.target)
                if got.value != 0.0:
                    lenient.append(f"{spec.id}/{sample.id}: scored {got.value}")
        assert lenient == [], "the scorer accepted a wrong answer:\n" + "\n".join(lenient)

    def test_the_numeric_tolerance_actually_binds(self, verifiable) -> None:
        """A value just outside the stated tolerance must be rejected.

        Guards the other direction from the test above: a tolerance widened by
        accident -- or a `relative_tolerance` left set from an earlier draft --
        would swallow a whole wrong method, and it would do so silently.
        """
        from ida_core.contracts import ScorerKind
        from ida_harness.scoring import build_scorer

        swallowed = []
        for spec in verifiable:
            if spec.scorer.kind is not ScorerKind.NUMERIC_MATCH:
                continue
            scorer = build_scorer(spec.scorer)
            for sample in spec.samples:
                want = float(sample.target)
                slack = max(spec.scorer.tolerance, abs(want) * spec.scorer.relative_tolerance)
                just_outside = want + slack * 1.5 + 1e-9
                if scorer.score(self.PREAMBLE + repr(just_outside), sample.target).value != 0.0:
                    swallowed.append(f"{spec.id}/{sample.id}: accepted {just_outside}")
        assert swallowed == [], "tolerance is wider than declared:\n" + "\n".join(swallowed)


class TestTheBenchmarkRunsAgainstTheMock:
    """Every SLO task, through the real harness, against the real mock service.

    `tasks/SCHEMA.md` says what to check after a mock run, and it is not the
    score: that the run completes, that every sample produced a transcript,
    that no sample carries an `error` -- an errored sample usually means an
    unparseable target -- and that subjective tasks come back UNSCORED rather
    than zeroed. A low score against the mock means nothing; a zero where a
    blank belongs means the platform is claiming a model failed when it has not
    been measured.

    Nothing here is mocked. `run_task`, the scorers, the client and the
    mock-model service are all the real implementations; only the transport is
    in-process, so there is no port and no container.
    """

    @pytest.fixture(scope="class")
    def logs(self, slo_tasks, tmp_path_factory) -> dict:
        from ida_core.artifacts import LocalArtifactStore
        from ida_core.registry import load_registry
        from ida_harness.client import OpenAICompatibleClient
        from ida_harness.runner import run_task
        from ida_mock_model.testing import make_transport

        entry = load_registry(repo_root() / "models.yaml").get("mock")
        transport = make_transport()
        store = LocalArtifactStore(str(tmp_path_factory.mktemp("slo")), bucket="slo-check")
        store.ensure_bucket()

        out = {}
        for i, spec in enumerate(slo_tasks):
            client = OpenAICompatibleClient(entry, transport=transport)
            try:
                out[spec.id] = run_task(
                    task=spec,
                    entry=entry,
                    run_id=f"slocheck{i:04d}",
                    task_git_sha="0" * 40,
                    artifact_store=store,
                    client=client,
                )
            finally:
                client.close()
        return out

    def test_every_sample_produced_a_result(self, logs, catalog) -> None:
        for task_id, log in logs.items():
            assert len(log.results) == len(catalog.get(task_id).samples)

    def test_no_sample_errored(self, logs) -> None:
        """An errored sample is a real defect, usually an unparseable target."""
        errored = [
            f"{task_id}/{r.sample_id}: {r.error}"
            for task_id, log in logs.items()
            for r in log.results
            if r.error
        ]
        assert errored == [], "\n".join(errored)

    def test_every_sample_archived_a_transcript(self, logs) -> None:
        missing = [
            f"{task_id}/{r.sample_id}"
            for task_id, log in logs.items()
            for r in log.results
            if not r.transcript_uri or r.archive_error
        ]
        assert missing == [], "\n".join(missing)

    def test_verifiable_tasks_are_scored_and_subjective_ones_are_blank(self, logs, catalog) -> None:
        """The distinction the platform exists to keep: a blank is not a zero.

        With no judge configured, a subjective task must report `scorable:
        False` and `score: None`. Reporting 0.0 would say the model failed
        every criterion, which is a false statement about a model nobody has
        graded yet.
        """
        for task_id, log in logs.items():
            verifiable = catalog.get(task_id).kind is TaskKind.VERIFIABLE
            for r in log.results:
                assert r.scorable is verifiable, f"{task_id}/{r.sample_id}"
                assert (r.score is not None) is verifiable, f"{task_id}/{r.sample_id}"
            assert (log.mean_score is not None) is verifiable, task_id
