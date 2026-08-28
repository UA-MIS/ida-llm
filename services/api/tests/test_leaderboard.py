"""``GET /leaderboard`` -- the task-first results view, and its trust tell.

The tests that matter here are not "does it return rows".  They are the ones
that pin the *honesty* properties: a missing score never reads as a zero, an
AI-judged score never reads like a program-checked one, and the winner of a
leaderboard is never a test stub.
"""

from __future__ import annotations

from _dashboard_helpers import (
    GRADING_TASK,
    QUIZ_TASK,
    SUBJECTIVE_TASK,
    VERIFIABLE_TASK,
    seed_run,
)
from fastapi.testclient import TestClient

from ida_api.deps import AppContext
from ida_api.leaderboard import (
    TaskLeaderboard,
    _ordered_slos,
    data_residency,
    task_axes,
    task_family,
)
from ida_api.slo import CurriculumView, OutcomeView, load_curriculum_view
from ida_api.trust import assess
from ida_core.contracts import RunStatus, ScorerKind, TaskKind


def board_for(body: dict, task_id: str) -> dict:
    return next(t for t in body["tasks"] if t["task_id"] == task_id)


class TestEmptyState:
    """A fresh install must say "nothing measured yet" -- never render a zero."""

    def test_reports_no_results_without_hiding_the_catalog(self, client: TestClient) -> None:
        body = client.get("/leaderboard").json()
        assert body["has_any_results"] is False
        assert body["measured_task_count"] == 0
        # The tasks still appear. An unbenchmarked task and a task that does not
        # exist must not look the same to the UI.
        assert body["task_count"] > 0
        assert all(task["has_results"] is False for task in body["tasks"])
        assert all(task["results"] == [] for task in body["tasks"])

    def test_no_task_claims_a_best_model(self, client: TestClient) -> None:
        body = client.get("/leaderboard").json()
        assert all(task["best_model_key"] is None for task in body["tasks"])


class TestAggregation:
    def test_a_measured_pair_appears_with_its_run_id(
        self, client: TestClient, context: AppContext
    ) -> None:
        run_id = seed_run(context, task_id=VERIFIABLE_TASK, model_key="luna", mean_score=0.8)
        board = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)

        assert board["has_results"] is True
        assert len(board["results"]) == 1
        result = board["results"][0]
        assert result["model_key"] == "luna"
        assert result["mean_score"] == 0.8
        # D-3: the receipt. Every number is one click from the run that made it.
        assert result["run_id"] == run_id

    def test_the_newest_finished_run_wins_for_a_pair(
        self, client: TestClient, context: AppContext
    ) -> None:
        """Runs of one pair are not samples of one quantity -- see the repository.

        Two runs of the same (task, model) can measure different task text or a
        different serving config. Averaging them would describe neither, so the
        newest is the one reported.
        """
        seed_run(
            context,
            task_id=VERIFIABLE_TASK,
            model_key="luna",
            mean_score=0.2,
            created_offset_minutes=0,
        )
        newest = seed_run(
            context,
            task_id=VERIFIABLE_TASK,
            model_key="luna",
            mean_score=0.95,
            created_offset_minutes=60,
        )
        board = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)

        assert len(board["results"]) == 1, "one row per (task, model), not one per run"
        assert board["results"][0]["run_id"] == newest
        assert board["results"][0]["mean_score"] == 0.95

    def test_unfinished_runs_are_not_read(self, client: TestClient, context: AppContext) -> None:
        """A queued run has no score, and a blank next to real numbers would be
        read as "nothing was measured" rather than "still going"."""
        seed_run(
            context,
            task_id=VERIFIABLE_TASK,
            model_key="luna",
            status=RunStatus.QUEUED,
            mean_score=None,
            scored_count=0,
            with_results=False,
        )
        board = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)
        assert board["has_results"] is False

    def test_ranking_is_best_first_and_unscored_rows_sink(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="luna", mean_score=0.4)
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="mock", mean_score=0.9)
        seed_run(
            context,
            task_id=VERIFIABLE_TASK,
            model_key="sparks-local",
            status=RunStatus.FAILED,
            mean_score=None,
            scored_count=0,
            error_count=5,
            with_results=False,
        )
        board = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)

        assert [r["model_key"] for r in board["results"]] == ["mock", "luna", "sparks-local"]

    def test_the_test_stub_never_wins_but_is_still_shown(
        self, client: TestClient, context: AppContext
    ) -> None:
        """`mock` is a deterministic echo server.

        Hiding its row would be a results page editing its own data; letting it
        top the leaderboard would be a results page whose winner is a fixture.
        It is shown and it is not ranked.
        """
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="mock", mean_score=1.0)
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="luna", mean_score=0.5)
        board = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)

        assert "mock" in [r["model_key"] for r in board["results"]]
        assert board["best_model_key"] == "luna"

    def test_a_failed_run_is_visible_and_is_not_a_zero(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(
            context,
            task_id=VERIFIABLE_TASK,
            model_key="luna",
            status=RunStatus.FAILED,
            mean_score=None,
            scored_count=0,
            error_count=5,
            with_results=False,
        )
        result = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)["results"][0]

        assert result["mean_score"] is None
        assert result["trust"]["confidence"] == "none"
        assert "not a score of zero" in " ".join(result["trust"]["caveats"])
        assert "failed" in result["trust"]["confidence_reason"]


class TestTrustTell:
    """Verifiable vs subjective, rendered -- the differentiator, tested."""

    def test_a_verifiable_score_says_no_ai_judged_it(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="luna", scored_count=5)
        trust = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)["results"][0]["trust"]

        assert trust["kind"] == "verifiable"
        assert trust["tier_label"] == "Verifiable"
        assert trust["confidence"] == "high"
        assert "No AI judged this score" in trust["headline"]

    def test_thin_evidence_is_labelled_thin_however_good_the_score(self) -> None:
        """Confidence is a claim about the measurement, never about the model."""
        trust = assess(
            kind=TaskKind.VERIFIABLE,
            scorer="numeric_match",
            scorable=True,
            unscorable_reason=None,
            mean_score=1.0,
            scored_count=2,
            sample_count=2,
            error_count=0,
        )
        assert trust.confidence == "low"
        assert "too few samples" in trust.confidence_reason

    def test_a_judged_score_can_never_be_high_confidence(self) -> None:
        """However many samples, the grader is still a language model whose
        agreement with real professors this project has not yet measured."""
        trust = assess(
            kind=TaskKind.SUBJECTIVE,
            scorer="llm_judge",
            scorable=True,
            unscorable_reason=None,
            mean_score=0.99,
            scored_count=500,
            sample_count=500,
            error_count=0,
        )
        assert trust.confidence == "moderate"
        assert trust.tier_label == "Subjective (AI-scored)"
        assert any("not by a professor" in c for c in trust.caveats)

    def test_a_score_is_never_contradicted_by_the_scorable_flag(
        self, client: TestClient, context: AppContext
    ) -> None:
        """REGRESSION. Seen live on the results page.

        A subjective run carrying ``mean_score: 0.86`` rendered the number AND
        the sentence "No score exists for this pair — this is not a score of
        zero", because ``scorable`` was tested before the score. ``scorable`` is
        a property of the task AND THIS DEPLOYMENT (no judge model configured);
        the run's number is a fact that already happened. Context does not get
        to contradict the fact -- it becomes a caveat.
        """
        seed_run(
            context,
            task_id=SUBJECTIVE_TASK,
            model_key="luna",
            mean_score=0.86,
            scored_count=5,
            scorer=ScorerKind.LLM_JUDGE,
        )
        result = board_for(client.get("/leaderboard").json(), SUBJECTIVE_TASK)["results"][0]

        assert result["mean_score"] == 0.86
        assert result["trust"]["confidence"] != "none"
        assert result["trust"]["confidence_label"] != "Not scored"
        assert not any("No score exists" in c for c in result["trust"]["caveats"])
        # ...and the tension is stated rather than hidden.
        assert any("cannot grade this task today" in c for c in result["trust"]["caveats"])
        assert any("would not reproduce it" in c for c in result["trust"]["caveats"])

    def test_not_yet_scorable_says_so_rather_than_showing_nothing(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(
            context,
            task_id=SUBJECTIVE_TASK,
            model_key="luna",
            mean_score=None,
            scored_count=0,
            with_results=False,
        )
        result = board_for(client.get("/leaderboard").json(), SUBJECTIVE_TASK)["results"][0]
        assert result["trust"]["confidence"] == "none"
        assert result["trust"]["confidence_label"] == "Not scored"

    def test_a_partial_run_caveats_the_excluded_samples(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(
            context,
            task_id=VERIFIABLE_TASK,
            model_key="luna",
            status=RunStatus.PARTIAL,
            mean_score=1.0,
            sample_count=10,
            scored_count=6,
            error_count=4,
        )
        trust = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)["results"][0]["trust"]
        assert trust["confidence"] == "moderate"
        assert any("excluded from this average" in c for c in trust["caveats"])


class TestResidency:
    """The FERPA angle, surfaced from the registry rather than typed into a page."""

    def test_campus_models_are_marked_on_campus(self, client: TestClient) -> None:
        entries = {m["key"]: m for m in client.get("/models?include_disabled=true").json()}
        assert "local" in entries["sparks-local"]["tags"]

    def test_residency_is_derived_from_registry_tags(self, context: AppContext) -> None:
        by_key = {e.key: e for e in context.registry.models}
        assert data_residency(by_key["sparks-local"]) == "on_campus"
        assert data_residency(by_key["luna"]) == "third_party"
        assert data_residency(by_key["mock"]) == "not_a_real_model"

    def test_the_row_carries_a_human_readable_residency_label(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="luna")
        result = board_for(client.get("/leaderboard").json(), VERIFIABLE_TASK)["results"][0]
        assert result["data_residency"] == "third_party"
        assert result["data_residency_label"] == "Sends data to a third party"


class TestFilters:
    def test_task_id_filter_narrows_to_one_task(self, client: TestClient) -> None:
        body = client.get(f"/leaderboard?task_id={QUIZ_TASK}").json()
        assert [t["task_id"] for t in body["tasks"]] == [QUIZ_TASK]

    def test_family_filter_uses_the_id_prefix_convention(self, client: TestClient) -> None:
        body = client.get("/leaderboard?family=conceptual-grading").json()
        assert body["task_count"] == 5
        assert all(t["family"] == "conceptual-grading" for t in body["tasks"])

    def test_domain_filter(self, client: TestClient) -> None:
        body = client.get("/leaderboard?domain=assessment").json()
        assert body["task_count"] > 0
        assert all(t["domain"] == "assessment" for t in body["tasks"])

    def test_unknown_filter_value_yields_an_empty_but_valid_board(self, client: TestClient) -> None:
        body = client.get("/leaderboard?family=does-not-exist").json()
        assert body["tasks"] == []
        assert body["has_any_results"] is False

    def test_family_is_the_id_prefix(self, context: AppContext) -> None:
        assert task_family(context.catalog.get(GRADING_TASK)) == "conceptual-grading"


class TestSloAxes:
    """The SLO-benchmark tag contract, as the dashboard consumes it.

    The contract itself lives in ``ida_core.curriculum`` and is enforced by the
    ``task-schema`` CI gate. What these pin is that the dashboard reads it the
    same way -- and, in particular, that it never invents an outcome.
    """

    def test_the_two_axes_and_benchmark_membership_come_off_the_tags(
        self, context: AppContext
    ) -> None:
        spec = context.catalog.get(QUIZ_TASK).model_copy(
            update={
                "tags": [
                    "slo-benchmark",
                    "slo:SLO2",
                    "use-mode:capability",
                    "ladder-l1",
                    "unit-economics",
                ]
            }
        )
        assert task_axes(spec) == ("SLO2", "capability", True)

    def test_a_value_containing_a_colon_survives_the_split(self, context: AppContext) -> None:
        """Split on the FIRST colon -- the rule ida_core.curriculum documents."""
        spec = context.catalog.get(QUIZ_TASK).model_copy(
            update={"tags": ["slo-benchmark", "slo:SLO2:draft", "use-mode:capability"]}
        )
        assert task_axes(spec)[0] == "SLO2:draft"

    def test_two_outcome_tags_group_under_neither(self, context: AppContext) -> None:
        """Ambiguity is not a claim.

        Picking one of two would file a real score under a heading the author
        did not choose. The validator reports it; the dashboard declines to
        guess, which is why `slo_of` returns None rather than `values[0]`.
        """
        spec = context.catalog.get(QUIZ_TASK).model_copy(
            update={"tags": ["slo-benchmark", "slo:SLO2", "slo:SLO9", "use-mode:capability"]}
        )
        assert task_axes(spec)[0] is None

    def test_an_untagged_task_claims_no_outcome(self, context: AppContext) -> None:
        """The exemplar and demo families predate the benchmark and stay clean."""
        assert task_axes(context.catalog.get(QUIZ_TASK)) == (None, None, False)

    def test_the_benchmark_tag_is_one_filter_over_the_whole_benchmark(
        self, client: TestClient
    ) -> None:
        body = client.get("/leaderboard?benchmark=true").json()
        assert all(t["in_benchmark"] for t in body["tasks"])
        assert body["benchmark_task_count"] == len(body["tasks"])

    def test_slo_and_use_mode_filters_are_served(self, client: TestClient) -> None:
        for query in ("slo=SLO2", "use_mode=capability"):
            response = client.get(f"/leaderboard?{query}")
            assert response.status_code == 200
            body = response.json()
            # Whether anything matches depends on whether this checkout carries
            # the SLO task families; either way the shape is valid and nothing
            # is invented.
            assert all(t["slo"] == "SLO2" for t in body["tasks"] if query.startswith("slo="))

    def test_outcome_ids_are_listed_in_curriculum_order_not_alphabetical(self) -> None:
        """SLO10 sorts before SLO2 alphabetically, and that is not the order the
        programme publishes its outcomes in."""
        curriculum = CurriculumView(
            available=True,
            outcomes=[
                OutcomeView(
                    id=f"SLO{n}",
                    title=f"Outcome {n}",
                    statement="...",
                    text_benchmarkable=True,
                    benchmark_note="...",
                )
                for n in (1, 2, 9, 10)
            ],
        )
        boards = [
            TaskLeaderboard(
                task_id=f"t{n}",
                title="t",
                description="d",
                kind=TaskKind.VERIFIABLE,
                domain="statistics",
                scorer="numeric_match",
                family="f",
                slo=slo,
                sample_count=1,
                scorable=True,
                has_results=False,
            )
            for n, slo in enumerate(["SLO10", "SLO2", "SLO1", "SLO-UNKNOWN"])
        ]
        assert _ordered_slos(boards, curriculum) == ["SLO1", "SLO2", "SLO10", "SLO-UNKNOWN"]

    def test_an_id_the_curriculum_does_not_know_is_surfaced_not_dropped(self) -> None:
        """It is a tagging error the CI gate reports. Hiding the row here would
        hide it from the person who has to fix it."""
        curriculum = CurriculumView(available=False, unavailable_reason="none here")
        boards = [
            TaskLeaderboard(
                task_id="t",
                title="t",
                description="d",
                kind=TaskKind.VERIFIABLE,
                domain="statistics",
                scorer="numeric_match",
                family="f",
                slo="SL02",  # a zero, not a letter O — the classic typo
                sample_count=1,
                scorable=True,
                has_results=False,
            )
        ]
        assert _ordered_slos(boards, curriculum) == ["SL02"]


class TestCurriculum:
    """``curriculum/slo.yaml`` is read, never retyped."""

    def test_the_curriculum_is_served_so_no_ui_holds_its_own_copy(self, client: TestClient) -> None:
        response = client.get("/curriculum")
        assert response.status_code == 200
        body = response.json()
        assert "available" in body
        if body["available"]:
            # Real map present: every outcome carries the registrar's wording,
            # and the un-benchmarkable ones are surfaced rather than filtered.
            assert body["outcomes"]
            assert all(o["statement"] for o in body["outcomes"])
            assert any(o["text_benchmarkable"] is False for o in body["outcomes"]), (
                "SLO5 and SLO8 are not text-benchmarkable; a map that hid them "
                "would read as though the programme has seven outcomes"
            )
        else:
            # Absent map: a legitimate state that must carry its reason.
            assert body["unavailable_reason"]
            assert body["outcomes"] == []

    def test_the_leaderboard_carries_the_curriculum_for_the_ui(self, client: TestClient) -> None:
        body = client.get("/leaderboard").json()
        assert body["curriculum"] == client.get("/curriculum").json()

    def test_a_missing_curriculum_never_invents_statements(self) -> None:
        view = CurriculumView(available=False, unavailable_reason="not here")
        assert view.outcomes == []
        assert view.outcome("SLO2") is None

    def test_the_loader_degrades_rather_than_raising_on_a_bad_path(self, tmp_path) -> None:
        """A malformed or missing map is `make lint-tasks`'s problem to fail a PR
        over. Taking the results page down would swap a visible data error for an
        invisible outage."""
        view = load_curriculum_view(tmp_path)
        assert view.available is False
        assert view.unavailable_reason
