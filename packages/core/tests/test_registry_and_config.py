"""Registry loading, key resolution, and settings resolution."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from ida_core.config import Settings, repo_root
from ida_core.contracts import ModelEntry, ServingConfig, ServingStack
from ida_core.registry import (
    MissingApiKeyError,
    MissingBaseUrlError,
    load_registry,
    resolve_api_key,
    resolve_base_url,
)
from ida_core.validation import ValidationError

MINIMAL = """
version: 1
models:
  - key: mock
    display_name: Mock
    base_url: http://mock-model:8000/v1
    serving:
      model_id: mock-echo-1
      serving_stack: mock
"""


class TestLoadRegistry:
    def test_loads_and_derives_registry_key(self, tmp_path) -> None:
        path = tmp_path / "models.yaml"
        path.write_text(MINIMAL)
        registry = load_registry(path)
        assert registry.get("mock").serving.registry_key == "mock"

    def test_schema_error_names_the_file(self, tmp_path) -> None:
        path = tmp_path / "models.yaml"
        path.write_text("version: 1\nmodels: []\n")
        with pytest.raises(ValidationError) as exc:
            load_registry(path)
        assert str(path) in str(exc.value)

    def test_shipped_registry_loads(self) -> None:
        registry = load_registry(repo_root() / "models.yaml")
        assert registry.enabled_keys() == ["mock"]

    def test_shipped_mock_entry_needs_no_api_key(self) -> None:
        """The whole point: `make dev` and CI must work with zero secrets."""
        entry = load_registry(repo_root() / "models.yaml").get("mock")
        assert entry.api_key_env is None
        assert resolve_api_key(entry, env={}) is None


class TestResolveApiKey:
    def _entry(self, api_key_env: str | None) -> ModelEntry:
        return ModelEntry(
            key="k",
            display_name="K",
            base_url="http://x/v1",
            api_key_env=api_key_env,
            serving=ServingConfig(model_id="m", serving_stack=ServingStack.MOCK),
        )

    def test_none_when_no_env_declared(self) -> None:
        assert resolve_api_key(self._entry(None), env={}) is None

    def test_reads_the_named_variable(self) -> None:
        assert resolve_api_key(self._entry("MY_KEY"), env={"MY_KEY": "sk-x"}) == "sk-x"

    def test_missing_variable_fails_loudly(self) -> None:
        with pytest.raises(MissingApiKeyError, match="MY_KEY"):
            resolve_api_key(self._entry("MY_KEY"), env={})

    def test_empty_variable_is_treated_as_missing(self) -> None:
        with pytest.raises(MissingApiKeyError):
            resolve_api_key(self._entry("MY_KEY"), env={"MY_KEY": ""})


class TestSettings:
    def test_env_prefix(self, monkeypatch) -> None:
        monkeypatch.setenv("IDA_REDIS_URL", "redis://elsewhere:6379/3")
        assert Settings().redis_url == "redis://elsewhere:6379/3"

    def test_no_secret_defaults(self) -> None:
        settings = Settings()
        assert settings.s3_access_key == ""
        assert settings.s3_secret_key == ""

    def test_auth_is_disabled_by_default(self) -> None:
        assert Settings().auth_mode == "disabled"

    def test_paths_fall_back_to_repo_root(self) -> None:
        settings = Settings(models_file="", tasks_dir="")
        assert settings.resolved_models_file().name == "models.yaml"
        assert settings.resolved_tasks_dir().name == "tasks"

    def test_explicit_paths_win(self, tmp_path) -> None:
        settings = Settings(models_file=str(tmp_path / "m.yaml"), tasks_dir=str(tmp_path / "t"))
        assert settings.resolved_models_file() == tmp_path / "m.yaml"
        assert settings.resolved_tasks_dir() == tmp_path / "t"

    def test_sweep_knobs_are_settable_from_the_environment(self, monkeypatch) -> None:
        """The CronJobs run a FIXED argv, so the environment is the ONLY lever.

        A sweep setting that could be reached solely through a CLI flag would be
        unreachable in the cluster -- and the flag it duplicates would look like
        a working control while the schedule ignored it. Asserted here rather
        than trusted to the prefix convention.
        """
        monkeypatch.setenv("IDA_SWEEP_MAX_RUNS", "7")
        monkeypatch.setenv("IDA_SWEEP_MAX_SAMPLES", "70")
        monkeypatch.setenv("IDA_SWEEP_FORCE", "1")
        monkeypatch.setenv("IDA_SWEEP_JUDGE_CANDIDATE_LIMIT", "9")

        settings = Settings()

        assert settings.sweep_max_runs == 7
        assert settings.sweep_max_samples == 70
        assert settings.sweep_force is True
        assert settings.sweep_judge_candidate_limit == 9

    def test_sweep_defaults_are_the_deployed_values(self) -> None:
        """No ConfigMap entry exists for these, so the defaults ARE production."""
        settings = Settings()

        assert settings.sweep_force is False, "forcing spend must never be the default"
        assert settings.sweep_max_runs > 0
        assert settings.sweep_max_samples > 0

    def test_repo_root_honours_explicit_env(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("IDA_REPO_ROOT", str(tmp_path))
        assert repo_root() == tmp_path


class TestGitMeta:
    def test_env_override_wins(self, monkeypatch) -> None:
        from ida_core.gitmeta import current_git_sha

        monkeypatch.setenv("IDA_GIT_SHA", "b" * 40)
        assert current_git_sha() == "b" * 40

    def test_absence_is_honest_not_faked(self, monkeypatch, tmp_path) -> None:
        """A None SHA means unreproducible. It must never be a placeholder string."""
        from ida_core.gitmeta import current_git_sha

        monkeypatch.delenv("IDA_GIT_SHA", raising=False)
        result = current_git_sha(tmp_path)
        assert result is None or len(result) == 40


class TestGitShaShapeChecking:
    """A wrong SHA looks like a real one. Only a well-formed SHA may be stored.

    Regression: this repository had no commits, `git rev-parse HEAD` printed the
    literal string "HEAD", and it was stored as provenance on every result --
    violating gitmeta's own documented contract that None means unreproducible
    and is never faked. The compose-mode tracer bullet caught it.
    """

    def test_accepts_a_real_sha(self) -> None:
        from ida_core.gitmeta import is_sha

        assert is_sha("0123456789abcdef0123456789abcdef01234567")

    @pytest.mark.parametrize(
        "bad",
        [
            "HEAD",  # what git prints in a repo with no commits
            "a" * 7,  # abbreviated: not guaranteed unique forever
            "a" * 41,
            "A" * 40,  # uppercase is not what git emits
            "g" * 40,  # not hex
            "$GITHUB_SHA",  # an unsubstituted pipeline variable
            "",
            None,
        ],
    )
    def test_rejects_everything_else(self, bad) -> None:
        from ida_core.gitmeta import is_sha

        assert is_sha(bad) is False

    def test_malformed_env_var_yields_none_not_the_garbage(self, monkeypatch) -> None:
        from ida_core.gitmeta import current_git_sha

        monkeypatch.setenv("IDA_GIT_SHA", "HEAD")
        assert current_git_sha() is None

    def test_wellformed_env_var_is_used(self, monkeypatch) -> None:
        from ida_core.gitmeta import current_git_sha

        monkeypatch.setenv("IDA_GIT_SHA", "b" * 40)
        assert current_git_sha() == "b" * 40


class TestResolveBaseUrl:
    """The credit/hardware safety switch.

    ONE image is promoted byte-identically from dev to staging to prod, so the
    endpoint a model resolves to CANNOT be baked into the image -- it has to come
    from the environment. `MOCK_MODEL_BASE_URL` is patched per overlay (the
    in-cluster stub in dev and preview, EMPTY in staging and prod) and
    .devops/ci/chart-render.test.sh asserts both directions. These tests are the
    app-side half of that assertion.
    """

    @staticmethod
    def _entry(**overrides) -> ModelEntry:
        base = {
            "key": "probe",
            "display_name": "Probe",
            "base_url": "http://literal:8000/v1",
            "serving": {"model_id": "m", "serving_stack": "mock"},
        }
        base.update(overrides)
        return ModelEntry.model_validate(base)

    def test_the_literal_is_used_when_no_variable_is_declared(self) -> None:
        assert resolve_base_url(self._entry(), env={}) == "http://literal:8000/v1"

    def test_the_variable_wins_when_set(self) -> None:
        entry = self._entry(base_url_env="MOCK_MODEL_BASE_URL")
        resolved = resolve_base_url(entry, env={"MOCK_MODEL_BASE_URL": "http://in-cluster/v1"})
        assert resolved == "http://in-cluster/v1"

    def test_an_empty_variable_falls_back_to_the_literal(self) -> None:
        """THE safety switch, in the shape the overlays actually use.

        staging and prod set MOCK_MODEL_BASE_URL to "" rather than deleting the
        key, so an overlay diff shows the switch being thrown rather than a line
        quietly vanishing. Empty must therefore mean "not set", not "the endpoint
        is the empty string".
        """
        entry = self._entry(base_url_env="MOCK_MODEL_BASE_URL")
        assert resolve_base_url(entry, env={"MOCK_MODEL_BASE_URL": ""}) == (
            "http://literal:8000/v1"
        )

    def test_whitespace_is_treated_as_empty(self) -> None:
        entry = self._entry(base_url_env="MOCK_MODEL_BASE_URL")
        assert resolve_base_url(entry, env={"MOCK_MODEL_BASE_URL": "   "}) == (
            "http://literal:8000/v1"
        )

    def test_no_literal_and_no_value_fails_loudly_naming_the_variable(self) -> None:
        """`sparks-local` is the live case: unreachable from this cluster today.

        The message must name SPARKS_BASE_URL, because "which variable do I set"
        is the only question the operator actually has. Silently resolving to
        anything -- or hanging on a connect timeout -- answers it far too late.
        """
        entry = self._entry(base_url="", base_url_env="SPARKS_BASE_URL")
        with pytest.raises(MissingBaseUrlError, match="SPARKS_BASE_URL"):
            resolve_base_url(entry, env={})

    def test_an_entry_with_neither_is_refused_at_load(self) -> None:
        """Unlike the two resolve-at-use-time rules above, this one CAN be
        decided at load: an entry with no endpoint at all is not "unconfigured
        for this environment", it is unusable in every environment."""
        with pytest.raises(PydanticValidationError, match="neither base_url"):
            self._entry(base_url="")

    def test_the_shipped_mock_entry_uses_the_switch(self) -> None:
        """A regression guard on models.yaml itself: dropping base_url_env from
        the mock entry would make the dev overlay's patch a silent no-op and dev
        would try to resolve a docker-compose hostname."""
        registry = load_registry(repo_root() / "models.yaml")
        assert registry.get("mock").base_url_env == "MOCK_MODEL_BASE_URL"

    def test_the_shipped_sparks_entry_is_present_disabled_and_fallback_free(self) -> None:
        registry = load_registry(repo_root() / "models.yaml")
        sparks = registry.get("sparks-local")
        assert sparks.enabled is False
        assert sparks.base_url_env == "SPARKS_BASE_URL"
        assert sparks.base_url == "", "no fallback: fail loudly rather than guess"


class TestOpenAIBaseNormalisation:
    """The platform writes ORIGINS; this codebase speaks in `/v1` BASES.

    `MOCK_MODEL_BASE_URL` is `http://ida-llm-mock-model` in the dev and preview
    overlays and `http://127.0.0.1:8099` in CI -- k8s Service addresses, not API
    bases. `.devops/ci/chart-render.test.sh` asserts those exact strings, so the
    reconciliation belongs in the app, at the boundary.

    Without it the harness requests `/chat/completions` at the Service ROOT and
    gets 404 on every single call, reported as "mock returned HTTP 404" -- a
    message that points nowhere near the ConfigMap that caused it. That is
    precisely how this was found: it passed locally (where compose supplies a
    `/v1` literal) and failed in CI.
    """

    @staticmethod
    def _entry(**overrides) -> ModelEntry:
        base = {
            "key": "probe",
            "display_name": "Probe",
            "base_url": "http://literal:8000/v1",
            "serving": {"model_id": "m", "serving_stack": "mock"},
        }
        base.update(overrides)
        return ModelEntry.model_validate(base)

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            # what the dev/preview overlays actually set
            ("http://ida-llm-mock-model", "http://ida-llm-mock-model/v1"),
            # what both workflows actually set
            ("http://127.0.0.1:8099", "http://127.0.0.1:8099/v1"),
            # a trailing slash is still an origin
            ("http://ida-llm-mock-model/", "http://ida-llm-mock-model/v1"),
            # already a base: left ALONE, not doubled
            ("http://mock-model:8000/v1", "http://mock-model:8000/v1"),
            ("https://api.anthropic.com/v1", "https://api.anthropic.com/v1"),
            # a non-/v1 path is somebody's deliberate mount point; do not touch it
            ("http://gw.internal/llm/openai", "http://gw.internal/llm/openai"),
        ],
    )
    def test_origins_gain_v1_and_bases_are_untouched(self, supplied: str, expected: str) -> None:
        entry = self._entry(base_url_env="MOCK_MODEL_BASE_URL")
        assert resolve_base_url(entry, env={"MOCK_MODEL_BASE_URL": supplied}) == expected

    def test_the_literal_is_normalised_too(self) -> None:
        """Same rule both sides of the switch -- a difference here would mean dev
        and local dev hit different paths, which is the whole class of bug this
        function exists to close."""
        entry = self._entry(base_url="http://mock-model:8000")
        assert resolve_base_url(entry, env={}) == "http://mock-model:8000/v1"

    def test_the_ci_environment_resolves_to_a_working_base(self) -> None:
        """A regression guard on the EXACT value both workflows set."""
        registry = load_registry(repo_root() / "models.yaml")
        resolved = resolve_base_url(
            registry.get("mock"), env={"MOCK_MODEL_BASE_URL": "http://127.0.0.1:8099"}
        )
        assert resolved.endswith("/v1"), resolved
