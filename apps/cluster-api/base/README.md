# cluster-api — specht-labs cluster

Cluster API (CAPH — [Cluster API Provider Hetzner](https://github.com/syself/cluster-api-provider-hetzner))
manifests for the **specht-labs** cluster. These objects live in the **management cluster**
(where the CAPI controllers run), *not* in the workload cluster that `~/.kube/configs/specht-labs`
points at.

## Layout

| File | Purpose |
|------|---------|
| `cluster.yaml` | `Cluster` + `HetznerCluster` — network, regions, load balancer, placement groups, SSH keys, Hetzner secret ref. |
| `controlplane-template.yaml` | `KubeadmControlPlane` (3 replicas) — inline kubeadm config, kubelet config, containerd/runc/k8s install commands. |
| `config-template.yaml` | `KubeadmConfigTemplate` — the same bootstrap, for worker nodes. |
| `machine-template.yaml` | `HCloudMachineTemplate` ×2 — the Hetzner server spec (type, image, SSH keys, placement group) for control plane and workers. |
| `machine-deployment.yaml` | `MachineDeployment` ×3 — one worker per region (fsn1, hel1, nbg1). |
| `machine-healthchecks.yaml` | `MachineHealthCheck` + `HCloudRemediationTemplate` for control plane and workers. |
| `kustomization.yaml` | Ties the base together. **Version values are overridden in the overlay** (below). |

The base builds standalone with working default versions. The overlay
`apps/cluster-api/cluster/specht-labs/` is what actually gets applied; it holds the
single-source version config and the `replacements` that propagate it.

## API versions

- **Core CAPI** (`Cluster`, `MachineDeployment`, `MachineHealthCheck`, `KubeadmControlPlane`,
  `KubeadmConfigTemplate`) is on **`v1beta2`**. `v1beta1` is deprecated and slated for removal
  around **April 2027** — do not reintroduce it.
- **CAPH infra** (`HetznerCluster`, `HCloudMachineTemplate`, `HCloudRemediationTemplate`) is
  **intentionally still `v1beta1`** — that is current for CAPH 1.1.x. Migrate to
  `infrastructure.cluster.x-k8s.io/v1beta2` once **CAPH 1.2.x** ships it.
- Object references use the v1beta2 **contract-ref** form (`apiGroup:` + `kind:` + `name:`,
  no `apiVersion:`). Keep new refs in that style.

## Single source of truth for versions

`kubernetesVersion`, `containerdVersion`, and `runcVersion` are defined **once**, in the overlay's
`cluster-config` ConfigMap, and propagated by kustomize `replacements` into:

- `KubeadmControlPlane.spec.version`
- every `MachineDeployment.spec.template.spec.version`
- the `export KUBERNETES_VERSION= / CONTAINERD= / RUNC=` lines in **both** preKubeadmCommands blocks.

The preKubeadmCommands replacements address commands **by list index**, so the three `export` lines
are pinned near the top of each block (see the comments there). If you reorder those commands, update
the indices in the overlay `replacements`.

## Upgrade runbook

### Bump Kubernetes / containerd / runc

1. Edit the three literals in
   `apps/cluster-api/cluster/specht-labs/kustomization.yaml` (`configMapGenerator.cluster-config`).
2. `kubectl kustomize apps/cluster-api/cluster/specht-labs` and eyeball the diff
   (versions + export lines should all reflect the new values).
3. Commit and let it apply. A `KubeadmControlPlane.spec.version` change rolls the control plane one
   node at a time; a `MachineDeployment` version change rolls the workers (`maxUnavailable: 0`).

> For Kubernetes, bump **one minor at a time** (control plane first, which the KCP handles), and keep
> `KUBERNETES_VERSION` `v`-prefixed — the bootstrap derives the unprefixed apt version (`KUBE_PKG_VERSION`)
> and the `1.xx` repo path (`TRIMMED_KUBERNETES_VERSION`) from it.

### Change an immutable machine field (server type, image, SSH keys, placement group)

`HCloudMachineTemplate.spec` is **immutable** — you cannot edit it in place; the webhook rejects it.
Instead:

1. In `machine-template.yaml`, add/rename the template using the convention
   **`<role>-<servertype>-<image-slug>`** (e.g. `worker-cx23-ubuntu-24-04`).
2. Repoint the `infrastructureRef.name`:
   - workers → `machine-deployment.yaml`
   - control plane → `controlplane-template.yaml` (`spec.machineTemplate.spec.infrastructureRef.name`)
3. Commit. The ref change triggers a rolling replacement; the orphaned old template is pruned once no
   `Machine` references it.

## Current pinning

- Kubernetes `v1.35.4`, containerd `2.3.1`, runc `1.2.5`, image `ubuntu-24.04`.
- All nodes: **`cx23`** (2 vCPU / 4 GB, ~half the cost of `cpx22`; ~40–50 GB disk — watch etcd/image
  disk pressure on the control plane). x86 only — ARM (`cax*`) is unavailable for now.

## Applying

Confirm how this overlay reaches the **management** cluster before relying on it — at time of writing
there is **no `cluster-api` ArgoCD `Application`** under `argo-apps/`, so it is applied manually
(`kubectl apply` / `clusterctl` against the mgmt cluster context). Prefer a server-side dry-run first:

```sh
kubectl kustomize apps/cluster-api/cluster/specht-labs \
  | kubectl --context <mgmt> apply --dry-run=server -f -
```

## Hetzner credentials secret

The CAPH controller authenticates to Hetzner via the `hetzner` secret in
namespace `default`, referenced by `HetznerCluster.spec.hetznerSecretRef`. It is
SOPS-encrypted (age) and GitOps-managed: it lives at
`apps/cluster-api/cluster/specht-labs/hetzner.secret.yaml` and is
decrypted by ArgoCD's ksops plugin via that overlay's `secret-generator.yaml`.
The `cluster-specht-labs` app applies it (`prune: false`, so it is never pruned).

> **Bootstrap caveat:** on a from-scratch management cluster the secret must
> exist before the `HetznerCluster` reconciles, but ArgoCD/ksops must be running
> to decrypt it. For the initial bootstrap apply it once by hand
> (`sops -d …/hetzner.secret.yaml | kubectl apply -f -`); thereafter ArgoCD owns
> it. Rotate the token by editing the encrypted file (`sops …`) and committing.
