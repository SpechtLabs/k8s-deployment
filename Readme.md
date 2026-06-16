# k8s-deployment

[![Lint](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/lint.yaml/badge.svg)](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/lint.yaml)
[![CodeQL](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/SpechtLabs/k8s-deployment/actions/workflows/github-code-scanning/codeql)

GitOps configuration for my playground Kubernetes clusters, reconciled by Argo CD.

## Layout

Each application is self-contained under `apps/<app>/`: a shared `base/` (a Kustomize
overlay that inflates the upstream Helm chart via the `helmCharts` generator, or plain
manifests) and one `cluster/<cluster>/` overlay per cluster that layers on the base.
Argo CD points at `apps/<app>/cluster/<cluster>`; everything for one app lives in one
subtree.

- **apps/** — per-app Kustomize configuration.
  - `<app>/base/` — shared base (Helm values + the inflated chart, or manifests).
  - `<app>/cluster/<cluster>/` — per-cluster overlay.
- **components/** — Kustomize resources shared across apps (Grafana dashboards and
  datasources, the `scrape-to-cloud` component).
- **argo-apps/** — the Argo CD `Application`/`ApplicationSet` definitions, grouped per
  cluster (`specht-labs-v2/`, `specht-labs/`, `labk3s/`). This is the GitOps entrypoint.
- **manifests/** — plain Kubernetes manifests applied outside the app layout (redirects,
  shortlinks, bootstrap secrets).
- **grafana/** — Grafana Cloud resources managed with `gcx` (SLOs, knowledge-graph
  suppressions).
- **docs/** — runbooks and guides (`first-deployment.md`, `working-with-argocd.md`,
  `age-secrets.md`, …).
- **hack/** — helper scripts (SOPS encrypt/decrypt, devcontainer init).

## Tooling

All CLI tooling is pinned in `mise.toml` (kustomize, helm, kubeconform, sops, age, ksops,
kubectl, clusterctl, argocd). Install it with:

```bash
mise install
```

`mise.toml` also points `KUBECONFIG` at `~/.kube/configs/specht-labs` for this repo.

## Validation

Manifests and rendered app overlays are validated with [kubeconform](https://github.com/yannh/kubeconform)
through mise tasks — the same commands run locally and in CI:

```bash
mise run check            # everything
mise run check-manifests  # plain manifests only
mise run check-apps       # render each app overlay and validate
```

CI (`.github/workflows/`) installs the pinned tools with `jdx/mise-action` and runs
`mise run check`.

Secrets are SOPS-encrypted with `age` (recipients in `.sops.yaml`) and decrypted into the
cluster by the `ksops` Kustomize generator. Use `hack/decrypt-secrets.sh` /
`hack/encrypt-secrets.sh` to work with them locally.

## Getting started

Clone the repo, run `mise install`, and follow `docs/first-deployment.md`.

## Contributing

See `CODEOWNERS` for who owns which areas.
