"""Registry loading, key resolution, and settings resolution."""

from __future__ import annotations

import pytest

from ida_core.config import Settings, repo_root
from ida_core.contracts import ModelEntry, ServingConfig, ServingStack
from ida_core.registry import MissingApiKeyError, load_registry, resolve_api_key
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
