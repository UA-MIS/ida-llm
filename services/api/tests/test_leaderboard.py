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
from ida_api.leaderboard import data_residency, task_facets, task_family
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


class TestFiltersAndFacets:
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

    def test_slo_and_use_mode_facets_are_read_from_prefixed_tags(self, context: AppContext) -> None:
        """No task carries these tags today.

        The facet reader is written against the tag convention so that tagging a
        task file is the ONLY step needed to make per-SLO and per-use-mode
        grouping appear -- the same "adding a class is a YAML edit" property the
        curriculum-map plan depends on.
        """
        spec = context.catalog.get(QUIZ_TASK).model_copy(
            update={
                "tags": [
                    "quantitative-quiz",
                    "slo:mis200-3",
                    "use-mode:professor-assist",
                    "audience:teacher",
                    "not-a-facet",
                    "malformed:",
                ]
            }
        )
        assert task_facets(spec) == {
            "slo": ["mis200-3"],
            "use_mode": ["professor-assist"],
            "audience": ["teacher"],
        }

    def test_facet_filters_match_nothing_until_tasks_are_tagged(self, client: TestClient) -> None:
        body = client.get("/leaderboard?use_mode=professor-assist").json()
        assert body["tasks"] == []
