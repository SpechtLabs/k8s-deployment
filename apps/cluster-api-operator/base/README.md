# cluster-api-operator — specht-labs

GitOps-managed Cluster API provider stack for the **specht-labs management
cluster**. Replaces `clusterctl init`. The cluster's workload objects
(`Cluster`, `HetznerCluster`, `MachineDeployment`, …) live in
`apps/cluster-api-v2/base/` and are owned by a separate ArgoCD app
(`cluster-specht-labs`).

## Layout

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Inflates the `cluster-api-operator` Helm chart (operator only) + the Provider CRs and namespaces. |
| `helm-values.yaml` | Operator deployment config. No provider values — providers are explicit CRs. |
| `namespaces.yaml` | The four provider namespaces (kept identical to clusterctl's layout). |
| `core-provider.yaml` / `bootstrap-provider.yaml` / `controlplane-provider.yaml` / `infrastructure-provider.yaml` | The four `operator.cluster.x-k8s.io/v1alpha2` Provider CRs. |

The base inflates the chart via kustomize `--enable-helm` (ArgoCD has it in
`kustomize.buildOptions`); the chart tarball is **not** vendored, matching the
repo convention (see `docs/chart-deployments.md`).

## Versions (single source of truth)

| Provider | Namespace | Version |
|----------|-----------|---------|
| CoreProvider `cluster-api` | capi-system | v1.13.2 |
| BootstrapProvider `kubeadm` | capi-kubeadm-bootstrap-system | v1.13.2 |
| ControlPlaneProvider `kubeadm` | capi-kubeadm-control-plane-system | v1.13.2 |
| InfrastructureProvider `hetzner` | caph-system | v1.1.6 |
| `cluster-api-operator` chart | capi-operator-system | 0.27.0 |

`hetzner` is a built-in clusterctl/operator infrastructure provider, so the CR
needs no `fetchConfig` URL. The providers run stock upstream feature gates, so
the CRs carry no `featureGates`. CAPH reads the `hetzner` secret named in
`HetznerCluster.spec.hetznerSecretRef` (already in git), so the
InfrastructureProvider needs no `configSecret`.

### Bump a provider

Edit `spec.version` in the relevant Provider CR, commit, let ArgoCD sync. The
operator rolls that controller. Bump CAPI core/bootstrap/control-plane together
(they share a release train); CAPH (`hetzner`) moves independently. Mind the API
contract notes in `../cluster-api-v2/README.md` before a CAPH minor bump.

## One-time cutover from clusterctl

See the project plan `docs/superpowers/plans/2026-06-10-capi-operator-gitops.md`,
Task 7. Summary: disable auto-sync on the `cluster-specht-labs` app, run
`clusterctl delete` for the four providers (CRDs and Cluster/Machine objects are
**kept** — never pass `--include-crd`), then sync this app so the operator
reinstalls the same versions. Controllers being briefly down only pauses
reconciliation; the running cluster is unaffected.
