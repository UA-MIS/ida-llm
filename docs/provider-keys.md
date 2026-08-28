# Provider keys: how a secret reaches a model call

**Audience:** anyone adding a model that needs an API key, or debugging
`model 'x' requires env var 'Y', which is unset`.

`models.yaml` never contains a secret. It contains the **name** of an
environment variable. This page is the rest of that sentence: where the value
comes from, who puts it there, and what to do when it is not there.

---

## The chain, end to end

```
Vault                       secret/tenants/ida-llm/<env>/app
  │                         property: OPENAI_API_KEY
  ▼  ExternalSecret (ESO)   .devops/chart/overlays/<env>/app-secret.externalsecret.yaml
Secret                      ida-llm-secret
  │                         key: OPENAI_API_KEY
  ▼  secretKeyRef           .devops/chart/base/deployments.yaml (runner)
                            .devops/chart/base/cronjobs.yaml  (3 sweeps)
container env               OPENAI_API_KEY=sk-...
  │
  ▼  resolve_api_key()      packages/core/ida_core/registry.py
models.yaml entry           api_key_env: OPENAI_API_KEY
  │
  ▼  build_client()         packages/harness/ida_harness/factory.py
the request                 Authorization: Bearer sk-...
```

Five files, four owners, and **nothing fails at start-up when a link is
missing** — the pod boots happily and the first job that selects the model dies.
That is why `services/runner/tests/test_provider_keys.py` reads the manifests and
asserts the chain joins up: it fails in the PR that breaks a link, not in the
environment that needed it.

---

## Adding a provider key

### 1. Name the variable in `models.yaml`

```yaml
  - key: my-model
    api_key_env: MY_PROVIDER_API_KEY   # a NAME. Never a value.
```

Two properties of this field are load-bearing:

- **`null` means the endpoint is unauthenticated** — the mock model, a campus
  vLLM behind a NetworkPolicy. It is a declared property of the entry, not a
  fallback. A hosted `https://` endpoint with `api_key_env: null` would send
  unauthenticated requests; `test_a_hosted_entry_names_a_key_variable` fails
  that.
- **It resolves at *use* time, not load time.** A developer with no OpenAI key
  must still be able to parse `models.yaml` and run the mock. A registry that
  refused to load because one disabled entry's variable was unset would be a
  file nobody could edit.

### 2. Put the value in Vault

```bash
vault kv patch secret/tenants/ida-llm/dev/app MY_PROVIDER_API_KEY=...
```

Per environment, deliberately: a leaked dev key cannot be spent against the
production budget. **This repo never writes to Vault**, and no CI job holds a
token that could.

### 3. Pull it into the Secret

Add a pair to the ExternalSecret for **each** environment
(`.devops/chart/overlays/{staging,prod}/app-secret.externalsecret.yaml`):

```yaml
    - secretKey: MY_PROVIDER_API_KEY
      remoteRef: { key: tenants/ida-llm/<env>/app, property: MY_PROVIDER_API_KEY }
```

### 4. Project it into the processes that call models

The **runner** (`.devops/chart/base/deployments.yaml`) and all three **sweep
CronJobs** (`.devops/chart/base/cronjobs.yaml`):

```yaml
            - name: MY_PROVIDER_API_KEY
              valueFrom:
                secretKeyRef:
                  name: ida-llm-secret
                  key: MY_PROVIDER_API_KEY
```

The API service does **not** get model keys, and should not: it never calls a
model. It enqueues.

> `secretKeyRef`s here are deliberately **not** `optional: true`. A missing
> secret keeps the pod in `CreateContainerConfigError` — loud and correct —
> rather than letting it boot with the variable unset and serve wrong results
> while reporting Ready. Every Deployment reading an ESO secret also carries a
> Reloader annotation, or a pod that started before ESO wrote the Secret would
> keep its unresolved env for the life of the container.

### 5. Document it in `.env.example`

Empty, with a comment saying when it is needed. The test suite checks that every
*enabled* entry's variable appears there.

### 6. Let the tests confirm the chain

```bash
make test-python    # test_provider_keys.py reads the real manifests
```

Steps 3 and 4 are the ones people forget. The sweeps are the trap in
particular: they select models **with no human present**, so a key that is
missing only from `cronjobs.yaml` surfaces as a job that fails every night at
02:00 and nowhere else.

> The live example of exactly that: the CronJobs receive `ANTHROPIC_API_KEY` and
> `OPENAI_API_KEY` but **not** `SPARKS_API_KEY`. Harmless while `sparks-local`
> is disabled; a nightly failure the moment it is not.

---

## `OPENAI_API_KEY` today

It is **already in Vault at `tenants/ida-llm/<env>/app`**, already pulled into
`ida-llm-secret`, and already projected into the runner and all three CronJobs.
Nothing needs adding for issue #49 — this section is the confirmation, and
`test_provider_keys.py` is the executable version of it.

What it unlocks is the `luna` entry (`gpt-5.6-luna`), the one hosted model this
project enables.

> ### ⚠ The key is scoped and capped
>
> It is scoped to **Luna only** and carries a **$25 hard cap, enforced
> OpenAI-side. It is for TESTING** — proving the real provider path works end to
> end — **not the finished product's budget.**
>
> The cap is a backstop against a mistake, not an allowance to spend.
>
> **Enabled is not the same as swept.** Both nightly sweeps plan over the
> *enabled* set, so enabling Luna would otherwise have scheduled a full
> unattended suite against it — `model-sweep` exists precisely to give a newly
> enabled model its first numbers. Luna's `testing-only` tag holds it back, via
> `IDA_SWEEP_EXCLUDE_TAGS` (default `testing-only`). A sweep that holds a model
> back says so in its report and its log. Removing the tag, or clearing that
> setting, schedules real spend — do the arithmetic first; see
> [`calibration.md`](calibration.md) for how to size a run.

### Why you cannot use it locally, and should not want to

`OPENAI_API_KEY` is **unset on dev boxes and in CI, deliberately.** Selecting
`luna` there fails immediately with

```
model 'luna' requires env var 'OPENAI_API_KEY', which is unset
```

That is the system working. The safety switch is structural rather than
remembered: local and CI runs reach `MOCK_MODEL_BASE_URL`, so no pull request
can burn credits. If you set a real key in your local `.env`, you have opted out
of that and you are spending from the test budget on a machine nobody is
auditing. Don't.

Real Luna calls happen **in a deployed environment**, where the key is present
because ESO put it there.

---

## Debugging

| Symptom | Cause | Fix |
|---|---|---|
| `requires env var 'X', which is unset` | not projected into this process, or Vault property missing | steps 2–4 above |
| Same error, but only in nightly sweeps | key is in `deployments.yaml`, missing from `cronjobs.yaml` | step 4, all three CronJobs |
| Pod stuck in `CreateContainerConfigError` | the Secret has no such key — ESO has not synced, or the property name is wrong | check the ExternalSecret's `remoteRef.property` |
| 401 from the provider | the key resolved but is wrong/revoked/for another org | rotate in Vault (step 2); Reloader restarts the pods |
| Works in staging, fails in prod | Vault paths are **per environment** | patch `.../prod/app` too |

An empty string counts as **missing**, not as a key. Sending an empty
`Authorization` header produces a 401 far from the cause, so
`resolve_api_key` refuses it up front.

---

## Rules that are not negotiable

1. **Never commit a key.** `models.yaml` names variables; `.env.example` ships
   them empty. A pasted key in either is the most expensive single mistake
   available in this repo.
2. **Never add a mock fallback.** `build_client` has none at any point, on
   purpose: a stand-in whose answers were stored under a real model's name
   poisons the results table, and nothing downstream can tell that it did. An
   unconfigured provider fails.
3. **Never make a `secretKeyRef` optional.** Loud beats Ready-and-wrong.
4. **This repo does not write to Vault.** Seeding and rotation are done by a
   human with a token, out of band.

## See also

- [`model-clients.md`](model-clients.md) — which client answers, and why
- [`calibration.md`](calibration.md) — sizing a real run against the $25 budget
- `.devops/README.md` — the Secrets table and the tenant Composition
