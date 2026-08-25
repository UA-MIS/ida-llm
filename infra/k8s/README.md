# `infra/k8s/`

**The deployable Kubernetes manifests are NOT here.** They live in
[`.devops/chart/`](../../.devops/chart/), which is what the platform's
ApplicationSet actually renders — see [`.devops/README.md`](../../.devops/README.md).

This directory is for anything Kubernetes-adjacent that is *not* part of the
deploy contract: one-off debugging manifests, notes, experiments.

⚠ Putting a manifest here does **not** deploy it. Nothing reads this path.
