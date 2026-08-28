"""Invariants of the SLO 3 and SLO 4 benchmark task families.

These tests guard the conventions that a *dashboard* depends on and that
``make lint-tasks`` cannot see. The validator checks that each file is a legal
task; what it cannot check is that the SLO families agree with each other about
how an outcome is tagged, that a ladder's rungs are numbered consistently with
their filenames, or that a rubric's anchors are behavioural rather than
adjectival.

Scope note, deliberately narrow: every test here is parameterised over the two
family prefixes owned by this file (``slo3-``/``slo4-`` for SLO 3 and SLO 4).
Other SLO families are authored separately and may land in the same tree; these
tests must not fail when they do, and must not silently start asserting things
about them either. ``test_tags.py``-style whole-tree assertions are avoided for
the reason given in ``test_tasks.py::test_indexes_the_shipped_tasks``: an
exact-list assertion fails on every new task file and teaches contributors to
edit the assertion instead of reading it.
"""

from __future__ import annotations

import re

import pytest

from ida_core.config import repo_root
from ida_harness.tasks import TaskCatalog

# The two outcomes this file owns, and the id prefix each family uses.
SLO3_VERIFIABLE = "slo3-global-knowledge/"
SLO3_SUBJECTIVE = "slo3-global-analysis/"
SLO4_SUBJECTIVE = "slo4-cultural-societal/"

FAMILIES = {
    SLO3_VERIFIABLE: ("SLO3", "verifiable"),
    SLO3_SUBJECTIVE: ("SLO3", "subjective"),
    SLO4_SUBJECTIVE: ("SLO4", "subjective"),
}

# Tag convention. `slo:` groups an outcome across the families that implement
# it -- SLO 3 needs two families because SCHEMA.md requires one kind per family,
# and only the tag reunites them. `use_mode:` marks what the task is measuring.
SLO_TAG = re.compile(r"^slo:SLO\d+$")
USE_MODE_TAG = "use_mode:capability"

# `l3-weighing-competing-factors` -> rung 3. Enforced against the `ladder-l3`
# tag so the id and the machine-readable rung cannot drift apart.
RUNG_IN_ID = re.compile(r"^l(\d+)-")


@pytest.fixture(scope="module")
def catalog() -> TaskCatalog:
    return TaskCatalog.from_directory(repo_root() / "tasks")


@pytest.fixture(scope="module")
def slo_tasks(catalog: TaskCatalog) -> list:
    tasks = [t for t in catalog.all() if any(t.id.startswith(p) for p in FAMILIES)]
    assert tasks, "no SLO 3/4 tasks found -- the families are missing, not merely broken"
    return tasks


def _family_of(task) -> str:
    return next(p for p in FAMILIES if task.id.startswith(p))


class TestTagConvention:
    """The tags a dashboard groups on. Nothing else in the repo enforces these.

    The task JSON Schema sets ``additionalProperties: false``, so `slo` and
    `use_mode` cannot be top-level YAML keys; `tags` (a list of strings, exposed
    by the API) is where this convention has to live.
    """

    def test_every_task_carries_exactly_one_slo_tag(self, slo_tasks) -> None:
        for task in slo_tasks:
            slo_tags = [t for t in task.tags if SLO_TAG.match(t)]
            assert len(slo_tags) == 1, f"{task.id} has slo tags {slo_tags}, want exactly one"

    def test_slo_tag_matches_the_family(self, slo_tasks) -> None:
        """A task filed under slo4-* must not be tagged SLO3, or grouping lies."""
        for task in slo_tasks:
            expected_slo, _ = FAMILIES[_family_of(task)]
            assert f"slo:{expected_slo}" in task.tags, f"{task.id} is missing slo:{expected_slo}"

    def test_every_task_declares_its_use_mode(self, slo_tasks) -> None:
        for task in slo_tasks:
            assert USE_MODE_TAG in task.tags, f"{task.id} is missing {USE_MODE_TAG}"

    def test_family_name_is_a_tag(self, slo_tasks) -> None:
        """SCHEMA.md: tag every task in a family with the family name."""
        for task in slo_tasks:
            family = _family_of(task).rstrip("/")
            assert family in task.tags, f"{task.id} is missing its family tag {family!r}"


class TestLadderStructure:
    def test_rung_in_the_id_matches_the_rung_in_the_tags(self, slo_tasks) -> None:
        """SCHEMA.md asks for the rung in the id *and* in tags; they must agree."""
        for task in slo_tasks:
            leaf = task.id.split("/", 1)[1]
            match = RUNG_IN_ID.match(leaf)
            assert match, f"{task.id} does not begin with a rung number (l1-, l2-, ...)"
            assert f"ladder-l{match.group(1)}" in task.tags, (
                f"{task.id} is tagged {[t for t in task.tags if t.startswith('ladder-')]}, "
                f"which does not match its id"
            )

    def test_rungs_are_contiguous_from_one(self, slo_tasks) -> None:
        """A ladder missing a rung is a ladder whose ordering cannot be read."""
        for prefix in FAMILIES:
            rungs = sorted(
                int(RUNG_IN_ID.match(t.id.split("/", 1)[1]).group(1))
                for t in slo_tasks
                if t.id.startswith(prefix)
            )
            assert rungs == list(range(1, len(rungs) + 1)), f"{prefix} rungs are {rungs}"

    def test_filename_matches_the_id(self, catalog: TaskCatalog, slo_tasks) -> None:
        """A reviewer tracing a failing result to its file should not have to grep."""
        for task in slo_tasks:
            expected = task.id.split("/", 1)[1] + ".yaml"
            assert catalog.source_of(task.id).name == expected, (
                f"{task.id} lives in {catalog.source_of(task.id).name}, expected {expected}"
            )

    def test_one_kind_per_family(self, slo_tasks) -> None:
        """SCHEMA.md: a family that mixes kinds is two families sharing a directory.

        This is why SLO 3 is two directories rather than one.
        """
        for prefix, (_, expected_kind) in FAMILIES.items():
            kinds = {t.kind.value for t in slo_tasks if t.id.startswith(prefix)}
            assert kinds == {expected_kind}, f"{prefix} contains kinds {kinds}"

    def test_the_verifiable_ladder_shares_one_system_prompt(self, slo_tasks) -> None:
        """Across the verifiable rungs, differences must be difficulty and not phrasing.

        Stricter than the repo convention, which is that a family shares one
        system-prompt *style* -- ``quantitative-quiz`` has seven distinct prompts,
        because its top rung asks for a distractor rather than a key. Nothing in
        this ladder changes what the model is asked to *do*: every rung asks for
        one number from an international-operations briefing, so an identical
        prompt is achievable here and pinning it keeps a later edit from
        introducing a phrasing difference that would read as a difficulty
        difference in the results.
        """
        prompts = {t.system_prompt for t in slo_tasks if t.id.startswith(SLO3_VERIFIABLE)}
        assert len(prompts) == 1, f"{SLO3_VERIFIABLE} has {len(prompts)} distinct system prompts"

    def test_every_family_shares_a_role_opener(self, slo_tasks) -> None:
        """The `style` half of the convention, mechanically.

        The subjective rungs genuinely ask for different work -- identify, trace,
        weigh, evaluate -- so their prompts cannot be identical and should not be.
        What must not drift is the framing the model is answering in, because a
        rung that quietly recast the role would confound its difficulty with a
        change of task.
        """
        for prefix in FAMILIES:
            openers = {t.system_prompt.split(".")[0] for t in slo_tasks if t.id.startswith(prefix)}
            assert len(openers) == 1, f"{prefix} has {len(openers)} distinct role openers"

    def test_slo4_prompts_forbid_reasoning_from_national_stereotype(self, slo_tasks) -> None:
        """Every SLO 4 rung has a rubric criterion scoring this; the prompt must ask for it.

        A rubric that penalises something the system prompt never asked for is
        measuring whether the model guessed the house style. This keeps the two
        halves in step.
        """
        for task in slo_tasks:
            if not task.id.startswith(SLO4_SUBJECTIVE):
                continue
            assert "general claims about any national culture" in task.system_prompt, (
                f"{task.id} scores no-appeal-to-national-stereotype but never asks for it"
            )


class TestSlo3SpansBothKinds:
    def test_slo3_is_measured_both_verifiably_and_subjectively(self, slo_tasks) -> None:
        """The brief asked SLO 3 to mix checkable knowledge with rubric-graded analysis.

        SCHEMA.md forbids mixing kinds *within* a family, so the mix is expressed
        as two families sharing one `slo:` tag. That is the arrangement this test
        pins: if someone later collapses them into one directory, or drops one,
        this fails.
        """
        kinds = {t.kind.value for t in slo_tasks if "slo:SLO3" in t.tags}
        assert kinds == {"verifiable", "subjective"}, f"SLO3 spans only {kinds}"

    def test_the_slo3_tag_reunites_the_two_families(self, slo_tasks) -> None:
        prefixes = {_family_of(t) for t in slo_tasks if "slo:SLO3" in t.tags}
        assert prefixes == {SLO3_VERIFIABLE, SLO3_SUBJECTIVE}


class TestVerifiableTasks:
    @pytest.fixture(scope="class")
    def verifiable(self, slo_tasks) -> list:
        return [t for t in slo_tasks if t.kind.value == "verifiable"]

    def test_every_sample_has_a_parseable_numeric_target(self, verifiable) -> None:
        """A target the scorer cannot parse is recorded as an error, not a failure."""
        for task in verifiable:
            assert task.scorer.kind.value == "numeric_match", task.id
            for sample in task.samples:
                assert sample.target is not None, f"{task.id}/{sample.id}"
                float(sample.target)  # raises ValueError if the key is unparseable

    def test_tolerance_is_opted_into_deliberately(self, verifiable) -> None:
        """Every one of these files asks for two decimal places, which needs 0.01.

        Pinned rather than left free: a tolerance tightened below the rounding the
        system prompt asks for marks correctly-rounded answers wrong, silently.
        """
        for task in verifiable:
            assert task.scorer.tolerance == pytest.approx(0.01), (
                f"{task.id} has tolerance {task.scorer.tolerance}"
            )

    def test_normalisation_is_stated_not_assumed(self, verifiable) -> None:
        for task in verifiable:
            norm = task.scorer.normalisation
            assert norm.take_last_line, f"{task.id} reasons before answering; needs take_last_line"
            assert norm.strip, task.id
            assert not norm.strip_punctuation, (
                f"{task.id}: strip_punctuation destroys decimal points under numeric_match"
            )

    def test_the_target_is_not_the_last_number_in_the_prompt(self, verifiable) -> None:
        """The defence against a model that passes by copying the prompt's last figure."""
        number = re.compile(r"-?\d[\d,]*\.?\d*")
        for task in verifiable:
            for sample in task.samples:
                found = number.findall(sample.input)
                if not found:
                    continue
                last = float(found[-1].replace(",", ""))
                assert last != pytest.approx(float(sample.target)), (
                    f"{task.id}/{sample.id}: target {sample.target} is the last number "
                    f"in its own prompt and is liftable without doing the work"
                )

    def test_no_rubric_on_a_verifiable_task(self, verifiable) -> None:
        for task in verifiable:
            assert task.rubric is None, task.id


class TestSubjectiveTasks:
    @pytest.fixture(scope="class")
    def subjective(self, slo_tasks) -> list:
        return [t for t in slo_tasks if t.kind.value == "subjective"]

    def test_scorer_points_at_the_rubric_in_the_file(self, subjective) -> None:
        for task in subjective:
            assert task.rubric is not None, task.id
            assert task.scorer.rubric_id == task.rubric.id, task.id

    def test_rubric_ids_are_versioned(self, subjective) -> None:
        """A grade is only comparable to grades from the same rubric.

        Versioning is what lets a future edit become `-v2` instead of silently
        invalidating stored results and making finished runs un-regradable.
        """
        for task in subjective:
            assert re.search(r"-v\d+$", task.rubric.id), (
                f"{task.id} rubric id {task.rubric.id!r} is not versioned"
            )

    def test_rubric_ids_are_unique_across_the_families(self, subjective) -> None:
        seen: dict[str, str] = {}
        for task in subjective:
            assert task.rubric.id not in seen, (
                f"{task.id} reuses rubric id {task.rubric.id} from {seen[task.rubric.id]}"
            )
            seen[task.rubric.id] = task.id

    def test_no_sample_carries_a_target(self, subjective) -> None:
        for task in subjective:
            for sample in task.samples:
                assert sample.target is None, f"{task.id}/{sample.id}"

    def test_every_criterion_has_behavioural_anchors(self, subjective) -> None:
        """An adjective is not an anchor.

        The schema has no per-level anchor field, so anchors live inside the
        criterion description by convention (SCHEMA.md, "The anchored-rubric
        template"). Checking all three levels are present is the only mechanical
        grip available on that convention -- and it is the one that stops a
        criterion reverting to "grade this well".
        """
        for task in subjective:
            for criterion in task.rubric.criteria:
                for level in ("1.0 --", "0.5 --", "0.0 --"):
                    assert level in criterion.description, (
                        f"{task.id}/{criterion.name} has no {level} anchor"
                    )

    def test_criteria_anchors_survived_yaml_folding(self, subjective) -> None:
        """Anchors must be written with `|-`, not `>-`.

        A folded scalar runs the three anchors into one paragraph and destroys
        the structure the judge is meant to read, invisibly: the string still
        contains all three markers, so an `in` check passes on a rubric that has
        already been ruined.

        Nor is "the description contains a newline" enough. YAML folding
        preserves a BLANK line as a newline, and every criterion here has one
        between its question and its anchors -- so a folded description still
        contains `\n` while the anchors themselves have been run together. The
        only property that actually distinguishes the two is that each anchor
        begins its own line, which is what is asserted here.
        """
        for task in subjective:
            for criterion in task.rubric.criteria:
                lines = [line.lstrip() for line in criterion.description.splitlines()]
                for level in ("1.0 --", "0.5 --", "0.0 --"):
                    assert any(line.startswith(level) for line in lines), (
                        f"{task.id}/{criterion.name}: the {level} anchor does not begin "
                        f"a line -- the description was folded with `>-` instead of `|-`"
                    )

    def test_a_rubric_has_more_than_one_criterion(self, subjective) -> None:
        """A single-criterion rubric measures one thing and cannot express a tension."""
        for task in subjective:
            assert len(task.rubric.criteria) >= 2, task.id

    def test_weights_are_positive_and_not_all_equal(self, subjective) -> None:
        """Uniform weights mean no criterion was judged to matter more than another.

        These rubrics deliberately weight a precision guard equally against its
        recall counterpart *and* rank both above the presentational criteria, so
        a flat weight vector means an authoring mistake rather than a style.
        """
        for task in subjective:
            weights = [c.weight for c in task.rubric.criteria]
            assert all(w > 0 for w in weights), task.id
            assert len(set(weights)) > 1, f"{task.id} weights every criterion equally: {weights}"

    def test_not_yet_scorable_is_advertised(self, subjective) -> None:
        """Convention from the exemplars: a human scanning the listing sees the default state."""
        for task in subjective:
            assert "not-yet-scorable" in task.tags, task.id

    def test_subjective_tasks_are_reported_unscorable_without_a_judge(self, subjective) -> None:
        """`is_scorable` means "gradable with no judge", so it is False here.

        A blank is honest; a zero would look like a failing model.
        """
        for task in subjective:
            assert task.is_scorable is False, task.id


class TestDatasetHygiene:
    """FERPA and copyright. SCHEMA.md: reviewers should refuse a family with no
    provenance statement, and nothing in the schema enforces one."""

    def test_every_task_states_its_provenance(self, slo_tasks) -> None:
        for task in slo_tasks:
            assert "Provenance:" in task.description, (
                f"{task.id} has no provenance sentence in its description"
            )
            assert "synthetic" in task.description.lower(), task.id

    def test_every_sample_records_its_provenance(self, slo_tasks) -> None:
        for task in slo_tasks:
            for sample in task.samples:
                assert sample.metadata.get("provenance") == "synthetic", (
                    f"{task.id}/{sample.id} does not record provenance: synthetic"
                )

    def test_no_sample_metadata_leaks_a_target(self, slo_tasks) -> None:
        """`GET /tasks/{id}` redacts targets and publishes metadata verbatim, unauthenticated.

        ``make lint-tasks`` runs the general form of this check; it is repeated
        here scoped to these families so the failure names the family when it is
        this family's authoring that broke it.
        """
        for task in slo_tasks:
            for sample in task.samples:
                if sample.target is None:
                    continue
                for key, value in sample.metadata.items():
                    assert str(value).strip() != sample.target.strip(), (
                        f"{task.id}/{sample.id}: metadata.{key} is the answer key"
                    )

    def test_scenarios_do_not_name_real_countries(self, slo_tasks) -> None:
        """The societies are invented on purpose.

        A benchmark that says "in country X business is done thus" encodes a
        stereotype about real people, publishes it, and then rewards a model for
        reproducing it. This checks the sample text a model actually sees; the
        surrounding prose may of course discuss the design.
        """
        real = ("China", "Japan", "Germany", "India", "Brazil", "Mexico", "France", "Nigeria")
        for task in slo_tasks:
            for sample in task.samples:
                for country in real:
                    assert country not in sample.input, (
                        f"{task.id}/{sample.id} names {country}; use an invented society"
                    )
