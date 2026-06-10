# CAPI/CAPH providers into GitOps via the Cluster API Operator

Date: 2026-06-10
Status: Approved (design), pending implementation plan

## Goal

Move the Cluster API provider controller stack on the **specht-labs-v2**
management cluster out of `clusterctl init` and into GitOps, so the providers
are declared and version-managed in this repo like everything else.

The cluster's **workload objects** (`Cluster`, `HetznerCluster`,
`KubeadmControlPlane`, `MachineDeployment`, …) are already GitOps-managed by the
`cluster-specht-labs` ArgoCD Application. The only piece still living outside git
is the four provider controller stacks that `clusterctl init` installed. This
round brings those under management.

## Current state (discovered)

specht-labs-v2 is a **self-managed** cluster: ArgoCD, the CAPI controllers, and
the cluster's own Cluster/Machine objects all live on the same cluster
(`https://kubernetes.default.svc`). Installed via `clusterctl init`:

| Provider | clusterctl inventory | namespace | version |
|----------|---------------------|-----------|---------|
| Core | `cluster-api` | `capi-system` | v1.13.2 |
| Bootstrap | `bootstrap-kubeadm` | `capi-kubeadm-bootstrap-system` | v1.13.2 |
| Control-plane | `control-plane-kubeadm` | `capi-kubeadm-control-plane-system` | v1.13.2 |
| Infrastructure | `infrastructure-hetzner` (CAPH) | `caph-system` | v1.1.6 |

Feature gates on all controllers are stock upstream defaults for these versions
(`MachinePool=true`, `ClusterTopology=false`, `RuntimeSDK=false`, …). CAPH runs
with `--leader-elect=true` and **no** provider-level credential env — it reads
the `hetzner` secret named in `HetznerCluster.spec.hetznerSecretRef`, which is
already in git. cert-manager is already GitOps-managed
(`kustomize/overlays/specht-labs-v2/cert-manager`).

## Scope

In scope:
- Install the **Cluster API Operator** (`cluster-api-operator` Helm chart,
  v0.27.0) via ArgoCD on specht-labs-v2.
- Declare the four providers as `operator.cluster.x-k8s.io/v1alpha2` CRs pinned
  to the **currently-running versions** above.
- A documented one-time **cutover** from clusterctl-managed to operator-managed.

Out of scope:
- specht-labs (v1, `cluster-cedi-dev`) — legacy, sync disabled. Replicate later
  if ever wanted.
- Any version upgrade of the providers (this round is a like-for-like handoff;
  bumps happen afterwards through the new declarative path).
- Changing the `cluster-specht-labs` app that owns the Cluster/Machine objects.
- Removing `clusterctl` from `mise.toml` (kept for diagnostics / `describe`).

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Which cluster | specht-labs-v2 only. |
| Mechanism | Cluster API Operator, not vendored static manifests — declarative version lifecycle, official GitOps path, no hand-maintained cert/webhook injection. |
| Namespaces | Keep clusterctl's namespaces (`capi-system`, `capi-kubeadm-bootstrap-system`, `capi-kubeadm-control-plane-system`, `caph-system`) by setting each Provider CR's namespace. Zero controller relocation. |
| Provider declaration | Explicit Provider CR YAML files (transparent diffs), not chart-templated providers. |
| Feature gates | Omit — inherit upstream defaults, which match the running install byte-for-byte. |
| Versions | Pin to running versions (v1.13.2 ×3, hetzner v1.1.6) so the operator's reinstall converges instead of rolling. |
| Prune policy | `prune: false`, `selfHeal: true` — match the house style; pruning a Provider CR would tear down a live controller. |

## File layout

Follows the existing base + overlay + argo-app pattern.

```
kustomize/bases/cluster-api-operator/
  kustomization.yaml            # helmChart: cluster-api-operator 0.27.0 (operator only) + Provider CRs as resources
  helm-values.yaml              # logLevel, leaderElection, resources
  charts/                       # vendored chart tarball (like metrics-server/charts)
  core-provider.yaml            # CoreProvider cluster-api v1.13.2 → capi-system
  bootstrap-provider.yaml       # BootstrapProvider kubeadm v1.13.2 → capi-kubeadm-bootstrap-system
  controlplane-provider.yaml    # ControlPlaneProvider kubeadm v1.13.2 → capi-kubeadm-control-plane-system
  infrastructure-provider.yaml  # InfrastructureProvider hetzner v1.1.6 → caph-system
  README.md                     # version pinning + cutover runbook

kustomize/overlays/specht-labs-v2/cluster-api-operator/
  kustomization.yaml            # references the base

argo-apps/specht-labs-v2/cluster-api-operator.yaml   # new ArgoCD Application
```

The operator Helm chart is installed **operator-only** (no `core:`/`bootstrap:`/
`controlPlane:`/`infrastructure:` values). Providers are declared as separate CR
files for readable diffs and explicit version control.

## Provider CRs

Four CRs, `operator.cluster.x-k8s.io/v1alpha2`:

| Kind | metadata.name | metadata.namespace | spec.version |
|------|---------------|--------------------|--------------|
| `CoreProvider` | cluster-api | capi-system | v1.13.2 |
| `BootstrapProvider` | kubeadm | capi-kubeadm-bootstrap-system | v1.13.2 |
| `ControlPlaneProvider` | kubeadm | capi-kubeadm-control-plane-system | v1.13.2 |
| `InfrastructureProvider` | hetzner | caph-system | v1.1.6 |

- The operator installs each provider into its CR's namespace → namespaces stay
  identical to clusterctl's.
- No `spec.manager.featureGates` — defaults match the running install. If a
  non-default gate is ever needed, that's where it goes.
- No `spec.configSecret` on the InfrastructureProvider — CAPH credentials are a
  per-cluster secret referenced by `HetznerCluster`, already in git, not a
  provider-config secret.

## ArgoCD Application + ordering/safety

One new `Application` named `cluster-api-operator` (namespace `argocd`) pointing
at `kustomize/overlays/specht-labs-v2/cluster-api-operator`, destination
`https://kubernetes.default.svc`.

- **Sync waves**: operator chart resources at wave 0, Provider CRs at wave 1, so
  the operator (and its `operator.cluster.x-k8s.io` CRDs) reconcile before the
  Provider CRs apply.
- **`SkipDryRunOnMissingResource=true`** on the Provider CRs so the very first
  sync doesn't fail dry-run before the Provider CRDs exist.
- **`syncPolicy`**: `automated.selfHeal: true`, `automated.prune: false`.
  Pruning a Provider CR would make the operator tear down the controller that
  reconciles the live cluster; removed/renamed providers are left orphaned and
  cleaned by hand (same rationale as the `cluster-specht-labs` app).
- **No `resources-finalizer`** — deleting the Application must not cascade into
  the providers.

## Cutover (one-time handoff)

There is no operator "adopt clusterctl" feature, so the handoff is explicit. It
is low-risk: **CAPI controllers being down does not affect the running workload
cluster** — nodes keep serving and only reconciliation pauses, so during a quiet
window nothing changes underneath.

1. Merge the operator chart + Provider CRs to git. Sync **only the operator**
   first (it installs the `operator.cluster.x-k8s.io` CRDs).
2. Temporarily disable auto-sync on the `cluster-specht-labs` app so it does not
   try to push Cluster/Machine objects through absent webhooks mid-cutover.
3. `clusterctl delete --all` against the mgmt context. Removes the four
   controller Deployments, RBAC, and webhooks. **No `--include-crd`, no
   `--include-namespace`** → all CRDs, every Cluster/Machine/HetznerCluster
   object, and the namespaces survive untouched.
4. Sync the Provider CRs → operator reinstalls the same versions into the same
   namespaces, now Git-sourced and operator-owned.
5. Verify: all four controllers `Ready`, and `kubectl get cluster,machine -A`
   unchanged (no `Machine` churn). Re-enable auto-sync on `cluster-specht-labs`.

Rollback: if anything looks wrong before step 5 completes, `clusterctl init`
with the same versions re-creates the original controllers (CRDs/CRs were never
touched), and the operator app can be deleted (no finalizer → no cascade).

## Verification

- `kubectl get providers -A` (operator CRs) shows all four `Ready` /
  `Installed` at the pinned versions.
- The four controller-manager Deployments are `Available` in their original
  namespaces, now owned/labelled by the operator.
- `kubectl get cluster,machine,hetznercluster -A` matches the pre-cutover state;
  no Machine has been recreated.
- ArgoCD shows `cluster-api-operator` `Synced` / `Healthy`.
- A trivial reconcile still works (e.g. annotate then unannotate a Machine, or
  confirm controller logs resume reconciliation without errors).

## Future upgrades

A provider bump is a one-line `spec.version:` edit in the relevant Provider CR;
the operator rolls the controller. Document the version table and the bump
procedure in the base `README.md`. The Kubernetes/containerd/runc upgrade path
(driven from the `cluster-api-v2` overlay) is unchanged and independent of this.
