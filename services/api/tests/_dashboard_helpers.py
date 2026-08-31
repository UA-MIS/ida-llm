"""Seeding helpers for the dashboard tests.

Real rows through the real repositories -- the leaderboard's whole job is to
aggregate what the database holds, so a fake row source would test the fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ida_api.deps import AppContext
from ida_core.contracts import (
    ResultRecord,
    RunRecord,
    RunStatus,
    Score,
    ScorerKind,
    ServingConfig,
    ServingStack,
    TokenUsage,
)
from ida_core.db import session_scope
from ida_core.ids import new_result_id, new_run_id
from ida_core.repositories import create_run, insert_results

VERIFIABLE_TASK = "demo/arithmetic-quiz-check"
SUBJECTIVE_TASK = "demo/essay-feedback"
QUIZ_TASK = "quantitative-quiz/l1-descriptive-key"
GRADING_TASK = "conceptual-grading/l1-key-point-coverage"

BASE_TIME = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def seed_run(
    context: AppContext,
    *,
    task_id: str,
    model_key: str,
    status: RunStatus = RunStatus.SUCCEEDED,
    mean_score: float | None = 0.9,
    sample_count: int = 5,
    scored_count: int = 5,
    error_count: int = 0,
    created_offset_minutes: int = 0,
    with_results: bool = True,
    scorer: ScorerKind = ScorerKind.NUMERIC_MATCH,
    harness_version: str = "0.1.0",
    serving_extra: dict[str, object] | None = None,
) -> str:
    """Write one run (and, by default, one result) and return its id."""
    run_id = new_run_id()
    serving = ServingConfig(
        model_id=f"{model_key}-under-test",
        registry_key=model_key,
        serving_stack=ServingStack.MOCK,
        extra=dict(serving_extra or {}),
    )
    created = BASE_TIME + timedelta(minutes=created_offset_minutes)
    with session_scope(context.session_factory) as session:
        create_run(
            session,
            RunRecord(
                id=run_id,
                status=status,
                task_id=task_id,
                model_key=model_key,
                harness_version=harness_version,
                serving_config=serving,
                sample_count=sample_count,
                scored_count=scored_count,
                error_count=error_count,
                mean_score=mean_score,
                total_usage=TokenUsage(prompt_tokens=100, completion_tokens=20),
                total_cost_usd=0.0,
                created_at=created,
                started_at=created,
                finished_at=created + timedelta(seconds=30),
            ),
        )
        if with_results:
            insert_results(
                session,
                [
                    ResultRecord(
                        id=new_result_id(),
                        run_id=run_id,
                        task_id=task_id,
                        sample_id="sample-1",
                        model_key=model_key,
                        serving_config=serving,
                        score=(
                            None
                            if mean_score is None
                            else Score(
                                scorer=scorer,
                                value=mean_score,
                                passed=mean_score >= 0.5,
                                explanation="seeded",
                            )
                        ),
                        scorable=mean_score is not None,
                        usage=TokenUsage(prompt_tokens=20, completion_tokens=4),
                        transcript_uri=f"s3://ida-artifacts/runs/{run_id}/transcripts/sample-1.json",
                    )
                ],
            )
    return run_id


COMPLETE_TEACHING_ANSWERS = {
    "role": "teacher",
    "beneficiary": "for_me",
    "teaching_task": "quiz_generation",
    "student_data": "no",
    "subject_level": "intro_undergrad",
    "stakes": "medium",
    "budget": "modest_paid",
}
"""Every applicable required question answered, with nothing that hard-filters.

The FERPA branch is deliberately not triggered (``student_data: no``), so this
is the baseline a test can perturb one answer at a time.
"""
