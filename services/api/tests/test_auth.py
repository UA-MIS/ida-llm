"""``auth_mode="token"``: the control that gates *spend*, not *reading*.

WHAT THIS FILE IS DEFENDING (D-49, ``docs/sensitive-material.md`` section 6).
``POST /runs`` enqueues work against real providers -- it spends money -- and
until this change the anonymous principal held ``runner``, so anyone who could
reach the API could spend it. That was contained only by the API having no
public Ingress, i.e. by accident of routing, and the containment disappears the
moment the API is routed publicly or a "run this" button lands.

The results view is a different question and stays PUBLIC on purpose: a
benchmark nobody can read is not a benchmark. So every read below is asserted
to still answer anonymously *with auth enabled* -- those assertions are not
padding, they are half the requirement, and they are what fails if someone
"secures the API" by putting a blanket dependency on the app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ida_api.app import create_app
from ida_api.auth import (
    MIN_TOKEN_LENGTH,
    AuthConfigError,
    parse_auth_tokens,
    validate_auth_config,
)
from ida_api.deps import AppContext
from ida_core.config import Settings

VERIFIABLE_TASK = "demo/arithmetic-quiz-check"

# Obviously-fake fixtures. Long enough to clear MIN_TOKEN_LENGTH, because the
# parser refuses a short one and a test that used "abc" would be testing the
# refusal rather than the route.
CI_TOKEN = "ci-token-not-a-real-secret-0001"  # noqa: S105 - fixture, and it says so
PROF_TOKEN = "prof-token-not-a-real-secret-002"  # noqa: S105 - ditto
AUTH_TOKENS = f"ci:{CI_TOKEN}, prof-smith:{PROF_TOKEN}"

ENQUEUE = {"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}


@pytest.fixture
def gated(context: AppContext) -> TestClient:
    """The deployed posture: auth on, two tokens configured."""
    context.settings.auth_mode = "token"
    context.settings.auth_tokens = AUTH_TOKENS
    return TestClient(create_app(context))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestTokenParsing:
    """Strict, and strict on purpose: every rejection here is a misconfiguration
    that would otherwise surface as an auth mode that cannot be enforced."""

    def test_parses_subject_and_token_pairs(self) -> None:
        assert parse_auth_tokens(AUTH_TOKENS) == {CI_TOKEN: "ci", PROF_TOKEN: "prof-smith"}

    @pytest.mark.parametrize(
        "raw",
        [
            f"ci:{CI_TOKEN},prof-smith:{PROF_TOKEN}",
            f"ci:{CI_TOKEN} prof-smith:{PROF_TOKEN}",
            f"  ci:{CI_TOKEN} ,\n prof-smith:{PROF_TOKEN}  ",
        ],
        ids=["comma", "whitespace", "both-with-slop"],
    )
    def test_separators_and_surrounding_space_are_tolerated(self, raw: str) -> None:
        """An operator pasting this into a Vault field will not be tidy."""
        assert parse_auth_tokens(raw) == {CI_TOKEN: "ci", PROF_TOKEN: "prof-smith"}

    def test_empty_is_no_tokens_not_an_error(self) -> None:
        assert parse_auth_tokens("") == {}
        assert parse_auth_tokens("   ") == {}

    def test_a_colon_in_the_token_is_kept(self) -> None:
        """Split on the FIRST colon only -- the subject is a label, the token is
        opaque and may contain anything, including a colon."""
        token = "aa:bb:cc-not-a-real-secret-0001"  # noqa: S105 - fixture
        assert parse_auth_tokens(f"ci:{token}") == {token: "ci"}

    @pytest.mark.parametrize(
        ("raw", "why"),
        [
            (f"{CI_TOKEN}", "no subject: an unattributable token"),
            (f":{CI_TOKEN}", "empty subject"),
            ("ci:", "empty token"),
            ("ci:short", "below the minimum length"),
            (f"ci:{CI_TOKEN},other:{CI_TOKEN}", "the same token for two subjects"),
            (f"ci:{CI_TOKEN},ci:{PROF_TOKEN}", "the same subject twice"),
        ],
    )
    def test_refuses_a_malformed_entry(self, raw: str, why: str) -> None:
        with pytest.raises(AuthConfigError):
            parse_auth_tokens(raw), why

    def test_the_error_never_quotes_the_token(self) -> None:
        """A config error goes to the pod log. The log must not become the leak."""
        with pytest.raises(AuthConfigError) as excinfo:
            parse_auth_tokens(f"ci:{CI_TOKEN},other:{CI_TOKEN}")
        assert CI_TOKEN not in str(excinfo.value)

    def test_a_short_token_is_refused_by_length_not_by_taste(self) -> None:
        subject_prefix = "ci:"
        assert parse_auth_tokens(subject_prefix + "x" * MIN_TOKEN_LENGTH)
        with pytest.raises(AuthConfigError):
            parse_auth_tokens(subject_prefix + "x" * (MIN_TOKEN_LENGTH - 1))


class TestStartupValidation:
    """Fail at boot, not at the first request.

    A pod that boots with ``auth_mode=token`` and no usable token cannot enforce
    the mode it was told to enforce. Refusing to start makes that a failed
    readiness probe -- the old replicas keep serving -- instead of a service that
    reports Ready while every enqueue 503s or, worse, succeeds.
    """

    def test_disabled_mode_needs_no_tokens(self) -> None:
        validate_auth_config(Settings(auth_mode="disabled", auth_tokens=""))

    def test_token_mode_without_tokens_refuses_to_start(self) -> None:
        with pytest.raises(AuthConfigError, match="auth_tokens"):
            validate_auth_config(Settings(auth_mode="token", auth_tokens=""))

    def test_token_mode_with_malformed_tokens_refuses_to_start(self) -> None:
        with pytest.raises(AuthConfigError):
            validate_auth_config(Settings(auth_mode="token", auth_tokens="ci:short"))

    def test_malformed_tokens_are_caught_even_while_disabled(self) -> None:
        """So the typo is found now, not on the day someone flips the flag."""
        with pytest.raises(AuthConfigError):
            validate_auth_config(Settings(auth_mode="disabled", auth_tokens="ci:short"))

    def test_create_app_refuses_a_mode_it_cannot_enforce(self, context: AppContext) -> None:
        context.settings.auth_mode = "token"
        context.settings.auth_tokens = ""
        with pytest.raises(AuthConfigError):
            create_app(context)

    def test_an_unimplemented_mode_still_boots_and_501s(self, context: AppContext) -> None:
        """Unchanged: an unknown mode is a REQUEST-time 501, not a boot failure.

        Booting is what lets the 501 be seen. The pod is up, the reads work, and
        the one thing that would spend money says, loudly, that it cannot.
        """
        context.settings.auth_mode = "oidc"
        client = TestClient(create_app(context))
        assert client.post("/runs", json=ENQUEUE).status_code == 501


class TestReadsStayPublic:
    """§1 of docs/sensitive-material.md: DO NOT GATE THE RESULTS UI."""

    @pytest.mark.parametrize(
        "path",
        [
            "/healthz",
            "/readyz",
            "/health",
            "/models",
            "/tasks",
            f"/tasks/{VERIFIABLE_TASK}",
            "/runs",
        ],
    )
    def test_anonymous_can_read_with_auth_enabled(self, gated: TestClient, path: str) -> None:
        assert gated.get(path).status_code == 200

    def test_anonymous_can_read_a_run_and_its_results(
        self, gated: TestClient, context: AppContext
    ) -> None:
        """The run has to exist first, and only a runner can make one exist."""
        run_id = gated.post("/runs", json=ENQUEUE, headers=bearer(CI_TOKEN)).json()["runs"][0]["id"]
        assert gated.get(f"/runs/{run_id}").status_code == 200

    def test_anonymous_can_read_an_archived_transcript(self, gated: TestClient, context) -> None:
        from ida_core.artifacts import sample_key

        context.artifact_store.put_json(sample_key("run_abc", "add-simple"), {"completion": "42"})
        response = gated.get("/runs/run_abc/results/add-simple/transcript")
        assert response.status_code == 200
        assert response.json() == {"completion": "42"}

    def test_the_answer_key_stays_shut_for_anonymous(self, gated: TestClient) -> None:
        """A10 is unchanged by this story: gating spend did not open the key."""
        assert gated.get(f"/tasks/{VERIFIABLE_TASK}?include_targets=true").status_code == 403


class TestAnonymousCannotSpend:
    def test_enqueue_is_refused(self, gated: TestClient) -> None:
        response = gated.post("/runs", json=ENQUEUE)
        assert response.status_code == 403
        assert "runner" in response.json()["detail"]

    def test_and_enqueues_absolutely_nothing(self, gated: TestClient, context: AppContext) -> None:
        """The assertion that actually matters: a 403 with a message on the queue
        would be a gate in name only."""
        gated.post("/runs", json=ENQUEUE)
        assert context.queue.depth() == 0
        assert gated.get("/runs").json()["total"] == 0

    def test_the_refusal_precedes_validation(self, gated: TestClient) -> None:
        """An unauthenticated caller must not be able to probe which task ids and
        model keys exist by reading 404 vs 409 off this endpoint."""
        response = gated.post("/runs", json={"task_ids": ["no/such"], "model_keys": ["nope"]})
        assert response.status_code == 403, "not 404 -- the role check is first"


class TestBadCredentialsAre401:
    """Distinct from 403 on purpose: 401 says 'your credential did not parse or
    is not one we know', 403 says 'we know who you are and you may not do this'.
    A wrong token silently degrading to anonymous would show up as a confusing
    403 and send an operator hunting for a role problem."""

    @pytest.mark.parametrize(
        ("header", "why"),
        [
            ({"Authorization": "Bearer not-a-configured-token-x"}, "unknown token"),
            ({"Authorization": f"Bearer {CI_TOKEN[:-1]}"}, "near miss on a real token"),
            ({"Authorization": f"Basic {CI_TOKEN}"}, "wrong scheme"),
            ({"Authorization": CI_TOKEN}, "no scheme at all"),
            ({"Authorization": "Bearer"}, "scheme with no token"),
            ({"Authorization": "Bearer "}, "scheme with an empty token"),
            ({"Authorization": ""}, "empty header"),
        ],
    )
    def test_enqueue_is_401(self, gated: TestClient, header: dict, why: str) -> None:
        response = gated.post("/runs", json=ENQUEUE, headers=header)
        assert response.status_code == 401, why

    def test_a_non_ascii_token_is_a_401_not_a_500(self, gated: TestClient) -> None:
        """`hmac.compare_digest` REFUSES a str with non-ASCII characters --
        it raises TypeError rather than returning False. Comparing the raw
        strings would turn junk in the header into an unhandled 500 on the auth
        path, and a 500 there is indistinguishable, from outside, from a route
        that never checked. Junk is a 401 like any other wrong credential."""
        # Sent as RAW BYTES, because that is the only way such a header can
        # actually arrive: on the wire headers are bytes, and Starlette decodes
        # them latin-1, so byte 0xFC reaches the handler as the str "\xfc" --
        # a perfectly ordinary str that compare_digest still refuses.
        response = gated.post(
            "/runs", json=ENQUEUE, headers={"Authorization": b"Bearer \xfc-token-attempt-xx"}
        )
        assert response.status_code == 401

    def test_401_carries_the_challenge(self, gated: TestClient) -> None:
        response = gated.post("/runs", json=ENQUEUE, headers=bearer("wrong-token-entirely-x"))
        assert response.headers["www-authenticate"] == "Bearer"

    def test_401_never_echoes_the_offered_token(self, gated: TestClient) -> None:
        offered = "wrong-token-entirely-but-guessable"
        assert offered not in gated.post("/runs", json=ENQUEUE, headers=bearer(offered)).text

    def test_a_bad_credential_enqueues_nothing(
        self, gated: TestClient, context: AppContext
    ) -> None:
        gated.post("/runs", json=ENQUEUE, headers=bearer("wrong-token-entirely-x"))
        assert context.queue.depth() == 0

    def test_a_bad_credential_also_fails_a_read_that_resolves_a_principal(
        self, gated: TestClient
    ) -> None:
        """Presenting a broken credential is an error on ANY route that reads one.
        Reads are open to *anonymous*, which is not the same as ignoring what you
        actually sent: a wrong token must never be treated as "no token"."""
        response = gated.get(f"/tasks/{VERIFIABLE_TASK}", headers=bearer("wrong-token-entirely-x"))
        assert response.status_code == 401

    def test_a_read_that_needs_no_principal_is_untouched(self, gated: TestClient) -> None:
        """`GET /tasks` resolves no principal, so there is nothing to reject."""
        assert gated.get("/tasks", headers=bearer("wrong-token-entirely-x")).status_code == 200

    def test_the_scheme_is_matched_case_insensitively(self, gated: TestClient) -> None:
        """RFC 7235: the scheme is case-insensitive. Rejecting `bearer` would be
        a 401 that looks exactly like a wrong token."""
        response = gated.post(
            "/runs", json=ENQUEUE, headers={"Authorization": f"bearer {CI_TOKEN}"}
        )
        assert response.status_code == 202


class TestAuthenticatedRunnerCanSpend:
    def test_enqueue_succeeds(self, gated: TestClient) -> None:
        assert gated.post("/runs", json=ENQUEUE, headers=bearer(CI_TOKEN)).status_code == 202

    def test_the_run_actually_reaches_the_queue(
        self, gated: TestClient, context: AppContext
    ) -> None:
        body = gated.post("/runs", json=ENQUEUE, headers=bearer(CI_TOKEN)).json()
        assert body["queued"] == 1
        assert context.queue.dequeue(timeout_s=0).run_id == body["runs"][0]["id"]

    def test_every_configured_subject_works(self, gated: TestClient) -> None:
        assert gated.post("/runs", json=ENQUEUE, headers=bearer(PROF_TOKEN)).status_code == 202

    def test_the_principal_is_attributable(self, gated: TestClient, caplog) -> None:
        """The subject is a label, and this is what it is for: the enqueue log
        line names who spent the money."""
        import logging

        with caplog.at_level(logging.INFO, logger="ida_api.app"):
            gated.post("/runs", json=ENQUEUE, headers=bearer(PROF_TOKEN))
        assert "prof-smith" in caplog.text

    def test_the_log_never_carries_the_token(self, gated: TestClient, caplog) -> None:
        import logging

        with caplog.at_level(logging.DEBUG):
            gated.post("/runs", json=ENQUEUE, headers=bearer(PROF_TOKEN))
        assert PROF_TOKEN not in caplog.text

    def test_a_token_holder_still_cannot_see_the_answer_key(self, gated: TestClient) -> None:
        """A static shared token is a WEAKER credential than the platform SSO
        A10 was written against, so it grants reader+runner and stops there.
        `author` stays fail-shut until real SSO lands."""
        response = gated.get(
            f"/tasks/{VERIFIABLE_TASK}?include_targets=true", headers=bearer(CI_TOKEN)
        )
        assert response.status_code == 403
        assert "author" in response.json()["detail"]


class TestTheOtherCostInterlocksAreUntouched:
    """This gate is one of three (D-43 suspended sweeps, the mock-only registry,
    and now this). Adding it must not have loosened the other two."""

    def test_the_budget_cap_still_refuses_an_oversized_sweep(self, gated: TestClient) -> None:
        response = gated.post(
            "/runs",
            json={
                "task_ids": [f"t{i}" for i in range(60)],
                "model_keys": [f"m{i}" for i in range(10)],
            },
            headers=bearer(CI_TOKEN),
        )
        assert response.status_code == 422, "authenticating does not buy an exemption"

    def test_duplicates_are_still_collapsed(self, gated: TestClient) -> None:
        body = gated.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, VERIFIABLE_TASK], "model_keys": ["mock", "mock"]},
            headers=bearer(CI_TOKEN),
        ).json()
        assert body["queued"] == 1

    def test_an_unknown_model_still_404s_for_a_real_runner(self, gated: TestClient) -> None:
        response = gated.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["gpt-nonexistent"]},
            headers=bearer(CI_TOKEN),
        )
        assert response.status_code == 404


class TestDisabledModeIsUnchanged:
    """Local dev, CI and the tracer bullet all run this path, and all of them run
    against the mock model. Requiring a token there would buy no safety and cost
    every contributor a setup step."""

    def test_anonymous_can_still_enqueue(self, client: TestClient) -> None:
        assert client.post("/runs", json=ENQUEUE).status_code == 202

    def test_it_is_the_default(self) -> None:
        assert Settings(_env_file=None).auth_mode == "disabled"
        assert Settings(_env_file=None).auth_tokens == ""

    def test_a_stray_authorization_header_is_ignored(self, client: TestClient) -> None:
        """With auth off there is nothing to validate against, so a leftover
        header from a curl history must not 401 a developer."""
        response = client.post("/runs", json=ENQUEUE, headers=bearer("whatever-x"))
        assert response.status_code == 202
