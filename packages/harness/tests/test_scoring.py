"""Scorer behaviour, including the rules from the module docstring:
a bad completion scores 0, it does not raise.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ida_core.contracts import Normalisation, ScorerKind, ScorerSpec
from ida_harness.errors import ScoringError
from ida_harness.scoring import (
    ExactMatchScorer,
    LLMJudgeScorer,
    NumericMatchScorer,
    build_scorer,
    extract_number,
    normalise,
)


class TestNormalise:
    def test_defaults_strip_and_collapse(self) -> None:
        assert normalise("  a   b  ", Normalisation()) == "a b"

    def test_nothing_happens_when_all_rules_off(self) -> None:
        rules = Normalisation(strip=False, collapse_whitespace=False)
        assert normalise("  a   b  ", rules) == "  a   b  "

    def test_take_last_line_skips_blank_lines(self) -> None:
        rules = Normalisation(take_last_line=True)
        assert normalise("thinking...\n\n42\n\n", rules) == "42"

    def test_take_last_line_on_empty_input(self) -> None:
        assert normalise("\n\n  \n", Normalisation(take_last_line=True)) == ""

    def test_lowercase(self) -> None:
        assert normalise("ABC", Normalisation(lowercase=True)) == "abc"

    def test_strip_punctuation_then_recollapses(self) -> None:
        rules = Normalisation(strip_punctuation=True)
        assert normalise("Hello, world!", rules) == "Hello world"

    def test_documented_order_is_honoured(self) -> None:
        """take_last_line runs FIRST -- that is what makes chain-of-thought gradable."""
        rules = Normalisation(take_last_line=True, lowercase=True, strip_punctuation=True)
        assert normalise("Step 1: think.\nThe Answer Is: FORTY-TWO!", rules) == (
            "the answer is fortytwo"
        )


class TestExtractNumber:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("42", 42.0),
            ("-11", -11.0),
            ("3.5", 3.5),
            ("1,234", 1234.0),
            ("1,234,567.89", 1234567.89),
            ("1e3", 1000.0),
            ("-2.5e-2", -0.025),
            ("The answer is 42.", 42.0),
            ("17 plus 25 is 42", 42.0),
            ("no digits at all", None),
            ("", None),
        ],
    )
    def test_cases(self, text: str, expected: float | None) -> None:
        assert extract_number(text) == expected

    def test_takes_the_last_number_not_the_first(self) -> None:
        """Models restate the question; the first number is usually an input."""
        assert extract_number("What is 17 + 25? It is 42.") == 42.0


class TestExactMatch:
    def _scorer(self, **kwargs) -> ExactMatchScorer:
        return ExactMatchScorer(ScorerSpec(kind=ScorerKind.EXACT_MATCH, **kwargs))

    def test_match(self) -> None:
        score = self._scorer().score("Paris", "Paris")
        assert score.passed and score.value == 1.0
        assert score.scorer is ScorerKind.EXACT_MATCH

    def test_mismatch_is_zero_not_partial(self) -> None:
        score = self._scorer().score("Paris, France", "Paris")
        assert not score.passed and score.value == 0.0

    def test_explanation_shows_both_sides(self) -> None:
        score = self._scorer().score("Lyon", "Paris")
        assert "Lyon" in score.explanation and "Paris" in score.explanation

    def test_case_sensitive_unless_task_opts_out(self) -> None:
        assert not self._scorer().score("paris", "Paris").passed
        opted_in = self._scorer(normalisation=Normalisation(lowercase=True))
        assert opted_in.score("paris", "Paris").passed

    def test_details_carry_the_normalised_values(self) -> None:
        score = self._scorer().score("  Paris  ", "Paris")
        assert score.details == {"normalised_completion": "Paris", "normalised_target": "Paris"}

    def test_missing_target_is_a_programming_error(self) -> None:
        with pytest.raises(ScoringError, match="requires a target"):
            self._scorer().score("x", None)


class TestNumericMatch:
    def _scorer(self, **kwargs) -> NumericMatchScorer:
        return NumericMatchScorer(ScorerSpec(kind=ScorerKind.NUMERIC_MATCH, **kwargs))

    def test_exact_by_default(self) -> None:
        assert self._scorer().score("42", "42").passed
        assert not self._scorer().score("42.0001", "42").passed

    def test_absolute_tolerance(self) -> None:
        assert self._scorer(tolerance=0.001).score("42.0005", "42").passed

    def test_relative_tolerance(self) -> None:
        assert self._scorer(relative_tolerance=0.01).score("101", "100").passed
        assert not self._scorer(relative_tolerance=0.001).score("101", "100").passed

    def test_either_tolerance_suffices(self) -> None:
        scorer = self._scorer(tolerance=5.0, relative_tolerance=0.0)
        assert scorer.score("104", "100").passed

    def test_negative_and_decimal_answers(self) -> None:
        assert self._scorer().score("-11", "-11").passed
        assert self._scorer(tolerance=1e-9).score("3.5", "3.5").passed

    def test_chain_of_thought_with_last_line_normalisation(self) -> None:
        scorer = self._scorer(normalisation=Normalisation(take_last_line=True))
        assert scorer.score("17 + 25\nLet me add.\n42", "42").passed

    def test_no_number_scores_zero_and_does_not_raise(self) -> None:
        """Rule 1: a model failure is a zero with an explanation, not an exception."""
        score = self._scorer().score("I don't know.", "42")
        assert score.value == 0.0 and not score.passed
        assert "no number found" in score.explanation
        assert score.details["extracted"] is None

    def test_explanation_reports_delta_and_allowance(self) -> None:
        score = self._scorer(tolerance=0.5).score("43", "42")
        assert "delta" in score.explanation and "allowed" in score.explanation

    def test_non_numeric_target_is_a_task_authoring_error(self) -> None:
        with pytest.raises(ScoringError, match="contains no number"):
            self._scorer().score("42", "forty-two")

    def test_missing_target_is_a_programming_error(self) -> None:
        with pytest.raises(ScoringError, match="requires a target"):
            self._scorer().score("42", None)


class TestLLMJudgeScorer:
    def test_is_registered_but_not_implemented(self) -> None:
        """The interface exists so subjective tasks validate; calling it must be loud."""
        scorer = build_scorer(ScorerSpec(kind=ScorerKind.LLM_JUDGE, rubric_id="r"))
        assert isinstance(scorer, LLMJudgeScorer)
        with pytest.raises(NotImplementedError, match="walking skeleton"):
            scorer.score("some feedback", None)


class TestBuildScorer:
    @pytest.mark.parametrize(
        "kind,expected",
        [
            (ScorerKind.EXACT_MATCH, ExactMatchScorer),
            (ScorerKind.NUMERIC_MATCH, NumericMatchScorer),
            (ScorerKind.LLM_JUDGE, LLMJudgeScorer),
        ],
    )
    def test_every_kind_is_constructible(self, kind, expected) -> None:
        spec = ScorerSpec(kind=kind, rubric_id="r" if kind is ScorerKind.LLM_JUDGE else None)
        assert isinstance(build_scorer(spec), expected)

    def test_scorers_satisfy_the_protocol(self) -> None:
        from ida_harness.scoring import Scorer

        assert isinstance(build_scorer(ScorerSpec(kind=ScorerKind.EXACT_MATCH)), Scorer)


class TestNumericMatchNormalisationSafety:
    """B3 — normalisation must never turn a correct numeric answer into a wrong one.

    Reproduced before the fix: with ``strip_punctuation: true``, ``"3.5"`` vs
    ``"3.5"`` scored 0.0 ("got 35.0, want 3.5"), because ``string.punctuation``
    contains ``.`` and ``,`` and only the *completion* was normalised. Silent
    benchmark-data corruption: no error, the model just looked worse than it was.

    Two independent guards now, so neither alone has to be perfect:
      1. ``ScorerSpec`` refuses the flag for numeric scorers at validation time;
      2. the scorer normalises both sides identically, like ExactMatchScorer.
    """

    def test_strip_punctuation_is_refused_for_numeric_scorers(self) -> None:
        with pytest.raises(ValidationError, match="numerically significant"):
            ScorerSpec(
                kind=ScorerKind.NUMERIC_MATCH,
                normalisation=Normalisation(strip_punctuation=True),
            )

    def test_the_rejection_names_a_remedy(self) -> None:
        """A validation error a task author cannot act on is only half useful."""
        with pytest.raises(ValidationError) as exc:
            ScorerSpec(
                kind=ScorerKind.NUMERIC_MATCH,
                normalisation=Normalisation(strip_punctuation=True),
            )
        assert "exact_match" in str(exc.value)

    def test_exact_match_may_still_strip_punctuation(self) -> None:
        """The flag is only dangerous for numeric comparison; do not over-ban it."""
        spec = ScorerSpec(
            kind=ScorerKind.EXACT_MATCH, normalisation=Normalisation(strip_punctuation=True)
        )
        assert build_scorer(spec).score("Paris.", "Paris").passed

    @pytest.mark.parametrize("answer", ["3.5", "1,234.5", "-11", "42", "0.001", "-2.5"])
    @pytest.mark.parametrize(
        "rules",
        [
            Normalisation(),
            Normalisation(take_last_line=True),
            Normalisation(lowercase=True),
            Normalisation(strip=True, collapse_whitespace=True),
            Normalisation(take_last_line=True, lowercase=True, collapse_whitespace=True),
        ],
        ids=["default", "last-line", "lowercase", "strip-collapse", "combined"],
    )
    def test_a_correct_answer_always_scores_one(self, answer: str, rules: Normalisation) -> None:
        """The invariant the asymmetry broke: completion == target must pass,
        under every normalisation combination a task may legally configure."""
        scorer = build_scorer(ScorerSpec(kind=ScorerKind.NUMERIC_MATCH, normalisation=rules))
        score = scorer.score(answer, answer)
        assert score.value == 1.0, f"{answer!r} under {rules!r} -> {score.explanation}"
        assert score.passed is True

    @pytest.mark.parametrize(
        "completion,target",
        [
            ("The answer is 1,234.5", "1234.5"),
            ("Let me think.\n3.5", "3.5"),
            ("  -11  ", "-11"),
        ],
    )
    def test_realistic_formatting_differences_still_match(
        self, completion: str, target: str
    ) -> None:
        scorer = build_scorer(
            ScorerSpec(
                kind=ScorerKind.NUMERIC_MATCH,
                normalisation=Normalisation(take_last_line=True),
            )
        )
        assert scorer.score(completion, target).passed is True

    def test_the_target_is_normalised_too_not_just_the_completion(self) -> None:
        """The asymmetry itself: a rule that changes the target must be applied to it."""
        scorer = build_scorer(
            ScorerSpec(
                kind=ScorerKind.NUMERIC_MATCH,
                normalisation=Normalisation(take_last_line=True),
            )
        )
        # `take_last_line` must pick 7 from BOTH sides. Un-normalised, the target
        # would yield 99 (extract_number takes the last number in the whole text).
        assert scorer.score("scratch 1\n7", "ignore 99\n7").passed is True

    def test_a_genuinely_wrong_answer_still_fails(self) -> None:
        """Symmetry must not become 'everything passes'."""
        scorer = build_scorer(ScorerSpec(kind=ScorerKind.NUMERIC_MATCH))
        assert scorer.score("35", "3.5").passed is False


class TestScoringErrorIsReachable:
    """A9 — the documented error taxonomy must actually be raised."""

    def test_missing_target_raises_scoring_error(self) -> None:
        scorer = build_scorer(ScorerSpec(kind=ScorerKind.EXACT_MATCH))
        with pytest.raises(ScoringError, match="requires a target"):
            scorer.score("x", None)

    def test_non_numeric_target_raises_scoring_error(self) -> None:
        scorer = build_scorer(ScorerSpec(kind=ScorerKind.NUMERIC_MATCH))
        with pytest.raises(ScoringError, match="contains no number"):
            scorer.score("42", "forty-two")

    def test_unknown_scorer_kind_raises_scoring_error(self) -> None:
        spec = ScorerSpec(kind=ScorerKind.EXACT_MATCH)
        object.__setattr__(spec, "kind", "telepathy")
        with pytest.raises(ScoringError, match="no scorer registered"):
            build_scorer(spec)

    def test_it_is_a_harness_error(self) -> None:
        """`except HarnessError` must catch it, or the taxonomy is decorative."""
        from ida_harness.errors import HarnessError

        assert issubclass(ScoringError, HarnessError)


class TestScoreContract:
    """B6 — `passed` is now optional, because graded scorers make no binary claim."""

    def test_programmatic_scorers_still_set_passed(self) -> None:
        assert build_scorer(ScorerSpec(kind=ScorerKind.EXACT_MATCH)).score("a", "a").passed is True

    def test_passed_may_be_none(self) -> None:
        """A rubric-weighted 0.62 is not a pass or a fail; forcing one invents a cutoff."""
        from ida_core.contracts import Score

        score = Score(scorer=ScorerKind.LLM_JUDGE, value=0.62)
        assert score.passed is None

    def test_criteria_default_empty_and_accept_a_breakdown(self) -> None:
        from ida_core.contracts import CriterionScore, Score

        score = Score(scorer=ScorerKind.EXACT_MATCH, value=1.0, passed=True)
        assert score.criteria == []
        judged = Score(
            scorer=ScorerKind.LLM_JUDGE,
            value=0.62,
            criteria=[
                CriterionScore(name="specificity", value=0.4, weight=2.0),
                CriterionScore(name="tone", value=0.9),
            ],
        )
        assert [c.name for c in judged.criteria] == ["specificity", "tone"]
