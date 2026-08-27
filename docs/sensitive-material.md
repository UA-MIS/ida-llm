# Sensitive course material: where it lives and how it is handled

**Status: decided, pending ratification.** This is the storage and handling rule
for real MIS 200 course material — exams, quizzes, answer keys, and anything
else a professor would not publish. It exists so ingestion can start without
each person inventing their own answer.

It is deliberately written from what this system *actually does today*, verified
against `origin/main` and the running cluster. Where a control does not exist
yet, it is named as a gap rather than assumed.

---

## The three facts that decide this

**1. The results UI is public and unauthenticated.**

`ida-llm.capstone.uamishub.com` is served with **no auth middleware** on its
Ingress. (Compare `ida-llm-dev`, which carries `oauth2-proxy` — the gate exists
in this platform and prod deliberately does not use it.) An anonymous request
returns run pages including task name, model, scores, sample counts and task git
SHA, and the transcript route under `/api/runs/<run_id>/results/<sample_id>/transcript`
answers without a credential too.

So: **anything that becomes a benchmark run artifact is effectively published.**
Not "stored somewhere with an access policy" — published, to the internet, with
no login.

**2. Everything a model sees is archived.**

`packages/core/ida_core/artifacts.py` treats the object-store layout as a
contract: every sample transcript, judge transcript and eval log is written to
`s3://<bucket>/runs/<run_id>/…`. The store is a tenant-owned MinIO on a PVC
(`.devops/chart/base/pvc.yaml`) — not internet-facing itself, but its contents
are exactly what the public UI reads. There is no "run this without keeping the
transcript" mode, by design: archiving is what makes results auditable.

**3. There is no local-inference path today.**

`infra/inference/README.md` states it plainly: off-cluster inference to the
campus "Sparks" vLLM is **deferred and not reachable**. The tenant egress policy
grants `:443` to the internet and nothing else; vLLM defaults to `:8000`; the
NetworkPolicy that would open it lives in a different repo
(`platform-infra`, `platform-services/ida-llm-egress/netpol.yaml`).
`SPARKS_BASE_URL` is deliberately empty in `.devops/chart/base/configmap.yaml`
and CI asserts it stays empty.

**Therefore every model call this system can currently make goes to a commercial
cloud API, and its transcript lands on a public web page.**

---

## The decision

### 1. Where sensitive material lives

**Outside this repository and outside this system**, in a UA-controlled,
access-restricted location owned by the instructor who provided it — the
university's managed storage (OneDrive / SharePoint / Box under their account),
not a personal drive.

It does **not** go in:

- **the git repository** — `tasks/SCHEMA.md` § Dataset hygiene already forbids it,
  and note that it forbids it *on the assumption the repo is public*. The repo is
  private today, but that is a setting someone can flip, and it is not the control
  this rule rests on;
- **MinIO / the artifact store** — its contents surface through the public UI
  (fact 1);
- **Vault** — that is for credentials, not bulk material.

> **Gap for ratification:** the exact UA-sanctioned restricted store is the one
> question here that genuinely needs an authority outside this repo. That is what
> the OIT conversation should settle. Until it does, the instructor's own
> UA-managed storage is the working answer, and nothing in this rule changes if
> OIT names a different location — only the address changes.

### 2. What may and may not enter the repo

**May not:** real exam papers, quizzes and answer keys in current use; any real
student work, even de-identified (FERPA — `tasks/SCHEMA.md` § 1 is the standing
rule and it is stricter than "remove the names"); anything from a course LMS;
copyrighted textbook or question-bank content.

**May:** official published curriculum material — the BSCBA curriculum map
(`bscba-curriculum-map-slo.png`) is public program documentation and is fine to
commit; the SLO list derived from it; and **synthetic task content** authored to
imitate the shape of real material without being it.

If you are unsure which side something falls on, it does not go in.

### 3. How a task references sensitive material without containing it

Tasks are authored as **synthetic stand-ins with a provenance pointer**. This is
not a new mechanism — it is what `tasks/conceptual-grading/` already does, and
what `tasks/SCHEMA.md` § 1 and § 3 already require. Applied to MIS 200:

- the task's content is **written for the file**, imitating the structure and
  difficulty of the real item;
- the task's `description` carries the provenance sentence SCHEMA.md § 3 requires;
- per-sample `metadata` names the source by **reference and content hash**, never
  by content — e.g. the source document's title, its SHA-256, the SLO it maps to,
  and the fact that the original is held in the restricted store.

The hash is what makes this honest: it lets someone with authorized access to the
original confirm which item a task was derived from, without the repo ever
carrying the item.

### 4. Cloud API vs local inference for sensitive content

**No sensitive content goes into a model call. Not today, and not by exception.**

The reason is fact 1 + fact 3 together: the transcript of every call is archived
and published, and there is no local path to run it instead. A "just this once"
run against a real exam would put that exam on a public web page.

This unblocks when **both** of the following are true, and they are separate
pieces of work:

1. **A local serving path exists** — the Sparks egress route is open and a model
   is actually serving (tracked in the local-model research item);
2. **Runs can be access-gated** — the results UI can keep a run non-public. Today
   it cannot. The platform already runs `oauth2-proxy` on non-prod ingresses, so
   the mechanism exists and has simply never been applied to prod.

Until both land, MIS 200 benchmarking runs on **synthetic stand-ins only**. That
is not a limitation on the benchmark's usefulness: the stand-ins are what make
the results redistributable and the whole task suite publishable.

---

## What this means if you are ingesting MIS 200 material

You are not blocked. Concretely:

1. Collect the real material into the restricted store (§1) — it never touches
   this repo.
2. Commit the **curriculum map** and the **SLO list** derived from it — public
   material, and the backbone the benchmark hangs on.
3. Keep an index of what exists in the restricted store: title, SLO, SHA-256,
   sensitivity. The index may be committed; the material may not.
4. Author tasks as synthetic stand-ins carrying provenance pointers (§3).

---

## Known gaps

| gap | consequence | owner |
|---|---|---|
| No UA-sanctioned restricted store confirmed | §1 uses instructor-managed UA storage as the working answer | OIT conversation |
| Prod results UI has no auth gate | a run cannot be made non-public; blocks sensitive-content inference | this repo (product) |
| Local inference unreachable (egress netpol) | no compliant path to run sensitive content at all | `platform-infra` |
| `tasks/SCHEMA.md` says the repo is public; it is currently private | the rules are correct either way, but the stated premise is wrong today | this repo (docs) |
