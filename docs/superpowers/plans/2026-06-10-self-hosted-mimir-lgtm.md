# Self-hosted Mimir (LGTM scaffold) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a right-sized, multi-tenant Grafana Mimir (Kafka ingest-storage) on specht-labs-v2 in an `lgtm` namespace, ingesting via the existing tailnet Gateway, with the LGTM ApplicationSet scaffolded so Loki/Tempo/Grafana are a one-line add later.

**Architecture:** `mimir-distributed` 6.0.6 (Mimir 3.0.4) via kustomize `helmCharts`, scaled to 1 replica per component, RF1, Kafka ingest-storage (single-node KRaft), blocks in Hetzner Object Storage. Deployed by an ArgoCD ApplicationSet that mirrors the repo's `monitoring`/`network` appsets. Three tenants (`homelab`, `hass`, `hass-schiltach`) tagged by per-hostname `X-Scope-OrgID` injection on HTTPRoutes.

**Tech Stack:** Kustomize (+ `--enable-helm`), Helm chart `grafana/mimir-distributed` 6.0.6, ksops + SOPS/age, Gateway API (Envoy Gateway), ArgoCD ApplicationSet.

**Reference spec:** `docs/superpowers/specs/2026-06-10-self-hosted-mimir-lgtm-design.md`

---

## Prerequisites (the operator provides at execution time)

1. A Hetzner Object Storage bucket (default name used here: `specht-labs-mimir-blocks`).
2. The bucket region (`fsn1`, `nbg1`, or `hel1`) — sets the S3 `endpoint`.
3. An access key + secret key for that bucket.
4. Local tooling: `kustomize`, `helm`, `sops`. The age **public** recipients are already in `.sops.yaml`, so `sops -e` works without private keys; only ArgoCD (in-cluster) needs the private key to decrypt.

If the bucket name or region differs, change the two values in `kustomize/bases/mimir/helm-values.yaml` (`bucket_name`, `endpoint`) before Task 1's verify step.

## File structure

```
kustomize/bases/mimir/
  kustomization.yaml          # helmCharts: mimir-distributed 6.0.6, releaseName mimir, valuesFile
  helm-values.yaml            # right-sized values + mimir.structuredConfig
kustomize/overlays/specht-labs-v2/mimir/
  kustomization.yaml          # namespace lgtm; references base + httproutes; ksops generator
  secret-generator.yaml       # ksops generator manifest
  mimir-objstore.secret.yaml  # SOPS-encrypted Secret: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  httproutes.yaml             # 3 HTTPRoutes, per-tenant X-Scope-OrgID injection
argo-apps/specht-labs-v2/lgtm.yaml   # ApplicationSet: mimir live, loki/tempo/grafana commented
```

Each file has one job: the base defines the workload, the overlay binds it to the cluster (namespace, secret, ingest), the appset tells ArgoCD to deploy it.

---

### Task 1: Mimir base (chart + values)

**Files:**
- Create: `kustomize/bases/mimir/kustomization.yaml`
- Create: `kustomize/bases/mimir/helm-values.yaml`

- [ ] **Step 1: Create the base kustomization**

`kustomize/bases/mimir/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: lgtm

helmCharts:
  - name: mimir-distributed
    repo: https://grafana.github.io/helm-charts
    version: 6.0.6
    releaseName: mimir
    namespace: lgtm
    valuesFile: helm-values.yaml
```

- [ ] **Step 2: Create the right-sized values**

`kustomize/bases/mimir/helm-values.yaml`:

```yaml
# Right-sized single-replica Mimir for homelab scale (Kafka ingest-storage).
# Structural reference: grafana mimir-distributed/small.yaml, scaled to RF1 and
# 1 replica each. Chart-default per-component resources are already modest
# (ingester 100m/512Mi, not small.yaml's 3.5/8Gi), so resources are NOT overridden.

minio:
  enabled: false              # blocks live in Hetzner Object Storage, not bundled MinIO

alertmanager:
  enabled: false              # not needed for v1
ruler:
  enabled: false              # not needed for v1
rollout_operator:
  enabled: false              # only needed for zone-aware rollouts (which we disable)

global:
  extraEnvFrom:
    - secretRef:
        name: mimir-objstore  # provides AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

distributor:
  replicas: 1
querier:
  replicas: 1
query_frontend:
  replicas: 1
query_scheduler:
  replicas: 1
overrides_exporter:
  replicas: 1

ingester:
  replicas: 1
  zoneAwareReplication:
    enabled: false
  persistentVolume:
    enabled: true
    size: 10Gi

store_gateway:
  replicas: 1
  zoneAwareReplication:
    enabled: false
  persistentVolume:
    enabled: true
    size: 5Gi

compactor:
  replicas: 1
  persistentVolume:
    enabled: true
    size: 10Gi

gateway:
  replicas: 1

# kafka stays enabled (chart default) for ingest-storage: single-node KRaft
# (apache/kafka-native, no Zookeeper). Chart defaults: 5Gi PV, 1 CPU / 1Gi. Left as-is.

mimir:
  structuredConfig:
    multitenancy_enabled: true
    common:
      storage:
        backend: s3
        s3:
          # CHANGE to your Hetzner Object Storage region: fsn1 / nbg1 / hel1
          endpoint: fsn1.your-objectstorage.com
          bucket_name: specht-labs-mimir-blocks
          access_key_id: ${AWS_ACCESS_KEY_ID}
          secret_access_key: ${AWS_SECRET_ACCESS_KEY}
    ingester:
      ring:
        replication_factor: 1
    store_gateway:
      sharding_ring:
        replication_factor: 1
    ingest_storage:
      kafka:
        auto_create_topic_default_partitions: 8
```

- [ ] **Step 3: Render and assert the topology**

Run:
```bash
kustomize build --enable-helm kustomize/bases/mimir > /tmp/mimir-base.yaml && echo OK
```
Expected: prints `OK` (exit 0), no errors.

Then assert the invariants:
```bash
grep -c 'multitenancy_enabled: true'                 /tmp/mimir-base.yaml   # -> 1
grep -c 'replication_factor: 1'                       /tmp/mimir-base.yaml   # -> 2 (ingester + store_gateway)
grep -c 'auto_create_topic_default_partitions: 8'     /tmp/mimir-base.yaml   # -> 1
grep -c 'name: mimir-kafka'                            /tmp/mimir-base.yaml   # -> >=1 (kafka present)
grep -c 'name: mimir-alertmanager'                    /tmp/mimir-base.yaml   # -> 0
grep -c 'name: mimir-ruler'                           /tmp/mimir-base.yaml   # -> 0
grep -Ec 'kind: .*[Mm]inio'                           /tmp/mimir-base.yaml   # -> 0
grep -c 'config.expand-env=true'                      /tmp/mimir-base.yaml   # -> >=10 (env expansion on)
```
Expected: the counts in the comments. If `mimir-alertmanager`/`mimir-ruler`/minio are non-zero, the disable toggles did not apply — recheck Step 2.

- [ ] **Step 4: Confirm every workload is namespaced to lgtm**

Run:
```bash
grep -E '^\s+namespace:' /tmp/mimir-base.yaml | grep -v 'lgtm' || echo "all lgtm"
```
Expected: `all lgtm` (the base `namespace: lgtm` rewrites everything).

- [ ] **Step 5: Commit**

```bash
git add kustomize/bases/mimir/
git commit -m "feat(lgtm): add right-sized Mimir base (mimir-distributed 6.0.6, Kafka ingest-storage)"
```

---

### Task 2: specht-labs-v2 overlay (namespace, S3 secret, ingest routes)

**Files:**
- Create: `kustomize/overlays/specht-labs-v2/mimir/secret-generator.yaml`
- Create: `kustomize/overlays/specht-labs-v2/mimir/mimir-objstore.secret.yaml`
- Create: `kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml`
- Create: `kustomize/overlays/specht-labs-v2/mimir/kustomization.yaml`

- [ ] **Step 1: Create the ksops generator**

`kustomize/overlays/specht-labs-v2/mimir/secret-generator.yaml`:

```yaml
apiVersion: viaduct.ai/v1
kind: ksops
metadata:
  name: mimir-objstore-secrets
files:
  - ./mimir-objstore.secret.yaml
```

- [ ] **Step 2: Create the object-storage Secret (plaintext, will be encrypted next)**

`kustomize/overlays/specht-labs-v2/mimir/mimir-objstore.secret.yaml`. Replace the two values with the real Hetzner keys from the prerequisites:

```yaml
apiVersion: v1
kind: Secret
type: Opaque
metadata:
  name: mimir-objstore
  namespace: lgtm
stringData:
  AWS_ACCESS_KEY_ID: REPLACE_WITH_HETZNER_ACCESS_KEY
  AWS_SECRET_ACCESS_KEY: REPLACE_WITH_HETZNER_SECRET_KEY
```

- [ ] **Step 3: Encrypt the Secret in place with SOPS**

Run:
```bash
sops -e -i kustomize/overlays/specht-labs-v2/mimir/mimir-objstore.secret.yaml
```
Then verify it is encrypted (no plaintext key material remains):
```bash
grep -c 'ENC\[' kustomize/overlays/specht-labs-v2/mimir/mimir-objstore.secret.yaml   # -> >=2
grep -c 'REPLACE_WITH_'    kustomize/overlays/specht-labs-v2/mimir/mimir-objstore.secret.yaml   # -> 0
grep -c 'sops:'            kustomize/overlays/specht-labs-v2/mimir/mimir-objstore.secret.yaml   # -> 1
```
Expected: the `stringData` values are now `ENC[AES256_GCM,...]`, no `REPLACE_WITH_` left, a `sops:` block present. The `.sops.yaml` rule `kustomize/.*/.*secret.yaml` encrypts `stringData` automatically; `metadata.name`/`namespace` stay readable.

- [ ] **Step 4: Create the per-tenant ingest routes**

`kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml`:

```yaml
# One HTTPRoute per tenant on the tailnet-only Gateway. Each injects the tenant's
# X-Scope-OrgID so clients (Pis, Home Assistant) need no custom-header config.
# Route + backend (mimir-gateway) are both in lgtm, so no ReferenceGrant needed.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mimir-homelab
  namespace: lgtm
spec:
  parentRefs:
    - name: tailnet
      namespace: envoy-gateway-system
      sectionName: http
  hostnames:
    - homelab-mimir.k8s.specht-labs.de
  rules:
    - filters:
        - type: RequestHeaderModifier
          requestHeaderModifier:
            set:
              - name: X-Scope-OrgID
                value: homelab
      backendRefs:
        - name: mimir-gateway
          port: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mimir-hass
  namespace: lgtm
spec:
  parentRefs:
    - name: tailnet
      namespace: envoy-gateway-system
      sectionName: http
  hostnames:
    - hass-mimir.k8s.specht-labs.de
  rules:
    - filters:
        - type: RequestHeaderModifier
          requestHeaderModifier:
            set:
              - name: X-Scope-OrgID
                value: hass
      backendRefs:
        - name: mimir-gateway
          port: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mimir-hass-schiltach
  namespace: lgtm
spec:
  parentRefs:
    - name: tailnet
      namespace: envoy-gateway-system
      sectionName: http
  hostnames:
    - hass-schiltach-mimir.k8s.specht-labs.de
  rules:
    - filters:
        - type: RequestHeaderModifier
          requestHeaderModifier:
            set:
              - name: X-Scope-OrgID
                value: hass-schiltach
      backendRefs:
        - name: mimir-gateway
          port: 80
```

- [ ] **Step 5: Create the overlay kustomization**

`kustomize/overlays/specht-labs-v2/mimir/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: lgtm

resources:
  - ../../../bases/mimir
  - ./httproutes.yaml

generators:
  - ./secret-generator.yaml
```

- [ ] **Step 6: Validate the route + secret YAML (portable, no ksops needed)**

The full overlay build needs the ksops exec plugin and the age private key, which only ArgoCD has. Validate the hand-written manifests instead:

Run:
```bash
kubeconform -strict -ignore-missing-schemas kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml && echo ROUTES_OK
```
Expected: `ROUTES_OK`. If `kubeconform` is not installed, fall back to:
```bash
python3 -c "import yaml,sys; list(yaml.safe_load_all(open('kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml'))); print('YAML_OK')"
```
Expected: `YAML_OK` and three documents parse.

Assert the tenant wiring:
```bash
grep -c 'X-Scope-OrgID'   kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml   # -> 3
grep -c 'value: homelab\|value: hass\|value: hass-schiltach' kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml   # -> 3
grep -c 'name: mimir-gateway' kustomize/overlays/specht-labs-v2/mimir/httproutes.yaml   # -> 3
```
Expected: 3, 3, 3.

- [ ] **Step 7: (Optional) Full overlay build if ksops + age key are available locally**

Only if the executor has KSOPS installed and the age private key in `SOPS_AGE_KEY_FILE`:
```bash
kustomize build --enable-helm --enable-alpha-plugins --enable-exec \
  kustomize/overlays/specht-labs-v2/mimir > /tmp/mimir-overlay.yaml && \
  grep -c 'kind: HTTPRoute' /tmp/mimir-overlay.yaml   # -> 3
```
Expected: builds clean, 3 HTTPRoutes. If ksops/age is not available, skip — ArgoCD performs this build in-cluster.

- [ ] **Step 8: Commit**

```bash
git add kustomize/overlays/specht-labs-v2/mimir/
git commit -m "feat(lgtm): mimir overlay for specht-labs-v2 (lgtm ns, Hetzner S3 secret, per-tenant ingest routes)"
```

---

### Task 3: LGTM ApplicationSet

**Files:**
- Create: `argo-apps/specht-labs-v2/lgtm.yaml`

- [ ] **Step 1: Create the ApplicationSet**

`argo-apps/specht-labs-v2/lgtm.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: lgtm
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - name: mimir
            path: kustomize/overlays/specht-labs-v2/mimir
            namespace: lgtm
          # LGTM stack scaffold. Uncomment each as it is migrated; add the
          # matching overlay under kustomize/overlays/specht-labs-v2/<name>.
          # - name: loki
          #   path: kustomize/overlays/specht-labs-v2/loki
          #   namespace: lgtm
          # - name: tempo
          #   path: kustomize/overlays/specht-labs-v2/tempo
          #   namespace: lgtm
          # - name: grafana
          #   path: kustomize/overlays/specht-labs-v2/grafana
          #   namespace: lgtm
  template:
    metadata:
      name: "{{name}}"
      namespace: argocd
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      destination:
        namespace: "{{namespace}}"
        server: https://kubernetes.default.svc
      project: default
      source:
        path: "{{path}}"
        repoURL: https://github.com/SpechtLabs/k8s-deployment.git
        targetRevision: main
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - ServerSideApply=true
          - SkipDryRunOnMissingResource=true
```

- [ ] **Step 2: Validate the ApplicationSet YAML**

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('argo-apps/specht-labs-v2/lgtm.yaml')); assert d['kind']=='ApplicationSet'; els=d['spec']['generators'][0]['list']['elements']; assert [e['name'] for e in els]==['mimir'], els; print('APPSET_OK: only mimir active')"
```
Expected: `APPSET_OK: only mimir active` (the loki/tempo/grafana entries are comments, so the live element list is `['mimir']`).

- [ ] **Step 3: Commit**

```bash
git add argo-apps/specht-labs-v2/lgtm.yaml
git commit -m "feat(lgtm): ApplicationSet scaffold (mimir live, loki/tempo/grafana stubbed)"
```

---

### Task 4: Final verification and PR

**Files:** none (verification + PR only)

- [ ] **Step 1: Re-render the base one more time from a clean state**

Run:
```bash
rm -rf kustomize/bases/mimir/charts 2>/dev/null; \
kustomize build --enable-helm kustomize/bases/mimir > /tmp/mimir-final.yaml && \
echo "workloads:" && awk '/^kind: (Deployment|StatefulSet)/{k=$2} /^  name: mimir-/{print k": "$2}' /tmp/mimir-final.yaml | sort -u | grep -viE 'headless|smoke|config|runtime|gossip|nginx'
```
Expected: 10 workloads — Deployments (distributor, gateway, overrides-exporter, querier, query-frontend, query-scheduler) and StatefulSets (compactor, ingester, kafka, store-gateway).

- [ ] **Step 2: Push the branch**

```bash
git push -u origin HEAD
```

- [ ] **Step 3: Open the PR (do NOT merge — hold until the Grafana Cloud trial ends)**

Use the pull-request skill, or:
```bash
gh pr create --base main --title "feat(lgtm): self-hosted multi-tenant Mimir on specht-labs-v2" --body-file - <<'EOF'
Stands up a right-sized Mimir (mimir-distributed 6.0.6, Kafka ingest-storage) in
an lgtm namespace so the Pi homelab and Home Assistant instances can remote-write
to durable Hetzner Object Storage instead of Grafana Cloud.

Tenants (X-Scope-OrgID injected per hostname on the tailnet Gateway):
- homelab            -> homelab-mimir.k8s.specht-labs.de
- hass               -> hass-mimir.k8s.specht-labs.de
- hass-schiltach     -> hass-schiltach-mimir.k8s.specht-labs.de

Only Mimir is live; the LGTM ApplicationSet has Loki/Tempo/Grafana stubbed.

Design: docs/superpowers/specs/2026-06-10-self-hosted-mimir-lgtm-design.md

Note: capacity is tight on the 3x cx23 workers (~11.7Gi total); Mimir+Kafka add
~1.8 vCPU / 3.6Gi of requests. Watch scheduling after first sync.
EOF
```

- [ ] **Step 4: Post-merge verification (run only after the PR is merged and ArgoCD syncs)**

```bash
export KUBECONFIG=~/.kube/configs/specht-labs
kubectl -n lgtm get pods                       # all Running/Ready
kubectl -n lgtm get pvc                        # ingester/store-gateway/compactor/kafka Bound
kubectl -n lgtm rollout status statefulset/mimir-ingester
# Tenant isolation smoke test (from a tailnet host):
#   write a sample to http://homelab-mimir.k8s.specht-labs.de/api/v1/push
#   query it back with X-Scope-OrgID: homelab  -> returns the sample
#   query it back with X-Scope-OrgID: hass      -> returns nothing
```
Expected: pods Ready, PVCs Bound, the sample visible only under its own tenant.

---

## Notes / risks

- Capacity: 3x cx23 workers (2 vCPU / ~3.9 Gi each) shared with argocd/envoy/cilium/alloy. Mimir+Kafka requests ~1.8 vCPU / 3.6 Gi. It fits but is tight; if pods stay Pending, the cheapest fix is one larger worker in a dedicated pool, or trimming Kafka's 1 CPU / 1Gi request.
- Single-node Kafka and RF1 ingester = no HA (matches the homelab posture). Kafka buffering means a restarting ingester replays rather than losing the unflushed window.
- Trust model: Mimir does not authenticate `X-Scope-OrgID`; isolation rests on the tailnet-only LB plus the Gateway being the only header-setting path. Per-tenant auth is a later add (see spec security section).
- The external write path depends on external-dns publishing `*.mimir.k8s.specht-labs.de` at the tailscale target; confirm the three hostnames resolve after sync.
```
