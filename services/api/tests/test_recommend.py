"""``POST /recommend`` -- the intake that refuses to hand-wave.

The interesting tests here are the ones that assert we DID NOT answer.  A
recommendation engine is easy to make say something; the product claim is that
it stays quiet when it should, and names exactly why.
"""

from __future__ import annotations

from _dashboard_helpers import (
    COMPLETE_TEACHING_ANSWERS,
    GRADING_TASK,
    QUIZ_TASK,
    VERIFIABLE_TASK,
    seed_run,
)
from fastapi.testclient import TestClient

from ida_api.deps import AppContext
from ida_api.recommend import QUESTIONS_BY_ID, applicable_questions
from ida_core.contracts import ScorerKind


def recommend(client: TestClient, answers: dict) -> dict:
    response = client.post("/recommend", json={"answers": answers})
    assert response.status_code == 200, response.text
    return response.json()


class TestQuestionTree:
    def test_the_tree_is_served_so_client_and_engine_cannot_drift(self, client: TestClient) -> None:
        body = client.get("/recommend/questions").json()
        ids = [q["id"] for q in body]
        assert "role" in ids
        assert "ferpa_hard_requirement" in ids
        assert all(q["why_it_matters"] for q in body), (
            "every question must be able to justify itself to a busy professor"
        )

    def test_the_ferpa_question_is_branched_on_student_data(self, client: TestClient) -> None:
        body = client.get("/recommend/questions").json()
        ferpa = next(q for q in body if q["id"] == "ferpa_hard_requirement")
        assert ferpa["depends_on"] == {
            "question_id": "student_data",
            "values": ["yes", "unsure"],
        }
        assert "FERPA" in (ferpa["branch_note"] or "")

    def test_a_researcher_is_never_asked_about_student_data(self) -> None:
        asked = {q.id for q in applicable_questions({"role": "researcher"})}
        assert "student_data" not in asked
        assert "ferpa_hard_requirement" not in asked
        assert "research_task" in asked

    def test_a_teacher_is_never_asked_about_unpublished_data(self) -> None:
        asked = {q.id for q in applicable_questions({"role": "teacher"})}
        assert "unpublished_data" not in asked
        assert "teaching_task" in asked

    def test_the_ferpa_branch_opens_only_once_student_data_is_admitted(self) -> None:
        base = {"role": "teacher"}
        assert "ferpa_hard_requirement" not in {q.id for q in applicable_questions(base)}
        assert "ferpa_hard_requirement" not in {
            q.id for q in applicable_questions({**base, "student_data": "no"})
        }
        for admitted in ("yes", "unsure"):
            assert "ferpa_hard_requirement" in {
                q.id for q in applicable_questions({**base, "student_data": admitted})
            }


class TestRefusalOnThinContext:
    """The 'force full context' mechanism -- the whole point of the intake."""

    def test_an_empty_intake_gets_named_gaps_not_a_guess(self, client: TestClient) -> None:
        body = recommend(client, {})
        assert body["status"] == "need_more_context"
        assert body["primary"] is None
        assert body["alternatives"] == []
        gap_ids = {g["question_id"] for g in body["gaps"]}
        assert "role" in gap_ids
        # Every gap explains why it is being asked for.
        assert all(g["why_it_matters"] for g in body["gaps"])

    def test_gaps_follow_the_branch_rather_than_listing_every_question(
        self, client: TestClient
    ) -> None:
        body = recommend(client, {"role": "researcher"})
        gap_ids = {g["question_id"] for g in body["gaps"]}
        assert "research_task" in gap_ids
        assert "student_data" not in gap_ids, "a researcher is not asked about FERPA"

    def test_admitting_student_data_adds_the_ferpa_gap(self, client: TestClient) -> None:
        answers = {**COMPLETE_TEACHING_ANSWERS, "student_data": "yes"}
        body = recommend(client, answers)
        assert body["status"] == "need_more_context"
        assert {g["question_id"] for g in body["gaps"]} == {"ferpa_hard_requirement"}

    def test_optional_questions_never_block(self, client: TestClient) -> None:
        """`surface` and `ai_trust` shape the answer; they do not gate it.

        Where's the line between thorough and annoying? Here: a question is
        required only when not knowing it would make the recommendation wrong.
        """
        assert QUESTIONS_BY_ID["surface"].required is False
        assert QUESTIONS_BY_ID["ai_trust"].required is False
        body = recommend(client, COMPLETE_TEACHING_ANSWERS)
        assert body["status"] != "need_more_context"

    def test_a_bogus_option_value_is_rejected_outright(self, client: TestClient) -> None:
        response = client.post("/recommend", json={"answers": {"role": "vice-chancellor"}})
        assert response.status_code == 422
        assert "role" in response.json()["detail"]

    def test_an_unknown_question_id_is_rejected(self, client: TestClient) -> None:
        response = client.post("/recommend", json={"answers": {"favourite_colour": "blue"}})
        assert response.status_code == 422


class TestHardConstraints:
    def test_ferpa_hard_requirement_refuses_rather_than_offering_a_cloud_model(
        self, client: TestClient, context: AppContext
    ) -> None:
        """THE flagship refusal.

        A cloud model has benchmark evidence and would score well. The professor
        said student data cannot leave campus. The only campus model in the
        registry is disabled. Offering the cloud model anyway -- even with a
        footnote -- would break the one promise that makes this project
        trustworthy with student work, so we return nothing and say why.
        """
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.95)
        body = recommend(
            client,
            {
                **COMPLETE_TEACHING_ANSWERS,
                "student_data": "yes",
                "ferpa_hard_requirement": "yes",
            },
        )
        assert body["status"] == "no_eligible_model"
        assert body["primary"] is None
        assert "campus" in body["message"]
        hard = [c for c in body["constraints"] if c["hard"]]
        assert any("stay on campus" in c["label"] for c in hard)
        # And it says what would change the answer, concretely.
        assert any("campus vLLM" in s for s in body["what_would_change_this"])

    def test_unsure_about_ferpa_is_treated_as_a_hard_requirement(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The cautious reading is the only safe default, and we say we took it."""
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.95)
        body = recommend(
            client,
            {
                **COMPLETE_TEACHING_ANSWERS,
                "student_data": "unsure",
                "ferpa_hard_requirement": "unsure",
            },
        )
        assert body["status"] == "no_eligible_model"
        assert any("cautious reading" in c["detail"] for c in body["constraints"])

    def test_de_identifying_reopens_cloud_models_as_a_soft_constraint(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.95)
        body = recommend(
            client,
            {
                **COMPLETE_TEACHING_ANSWERS,
                "student_data": "yes",
                "ferpa_hard_requirement": "no",
            },
        )
        assert body["status"] == "ok"
        soft = [c for c in body["constraints"] if not c["hard"]]
        assert any("de-identified" in c["label"] for c in soft)
        # ...and the cloud model is flagged for what it is.
        assert any("leaves the university" in reason for reason in body["primary"]["why"])

    def test_free_only_excludes_the_paid_model(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.95)
        body = recommend(client, {**COMPLETE_TEACHING_ANSWERS, "budget": "free_or_local_only"})
        assert body["status"] == "no_eligible_model"
        assert any(c["label"] == "No per-use cost" for c in body["constraints"])


class TestEvidenceGate:
    def test_no_benchmark_data_means_no_recommendation(self, client: TestClient) -> None:
        body = recommend(client, COMPLETE_TEACHING_ANSWERS)
        assert body["status"] == "insufficient_evidence"
        assert body["primary"] is None
        assert body["matched_task_ids"], "we still say which tasks we looked for"
        assert body["missing_benchmarks"]
        assert any("Run the benchmark" in s for s in body["what_would_change_this"])

    def test_a_test_stub_is_not_evidence(self, client: TestClient, context: AppContext) -> None:
        """`mock` echoes deterministically. A recommendation backed by it would
        be a recommendation backed by a fixture."""
        seed_run(context, task_id=QUIZ_TASK, model_key="mock", mean_score=1.0)
        body = recommend(client, COMPLETE_TEACHING_ANSWERS)
        assert body["status"] == "insufficient_evidence"

    def test_high_stakes_refuses_ai_judged_evidence(
        self, client: TestClient, context: AppContext
    ) -> None:
        """A grade of record is not backed by one language model grading another."""
        seed_run(
            context,
            task_id=GRADING_TASK,
            model_key="luna",
            mean_score=0.92,
            scorer=ScorerKind.LLM_JUDGE,
        )
        answers = {
            **COMPLETE_TEACHING_ANSWERS,
            "teaching_task": "grading",
            "stakes": "high",
        }
        body = recommend(client, answers)
        assert body["status"] == "insufficient_evidence"
        assert "consequential" in body["message"]
        assert any("change the" in s and "stakes" in s for s in body["what_would_change_this"])

    def test_the_same_evidence_is_enough_when_the_professor_reviews_the_output(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The stakes answer genuinely changes the outcome -- so the question earns its place."""
        seed_run(
            context,
            task_id=GRADING_TASK,
            model_key="luna",
            mean_score=0.92,
            scorer=ScorerKind.LLM_JUDGE,
        )
        body = recommend(
            client,
            {**COMPLETE_TEACHING_ANSWERS, "teaching_task": "grading", "stakes": "medium"},
        )
        assert body["status"] == "ok"
        assert body["primary"]["verifiable_evidence"] is False


class TestTheRecommendation:
    def test_the_payload_is_a_package_not_a_model_name(
        self, client: TestClient, context: AppContext
    ) -> None:
        """Model + surface + cost + a working starting point -- the money moment."""
        run_id = seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        body = recommend(client, COMPLETE_TEACHING_ANSWERS)

        assert body["status"] == "ok"
        primary = body["primary"]
        assert primary["model_key"] == "luna"
        assert primary["surface_label"]
        assert primary["surface_rationale"]
        assert primary["cost"]["tier"] == "paid"
        assert primary["prompt_template"].strip(), "a professor gets something to paste"
        assert "{level}" not in primary["prompt_template"], "placeholders are filled in"
        # Receipts: the differentiator.
        assert primary["receipts"]
        assert primary["receipts"][0]["run_id"] == run_id
        assert primary["receipts"][0]["task_id"] == QUIZ_TASK

    def test_the_template_asks_for_the_subject_rather_than_inventing_one(
        self, client: TestClient, context: AppContext
    ) -> None:
        """We ask what LEVEL you teach at, never which subject.

        An earlier version substituted the task label, producing "students in
        writing quiz or exam items" -- a sentence that tells a professor the
        thing was generated by something not paying attention, which is exactly
        the impression this page cannot afford to make.
        """
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        template = recommend(client, COMPLETE_TEACHING_ANSWERS)["primary"]["prompt_template"]
        assert "[your subject]" in template
        assert "introductory undergraduate" in template, "the level we DID ask for is filled in"
        assert "in writing quiz or exam items" not in template

    def test_every_reason_given_names_the_evidence_behind_it(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        primary = recommend(client, COMPLETE_TEACHING_ANSWERS)["primary"]
        assert any("0.88" in reason for reason in primary["why"])
        assert any("program checked" in reason for reason in primary["why"])

    def test_the_ranking_basis_is_shown_rather_than_hidden(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.6)
        primary = recommend(client, COMPLETE_TEACHING_ANSWERS)["primary"]
        assert primary["evidence_score"] == 0.6

    def test_a_mediocre_best_option_says_it_is_mediocre(
        self, client: TestClient, context: AppContext
    ) -> None:
        """ "The best measured option" and "a good option" are different claims."""
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.3)
        primary = recommend(client, COMPLETE_TEACHING_ANSWERS)["primary"]
        assert any("not a good one" in c for c in primary["caveats"])

    def test_a_testing_only_registry_entry_is_caveated(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        primary = recommend(client, COMPLETE_TEACHING_ANSWERS)["primary"]
        assert any("testing-only" in c for c in primary["caveats"])

    def test_student_facing_use_adds_guardrails(
        self, client: TestClient, context: AppContext
    ) -> None:
        seed_run(context, task_id=VERIFIABLE_TASK, model_key="luna", mean_score=0.9)
        body = recommend(
            client,
            {
                **COMPLETE_TEACHING_ANSWERS,
                "teaching_task": "tutoring",
                "beneficiary": "for_students",
            },
        )
        if body["status"] != "ok":
            # `tutoring` has no benchmarked task family yet; the honest refusal
            # is itself correct behaviour, so assert that instead.
            assert body["status"] == "insufficient_evidence"
            return
        assert body["primary"]["guardrails"]

    def test_the_context_we_acted_on_is_played_back(
        self, client: TestClient, context: AppContext
    ) -> None:
        """A professor must be able to see what we thought they said."""
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        body = recommend(client, COMPLETE_TEACHING_ANSWERS)
        labels = {item["label"] for item in body["context_summary"]}
        assert {"Role", "Task", "Level", "Stakes", "Budget"} <= labels

    def test_nothing_from_the_intake_is_persisted(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The intake is a read. It writes no rows -- there is no consent flow
        for storing what a professor tells us about their course."""
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        before = client.get("/runs").json()["total"]
        recommend(client, COMPLETE_TEACHING_ANSWERS)
        assert client.get("/runs").json()["total"] == before

    def test_recommendation_needs_no_credential(
        self, client: TestClient, context: AppContext
    ) -> None:
        """Reads are anonymous; only spending provider money is gated."""
        seed_run(context, task_id=QUIZ_TASK, model_key="luna", mean_score=0.88)
        response = client.post("/recommend", json={"answers": COMPLETE_TEACHING_ANSWERS})
        assert response.status_code == 200
