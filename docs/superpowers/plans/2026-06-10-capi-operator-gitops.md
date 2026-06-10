# CAPI/CAPH providers into GitOps (Cluster API Operator) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `clusterctl init` on the specht-labs-v2 management cluster with a GitOps-managed Cluster API Operator that declares the four providers (CAPI core, kubeadm bootstrap, kubeadm control-plane, CAPH) as version-pinned CRs under ArgoCD.

**Architecture:** A new kustomize base (`cluster-api-operator`) inflates the `cluster-api-operator` Helm chart (operator only) and carries four `operator.cluster.x-k8s.io/v1alpha2` Provider CRs plus their namespaces. A v2 overlay references the base, and a new ArgoCD `Application` (registered through the existing `1-meta-specht-labs-cluster` app-of-apps) syncs it. A one-time, manually-gated cutover removes the clusterctl-installed controllers (keeping all CRDs/CRs) and lets the operator reinstall the same versions.

**Tech Stack:** Kustomize (`--enable-helm`), Helm chart `cluster-api-operator` 0.27.0, Cluster API Operator CRs, ArgoCD, clusterctl (cutover + diagnostics only).

**Reference spec:** `docs/superpowers/specs/2026-06-10-capi-operator-gitops-design.md`

---

## Reference facts (from discovery — do not re-derive)

Currently installed via `clusterctl init` on specht-labs-v2 (`~/.kube/configs/specht-labs`):

| Provider kind | name | namespace | version |
|---|---|---|---|
| CoreProvider | cluster-api | capi-system | v1.13.2 |
| BootstrapProvider | kubeadm | capi-kubeadm-bootstrap-system | v1.13.2 |
| ControlPlaneProvider | kubeadm | capi-kubeadm-control-plane-system | v1.13.2 |
| InfrastructureProvider | hetzner | caph-system | v1.1.6 |

- `hetzner` is a built-in clusterctl/operator infrastructure provider (release asset `infrastructure-components.yaml` from `github.com/syself/cluster-api-provider-hetzner`), so **no `fetchConfig` URL is required**.
- Feature gates are stock upstream defaults → Provider CRs carry **no** `featureGates`.
- CAPH reads the `hetzner` secret named in `HetznerCluster.spec.hetznerSecretRef` (already in git) → **no `configSecret`** on the InfrastructureProvider.
- cert-manager is already GitOps-managed and is the operator's webhook dependency — leave it alone.
- House norm: do **not** commit the chart tarball; `--enable-helm` pulls it (ArgoCD has `kustomize.buildOptions: --enable-alpha-plugins --enable-helm`). Mirror `kustomize/bases/cert-manager/`.
- Work happens on branch `feat/capi-operator-gitops` (already created; the design doc is the first commit).

---

## Task 1: Operator base — chart inflation + provider namespaces

**Files:**
- Create: `kustomize/bases/cluster-api-operator/kustomization.yaml`
- Create: `kustomize/bases/cluster-api-operator/helm-values.yaml`
- Create: `kustomize/bases/cluster-api-operator/namespaces.yaml`

- [ ] **Step 1: Write the Helm values (operator only)**

`kustomize/bases/cluster-api-operator/helm-values.yaml`:

```yaml
# Operator only — no core/bootstrap/controlPlane/infrastructure values, so the
# chart installs just the operator. Providers are declared as explicit CRs
# (core-provider.yaml etc.) for transparent diffs and per-provider version pins.
logLevel: 2
replicaCount: 1
leaderElection:
  enabled: true
resources:
  manager:
    limits:
      cpu: 100m
      memory: 300Mi
    requests:
      cpu: 100m
      memory: 100Mi
```

- [ ] **Step 2: Write the provider namespaces**

`kustomize/bases/cluster-api-operator/namespaces.yaml` — keeps clusterctl's namespace layout so controllers never relocate:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: capi-system
---
apiVersion: v1
kind: Namespace
metadata:
  name: capi-kubeadm-bootstrap-system
---
apiVersion: v1
kind: Namespace
metadata:
  name: capi-kubeadm-control-plane-system
---
apiVersion: v1
kind: Namespace
metadata:
  name: caph-system
```

- [ ] **Step 3: Write the base kustomization**

`kustomize/bases/cluster-api-operator/kustomization.yaml`. Note: **no top-level `namespace:` transformer** — each Provider CR must keep its own namespace, and the operator goes in `capi-operator-system`.

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Operator runs in capi-operator-system (created by the ArgoCD app's
# CreateNamespace=true). Providers install into their own namespaces below.
helmCharts:
  - name: cluster-api-operator
    repo: https://kubernetes-sigs.github.io/cluster-api-operator
    version: 0.27.0
    releaseName: cluster-api-operator
    namespace: capi-operator-system
    valuesFile: helm-values.yaml

resources:
  - namespaces.yaml
  - core-provider.yaml
  - bootstrap-provider.yaml
  - controlplane-provider.yaml
  - infrastructure-provider.yaml
```

> The four `*-provider.yaml` files are created in Task 2. The base will not build until they exist, so build validation lives in Task 2 Step 6.

- [ ] **Step 4: Commit**

```bash
git add kustomize/bases/cluster-api-operator/kustomization.yaml \
        kustomize/bases/cluster-api-operator/helm-values.yaml \
        kustomize/bases/cluster-api-operator/namespaces.yaml
git commit -m "feat(cluster-api): scaffold cluster-api-operator base (chart + namespaces)"
```

---

## Task 2: Provider CRs

**Files:**
- Create: `kustomize/bases/cluster-api-operator/core-provider.yaml`
- Create: `kustomize/bases/cluster-api-operator/bootstrap-provider.yaml`
- Create: `kustomize/bases/cluster-api-operator/controlplane-provider.yaml`
- Create: `kustomize/bases/cluster-api-operator/infrastructure-provider.yaml`

Every CR gets two ArgoCD annotations: `sync-wave: "1"` (apply after the operator + its CRDs, which are wave 0 by default) and `SkipDryRunOnMissingResource=true` (so the first sync doesn't fail dry-run before the Provider CRDs exist).

- [ ] **Step 1: CoreProvider**

`kustomize/bases/cluster-api-operator/core-provider.yaml`:

```yaml
apiVersion: operator.cluster.x-k8s.io/v1alpha2
kind: CoreProvider
metadata:
  name: cluster-api
  namespace: capi-system
  annotations:
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  version: v1.13.2
```

- [ ] **Step 2: BootstrapProvider**

`kustomize/bases/cluster-api-operator/bootstrap-provider.yaml`:

```yaml
apiVersion: operator.cluster.x-k8s.io/v1alpha2
kind: BootstrapProvider
metadata:
  name: kubeadm
  namespace: capi-kubeadm-bootstrap-system
  annotations:
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  version: v1.13.2
```

- [ ] **Step 3: ControlPlaneProvider**

`kustomize/bases/cluster-api-operator/controlplane-provider.yaml`:

```yaml
apiVersion: operator.cluster.x-k8s.io/v1alpha2
kind: ControlPlaneProvider
metadata:
  name: kubeadm
  namespace: capi-kubeadm-control-plane-system
  annotations:
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  version: v1.13.2
```

- [ ] **Step 4: InfrastructureProvider (CAPH)**

`kustomize/bases/cluster-api-operator/infrastructure-provider.yaml`:

```yaml
apiVersion: operator.cluster.x-k8s.io/v1alpha2
kind: InfrastructureProvider
metadata:
  name: hetzner
  namespace: caph-system
  annotations:
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  version: v1.1.6
```

- [ ] **Step 5: Render the base**

Run:
```bash
kustomize build --enable-helm kustomize/bases/cluster-api-operator > /tmp/capi-op-base.yaml && echo OK
```
Expected: `OK` (chart pulls on first run; needs network egress).

- [ ] **Step 6: Sanity-check the rendered output**

Run:
```bash
grep -c 'kind: CoreProvider\|kind: BootstrapProvider\|kind: ControlPlaneProvider\|kind: InfrastructureProvider' /tmp/capi-op-base.yaml
grep -E 'cluster-api-operator.*Deployment|kind: Deployment' /tmp/capi-op-base.yaml | head
grep -E 'capi-operator-system|capi-system|caph-system' /tmp/capi-op-base.yaml | sort -u | head
```
Expected: the first command prints `4`; a `cluster-api-operator-controller-manager` Deployment is present; the four namespaces appear. No `clusterctl` fetchConfig URLs are needed for hetzner.

- [ ] **Step 7: Commit**

```bash
git add kustomize/bases/cluster-api-operator/*-provider.yaml
git commit -m "feat(cluster-api): declare CAPI/CAPH providers as operator CRs (pinned to running versions)"
```

---

## Task 3: v2 overlay

**Files:**
- Create: `kustomize/overlays/specht-labs-v2/cluster-api-operator/kustomization.yaml`

- [ ] **Step 1: Write the overlay**

`kustomize/overlays/specht-labs-v2/cluster-api-operator/kustomization.yaml` — no namespace transformer (preserve per-resource namespaces):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../../bases/cluster-api-operator/
```

- [ ] **Step 2: Render the overlay**

Run:
```bash
kustomize build --enable-helm kustomize/overlays/specht-labs-v2/cluster-api-operator > /tmp/capi-op-overlay.yaml \
  && diff <(grep -E '^kind:' /tmp/capi-op-base.yaml | sort) <(grep -E '^kind:' /tmp/capi-op-overlay.yaml | sort) \
  && echo "OVERLAY MATCHES BASE KINDS"
```
Expected: `OVERLAY MATCHES BASE KINDS` (overlay is a thin passthrough).

- [ ] **Step 3: Commit**

```bash
git add kustomize/overlays/specht-labs-v2/cluster-api-operator/kustomization.yaml
git commit -m "feat(cluster-api): specht-labs-v2 overlay for cluster-api-operator"
```

---

## Task 4: ArgoCD Application

**Files:**
- Create: `argo-apps/specht-labs-v2/cluster-api-operator.yaml`

- [ ] **Step 1: Write the Application**

Modeled on `argo-apps/specht-labs-v2/cluster-api.yaml`. `prune: false` (pruning a Provider CR would tear down a live controller); no `resources-finalizer` (deleting the app must not cascade into providers).

`argo-apps/specht-labs-v2/cluster-api-operator.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cluster-api-operator
  namespace: argocd
  # No finalizer: deleting this Application must NOT cascade-delete the providers
  # (that would stop reconciliation of the live Hetzner cluster).
spec:
  project: default
  destination:
    namespace: capi-operator-system
    server: https://kubernetes.default.svc
  source:
    path: kustomize/overlays/specht-labs-v2/cluster-api-operator
    repoURL: https://github.com/SpechtLabs/k8s-deployment.git
    targetRevision: main
  syncPolicy:
    automated:
      selfHeal: true
      # prune MUST stay false. Pruning a CoreProvider/InfrastructureProvider CR
      # makes the operator uninstall the controller that reconciles the cluster.
      # Removed/renamed providers are orphaned and cleaned by hand.
      prune: false
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 2: Validate the manifest parses**

Run:
```bash
kubectl create --dry-run=client -o name -f argo-apps/specht-labs-v2/cluster-api-operator.yaml
```
Expected: `application.argoproj.io/cluster-api-operator created` (client dry-run; no cluster mutation).

- [ ] **Step 3: Commit**

```bash
git add argo-apps/specht-labs-v2/cluster-api-operator.yaml
git commit -m "feat(cluster-api): ArgoCD Application for cluster-api-operator (selfHeal, no prune)"
```

---

## Task 5: Base README (versions + cutover runbook)

**Files:**
- Create: `kustomize/bases/cluster-api-operator/README.md`

- [ ] **Step 1: Write the README**

`kustomize/bases/cluster-api-operator/README.md`:

````markdown
# cluster-api-operator — specht-labs-v2

GitOps-managed Cluster API provider stack for the **specht-labs-v2 management
cluster**. Replaces `clusterctl init`. The cluster's workload objects
(`Cluster`, `HetznerCluster`, `MachineDeployment`, …) live in
`kustomize/bases/cluster-api-v2/` and are owned by a separate ArgoCD app.

## Layout

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Inflates the `cluster-api-operator` Helm chart (operator only) + the Provider CRs and namespaces. |
| `helm-values.yaml` | Operator deployment config. No provider values — providers are explicit CRs. |
| `namespaces.yaml` | The four provider namespaces (kept identical to clusterctl's layout). |
| `core-provider.yaml` / `bootstrap-provider.yaml` / `controlplane-provider.yaml` / `infrastructure-provider.yaml` | The four `operator.cluster.x-k8s.io/v1alpha2` Provider CRs. |

## Versions (single source of truth)

| Provider | Namespace | Version |
|----------|-----------|---------|
| CoreProvider `cluster-api` | capi-system | v1.13.2 |
| BootstrapProvider `kubeadm` | capi-kubeadm-bootstrap-system | v1.13.2 |
| ControlPlaneProvider `kubeadm` | capi-kubeadm-control-plane-system | v1.13.2 |
| InfrastructureProvider `hetzner` | caph-system | v1.1.6 |
| `cluster-api-operator` chart | capi-operator-system | 0.27.0 |

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
````

- [ ] **Step 2: Commit**

```bash
git add kustomize/bases/cluster-api-operator/README.md
git commit -m "docs(cluster-api): cluster-api-operator base README (versions + cutover)"
```

---

## Task 6: Open the PR (code review before any cluster change)

No cluster mutation happens here. The cutover (Task 7) runs only after this is reviewed/merged.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/capi-operator-gitops
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base main --title "feat(cluster-api): move CAPI/CAPH providers into GitOps via Cluster API Operator" --body-file - <<'EOF'
Moves the specht-labs-v2 provider controller stack out of `clusterctl init` and
into GitOps using the Cluster API Operator.

- New base `kustomize/bases/cluster-api-operator/`: operator Helm chart 0.27.0
  (operator only) + four version-pinned Provider CRs + their namespaces.
- New v2 overlay + ArgoCD `Application` (`selfHeal: true`, `prune: false`, no
  finalizer).
- Providers pinned to the currently-running versions (CAPI v1.13.2 ×3, CAPH
  v1.1.6) so the operator reinstall converges instead of rolling nodes.

Cutover (clusterctl delete keeping all CRDs/CRs, then operator reinstall) is a
manually-gated step run after merge — see
`docs/superpowers/plans/2026-06-10-capi-operator-gitops.md` Task 7.

Design: `docs/superpowers/specs/2026-06-10-capi-operator-gitops-design.md`
EOF
```
Expected: PR URL printed.

---

## Task 7: Cutover (manual, gated — run after PR merge)

> **STOP / human-gated.** This touches the live management cluster. Do not run any step until the operator wants the cutover performed and the PR is merged to `main`. Each step has a verification; do not proceed past a failed verification — go to Rollback.

All commands use the mgmt context:
```bash
export KUBECONFIG=~/.kube/configs/specht-labs
```

- [ ] **Step 1: Snapshot pre-cutover state**

```bash
kubectl get providers -A
kubectl get cluster,machine,hetznercluster -A
kubectl get pods -n capi-system -n caph-system 2>/dev/null
kubectl get cluster,machine -A -o name | sort > /tmp/capi-pre.txt && cat /tmp/capi-pre.txt
```
Expected: four clusterctl providers `Ready`; record the Cluster/Machine list in `/tmp/capi-pre.txt` for the post-check.

- [ ] **Step 2: Disable auto-sync on the workload-objects app**

So it doesn't push Cluster/Machine changes through absent webhooks mid-cutover.

```bash
kubectl -n argocd patch application cluster-specht-labs --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
kubectl -n argocd get application cluster-specht-labs -o jsonpath='{.spec.syncPolicy}{"\n"}'
```
Expected: the printed syncPolicy no longer contains `automated`.

- [ ] **Step 3: Delete the clusterctl-managed controllers (keep CRDs/CRs)**

Explicit per-provider form so cert-manager is never touched. **No `--include-crd`, no `--include-namespace`.**

```bash
clusterctl delete \
  --core cluster-api \
  --bootstrap kubeadm \
  --control-plane kubeadm \
  --infrastructure hetzner
```
Verify CRDs and CRs survived:
```bash
kubectl get crd | grep -E 'cluster.x-k8s.io|hetzner' | head
kubectl get cluster,machine,hetznercluster -A
```
Expected: CRDs still present; every Cluster/Machine/HetznerCluster still listed (unchanged from Step 1). Controller pods in capi-* / caph-system are gone.

- [ ] **Step 4: Register and sync the operator app**

Sync the app-of-apps so the new Application appears, then sync it.

```bash
# Register the new Application via the meta app-of-apps:
argocd app sync 1-meta-specht-labs-cluster
# Then sync the operator app (operator wave 0, Provider CRs wave 1):
argocd app sync cluster-api-operator
argocd app wait cluster-api-operator --health --timeout 300
```
(If the `argocd` CLI isn't logged in, sync both Applications from the ArgoCD UI instead.)
Expected: `cluster-api-operator` reaches `Synced` / `Healthy`.

- [ ] **Step 5: Verify the operator reinstalled the providers**

```bash
kubectl get providers -A
kubectl -n capi-system get deploy
kubectl -n caph-system get deploy
kubectl get cluster,machine -A -o name | sort > /tmp/capi-post.txt
diff /tmp/capi-pre.txt /tmp/capi-post.txt && echo "NO MACHINE/CLUSTER CHURN"
```
Expected: four operator-managed providers `Ready` at the pinned versions; the four controller Deployments `Available`; `NO MACHINE/CLUSTER CHURN` printed (empty diff).

- [ ] **Step 6: Confirm reconciliation resumed, then re-enable workload-app auto-sync**

```bash
kubectl -n capi-system logs deploy/capi-controller-manager --tail=20
kubectl -n argocd patch application cluster-specht-labs --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"selfHeal":true,"prune":false}}}}'
kubectl -n argocd get application cluster-specht-labs -o jsonpath='{.spec.syncPolicy.automated}{"\n"}'
```
Expected: controller logs show normal reconcile (no crashloop/errors); `cluster-specht-labs` automated sync restored to `selfHeal:true, prune:false`.

### Rollback (if any step fails before Step 6 completes)

CRDs and CRs were never deleted, so re-creating the controllers restores the prior state:

```bash
export KUBECONFIG=~/.kube/configs/specht-labs
# Remove the half-applied operator app (no finalizer → no cascade):
kubectl -n argocd delete application cluster-api-operator
# Reinstall the original clusterctl controllers at the same versions:
clusterctl init \
  --core cluster-api:v1.13.2 \
  --bootstrap kubeadm:v1.13.2 \
  --control-plane kubeadm:v1.13.2 \
  --infrastructure hetzner:v1.1.6
# Re-enable workload-app auto-sync:
kubectl -n argocd patch application cluster-specht-labs --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"selfHeal":true,"prune":false}}}}'
```
Then investigate before retrying the cutover.

---

## Self-review notes

- **Spec coverage:** operator install (Task 1), four Provider CRs at running versions (Task 2), namespaces kept (Task 1), overlay + ArgoCD app with sync-waves/prune-false/no-finalizer (Tasks 3–4), README version table + bump procedure (Task 5), cutover with no `--include-crd` + verification + rollback (Task 7). All spec sections mapped.
- **Refinements vs spec (intentional):** (1) no committed `charts/` dir — follows the repo's `--enable-helm` norm; (2) cutover is delete-then-install rather than install-operator-then-delete, which avoids the dual-ownership conflict window while preserving every safety property; (3) cert-manager left untouched by scoping `clusterctl delete` to the four named providers instead of `--all`.
- **Name/version consistency:** provider kinds, names, namespaces, and versions match the discovery table in every task and the README.
