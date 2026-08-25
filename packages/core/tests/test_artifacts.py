"""The object-key convention is a contract; these tests pin it literally."""

from __future__ import annotations

import pytest

from ida_core.artifacts import (
    DEFAULT_BUCKET,
    LocalArtifactStore,
    eval_log_key,
    judge_key,
    parse_uri,
    run_prefix,
    sample_key,
    to_uri,
)


class TestKeyConvention:
    def test_run_prefix_literal(self) -> None:
        assert run_prefix("run_abc") == "runs/run_abc/"

    def test_sample_key_literal(self) -> None:
        assert sample_key("run_abc", "add-simple") == "runs/run_abc/transcripts/add-simple.json"

    def test_repeat_key_literal(self) -> None:
        assert (
            sample_key("run_abc", "add-simple", 1) == "runs/run_abc/transcripts/add-simple/r1.json"
        )

    def test_eval_log_key_literal(self) -> None:
        assert eval_log_key("run_abc") == "runs/run_abc/eval-log.json"

    def test_everything_for_a_run_shares_one_prefix(self) -> None:
        prefix = run_prefix("run_abc")
        assert sample_key("run_abc", "s").startswith(prefix)
        assert eval_log_key("run_abc").startswith(prefix)


class TestPathTraversalDefence:
    @pytest.mark.parametrize(
        "hostile", ["../escape", "a/b", "..", ".hidden", "with space", "", "a" * 300]
    )
    def test_hostile_sample_ids_are_refused(self, hostile: str) -> None:
        with pytest.raises(ValueError, match="unsafe"):
            sample_key("run_abc", hostile)

    def test_hostile_run_ids_are_refused(self) -> None:
        with pytest.raises(ValueError, match="unsafe"):
            run_prefix("../../etc")


class TestUri:
    def test_round_trip(self) -> None:
        uri = to_uri("bucket", "runs/r/eval-log.json")
        assert uri == "s3://bucket/runs/r/eval-log.json"
        assert parse_uri(uri) == ("bucket", "runs/r/eval-log.json")

    @pytest.mark.parametrize("bad", ["http://x/y", "s3://onlybucket", "s3://", "nonsense"])
    def test_malformed_uris_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_uri(bad)


class TestLocalArtifactStore:
    def test_round_trip_and_uri(self, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        key = sample_key("run_x", "s1")
        uri = store.put_json(key, {"hello": "world"})
        assert uri == f"s3://{DEFAULT_BUCKET}/{key}"
        assert store.get_json(key) == {"hello": "world"}
        assert store.exists(key)

    def test_missing_key_raises_keyerror(self, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with pytest.raises(KeyError):
            store.get_json("runs/nope/eval-log.json")

    def test_key_escaping_root_is_refused(self, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with pytest.raises(ValueError, match="escapes store root"):
            store.put_json("../../etc/passwd", {})

    def test_ensure_bucket_is_idempotent(self, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        store.ensure_bucket()
        assert (tmp_path / DEFAULT_BUCKET).is_dir()


class TestRepeatKeysCannotCollide:
    """N1 — repetition keys must not be forgeable by a sample id.

    The original scheme suffixed the leaf (``<sample_id>.r<n>.json``). Because
    ``.`` is a legal sample-id character, a task with a sample named ``s1.r2``
    produced *the identical key* to repetition 2 of a sample named ``s1``:

        sample_key(run, "s1",    2)  ->  runs/<run>/transcripts/s1.r2.json
        sample_key(run, "s1.r2", 0)  ->  runs/<run>/transcripts/s1.r2.json

    Both writes succeed, so one transcript silently destroys the other and the
    surviving one is cited as evidence for the wrong sample. Nesting repetitions
    under a directory makes the collision structurally impossible, because ``/``
    is the one character a sample id may never contain.
    """

    def test_the_specific_reported_collision_is_gone(self) -> None:
        assert sample_key("run_abc", "s1", 2) != sample_key("run_abc", "s1.r2", 0)

    @pytest.mark.parametrize(
        "sample_id,repeat",
        [
            ("s1", 1),
            ("s1", 2),
            ("s1", 10),
            ("fig.3a", 1),
            ("a.r1", 1),
            ("a-b_c.d", 3),
        ],
    )
    def test_a_repeat_key_is_never_reachable_as_a_repeat_zero_key(
        self, sample_id: str, repeat: int
    ) -> None:
        """No sample id, however adversarial, can name a repetition's object."""
        target = sample_key("run_abc", sample_id, repeat)
        # A repeat-0 key is `transcripts/<id>.json` with <id> containing no '/'.
        # A repeat-n key has a '/' after `transcripts/`, so no <id> can produce it.
        leaf = target.removeprefix("runs/run_abc/transcripts/")
        assert "/" in leaf, f"{target} is forgeable by a sample id"

    def test_keys_are_unique_across_a_realistic_id_and_repeat_matrix(self) -> None:
        """Exhaustive over ids that stress the '.'-and-'r' interaction."""
        ids = ["s1", "s1.r1", "s1.r2", "r1", "s1.r", "fig.3a", "a.b.c"]
        repeats = range(0, 4)
        keys = [sample_key("run_abc", i, n) for i in ids for n in repeats]
        assert len(keys) == len(set(keys)), "duplicate keys in the matrix"

    def test_repeat_zero_is_unchanged(self) -> None:
        """Existing objects must keep resolving; this convention is documented
        as stable and there are already transcripts written under it."""
        assert sample_key("run_abc", "add-simple") == ("runs/run_abc/transcripts/add-simple.json")
        assert sample_key("run_abc", "add-simple", 0) == sample_key("run_abc", "add-simple")

    def test_repeats_still_live_under_the_run_prefix(self) -> None:
        """The one-LIST-per-run property must survive the nesting."""
        assert sample_key("run_abc", "s1", 3).startswith(run_prefix("run_abc"))

    def test_a_negative_repeat_is_refused(self) -> None:
        with pytest.raises(ValueError, match="repeat_index"):
            sample_key("run_abc", "s1", -1)

    def test_an_unsafe_id_is_still_refused_for_repeats(self) -> None:
        """The traversal defence must not be bypassable via the repeat path."""
        with pytest.raises(ValueError, match="unsafe"):
            sample_key("run_abc", "../escape", 2)


class TestLocalStoreHandlesRepeats:
    """The nested form must actually round-trip on a real filesystem.

    A directory named ``s1/`` and a file named ``s1.json`` coexisting in the same
    parent is legal on POSIX and in S3 (whose keys are flat strings), but it is
    worth proving rather than assuming -- it is the one place the two backends
    could plausibly disagree.
    """

    def test_repeat_zero_and_repeat_n_coexist(self, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        store.put_json(sample_key("run_x", "s1", 0), {"repeat": 0})
        store.put_json(sample_key("run_x", "s1", 1), {"repeat": 1})
        store.put_json(sample_key("run_x", "s1", 2), {"repeat": 2})

        assert store.get_json(sample_key("run_x", "s1", 0)) == {"repeat": 0}
        assert store.get_json(sample_key("run_x", "s1", 1)) == {"repeat": 1}
        assert store.get_json(sample_key("run_x", "s1", 2)) == {"repeat": 2}

    def test_the_previously_colliding_pair_now_round_trips_independently(self, tmp_path) -> None:
        """End to end: write both, read both, neither clobbered the other."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        store.put_json(sample_key("run_x", "s1", 2), {"which": "repeat-2-of-s1"})
        store.put_json(sample_key("run_x", "s1.r2", 0), {"which": "sample-named-s1.r2"})

        assert store.get_json(sample_key("run_x", "s1", 2)) == {"which": "repeat-2-of-s1"}
        assert store.get_json(sample_key("run_x", "s1.r2", 0)) == {"which": "sample-named-s1.r2"}


class TestJudgeKeyConvention:
    """The judge prefix is ADDITIVE: nothing that was already written moves.

    A judged run gains ``runs/<id>/judge/``; ``transcripts/`` is byte-for-byte
    what it was. That matters beyond tidiness -- anything counting keys under
    ``transcripts/`` to mean "samples in this run" would have silently doubled
    if judge objects had been interleaved there.
    """

    def test_literal(self) -> None:
        assert judge_key("run_abc", "s1") == "runs/run_abc/judge/s1.json"

    def test_repeat_literal(self) -> None:
        assert judge_key("run_abc", "s1", 2) == "runs/run_abc/judge/s1/r2.json"

    def test_it_is_a_sibling_of_transcripts_not_a_child(self) -> None:
        assert judge_key("run_abc", "s1") != sample_key("run_abc", "s1")
        assert "transcripts/" not in judge_key("run_abc", "s1")

    def test_it_lives_under_the_run_prefix(self) -> None:
        """So deleting a run is still ONE prefixed delete."""
        assert judge_key("run_abc", "s1").startswith(run_prefix("run_abc"))
        assert judge_key("run_abc", "s1", 3).startswith(run_prefix("run_abc"))

    def test_a_run_with_no_judge_has_no_judge_prefix(self) -> None:
        """'Was this run graded?' is answerable from object storage alone."""
        keys = {sample_key("run_abc", "s1"), eval_log_key("run_abc")}
        assert not any(k.startswith("runs/run_abc/judge/") for k in keys)

    @pytest.mark.parametrize(
        "hostile", ["../escape", "a/b", ".hidden", "", "x" * 300, "..", "/abs"]
    )
    def test_hostile_sample_ids_are_refused_here_too(self, hostile: str) -> None:
        """Same defence as sample_key -- a hostile task file must not be able to
        write outside its run prefix through the judge path either."""
        with pytest.raises(ValueError):
            judge_key("run_abc", hostile)

    def test_a_negative_repeat_is_refused(self) -> None:
        with pytest.raises(ValueError, match="repeat_index"):
            judge_key("run_abc", "s1", -1)

    def test_repeats_cannot_collide_with_a_dotted_sample_id(self) -> None:
        """The ``s1.r2`` collision that motivated nesting in sample_key applies
        identically here, so it is defended identically."""
        assert judge_key("run_abc", "s1.r2") != judge_key("run_abc", "s1", 2)

    def test_it_round_trips_through_a_real_store(self, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        uri = store.put_json(judge_key("run_abc", "s1"), {"aggregate": 0.75})
        assert uri.endswith("runs/run_abc/judge/s1.json")
        assert store.get_json(judge_key("run_abc", "s1"))["aggregate"] == 0.75
