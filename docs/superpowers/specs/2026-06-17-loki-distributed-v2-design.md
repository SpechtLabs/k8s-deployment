# Self-hosted Loki on specht-labs-v2

**Date:** 2026-06-17
**Status:** Approved design, pending implementation plan

## Goal

Stand up a new, self-hosted Loki on the `specht-labs-v2` cluster, mirroring how
Mimir was set up there (`apps/mimir`). Logs are stored in a dedicated Hetzner
Object Storage bucket, separate from the Mimir blocks bucket. This is a brand-new
app (`apps/loki`); the v1 `apps/grafana-loki` (Backblaze B2, SimpleScalable) is
left untouched.

## Decisions

| Decision | Choice |
|---|---|
| Helm chart | `loki` chart `7.0.0` (Loki app `3.6.7`), `deploymentMode: Distributed` |
| Tenancy | `auth_enabled: true`, 4 per-tenant HTTPRoutes on the tailnet gateway |
| Log routing | Out of scope — k8s-monitoring keeps shipping logs to Grafana Cloud |
| Object storage | Hetzner bucket `specht-labs-loki-chunks` (already created), `hel1` endpoint |
| Namespace | `lgtm` |

The `loki` chart in `Distributed` mode is the maintained, latest-Loki path. The
separately-named `loki-distributed` chart is deprecated and lags on versions, so
it is not used.

## Layout

Mirrors `apps/mimir`:

```
apps/loki/
  base/
    kustomization.yaml          # helmCharts: loki 7.0.0, releaseName loki, ns lgtm, valuesFile helm-values.yaml
    helm-values.yaml            # Distributed mode, auth, s3, schema, per-component sizing
    charts/loki-7.0.0/          # vendored chart (downloaded by `kustomize build --enable-helm`, committed)
  cluster/specht-labs-v2/
    kustomization.yaml          # resources: ../../base + ./httproutes.yaml; generators: ./secret-generator.yaml
    httproutes.yaml             # 4 tenant HTTPRoutes -> loki-gateway
    loki-objstore.secret.yaml   # SOPS-encrypted: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (created by user)
    secret-generator.yaml       # ksops generator -> loki-objstore.secret.yaml
```

`base/kustomization.yaml` follows `apps/mimir/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: lgtm
helmCharts:
  - name: loki
    repo: https://grafana.github.io/helm-charts
    version: 7.0.0
    releaseName: loki
    namespace: lgtm
    valuesFile: helm-values.yaml
```

## Registration

In `argo-apps/specht-labs-v2/lgtm.yaml`, replace the commented loki stub with a
live list element (and correct the path from `grafana-loki` to `loki`):

```yaml
- name: loki
  path: apps/loki/cluster/specht-labs-v2
  namespace: lgtm
```

## Components

Distributed mode, RF1, 1 replica each:

- distributor, ingester, querier, query-frontend, query-scheduler, compactor,
  index-gateway, gateway (nginx)

Disabled for v1 (the Loki analog of Mimir's "not needed for v1" trims):

- ruler, bloom components (bloom-gateway / bloom-planner / bloom-builder),
  loki-canary, helm test
- **chunks cache and results cache (memcached)** — the chart defaults these to
  multi-GB allocations that would not fit a cx23 node. Disabled for v1; revisit
  if query latency warrants it.

## Resource sizing

Same guardrail as Mimir (`apps/mimir/base/helm-values.yaml`): **every component
gets an explicit memory limit; CPU requests only; no CPU limits.** Distributed
mode runs ~8 pods, heavier than the v1 SimpleScalable Loki, so tight memory caps
keep an ingester WAL replay or query burst from ballooning a pod and OOM-killing
a cx23 node (the failure mode that killed the kubelet on 2026-06-10). The
ingester gets the largest cap (it holds the in-memory chunks); query-scheduler
and gateway the smallest. Exact numbers are tuned in the implementation plan
against the cx23 memory budget.

## Storage

Single Hetzner bucket, tsdb store, schema v13:

```yaml
loki:
  auth_enabled: true
  storage:
    type: s3
    bucketNames:
      chunks: specht-labs-loki-chunks
      ruler: specht-labs-loki-chunks
      admin: specht-labs-loki-chunks
    s3:
      endpoint: hel1.your-objectstorage.com
      region: hel1
      accessKeyId: ${AWS_ACCESS_KEY_ID}
      secretAccessKey: ${AWS_SECRET_ACCESS_KEY}
      s3ForcePathStyle: true
      insecure: false
  schemaConfig:
    configs:
      - from: 2026-01-01
        store: tsdb
        object_store: s3
        schema: v13
        index:
          prefix: index_
          period: 24h
```

S3 credentials are delivered by the SOPS + ksops secret `loki-objstore` (env vars
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, matching the Mimir convention on
this cluster) and consumed via `extraEnvFrom` with `-config.expand-env=true`.

**Open implementation detail:** confirm against the vendored chart whether the
secret can be injected once via a global `extraEnvFrom` or must be set per
component (the v1 `grafana-loki` set it per `read`/`write`). Every component that
reads the storage config (ingester, querier, compactor, index-gateway, at least)
must have both the env-from and the `-config.expand-env=true` arg.

## Tenancy

`auth_enabled: true` with 4 HTTPRoutes on the `tailnet` Gateway
(`envoy-gateway-system`, `sectionName: http`), backend `loki-gateway:80`, each
injecting `X-Scope-OrgID` via a RequestHeaderModifier. Structure copied verbatim
from `apps/mimir/cluster/specht-labs-v2/httproutes.yaml` (explicit group/kind on
parentRefs/backendRefs and the default `/` PathPrefix match, to avoid permanent
ArgoCD OutOfSync from webhook defaulting).

| Hostname | Tenant (X-Scope-OrgID) |
|---|---|
| `homelab-loki.k8s.specht-labs.de` | homelab |
| `hass-loki.k8s.specht-labs.de` | hass |
| `hass-schiltach-loki.k8s.specht-labs.de` | hass-schiltach |
| `spechtlabs-loki.k8s.specht-labs.de` | spechtlabs |

`*.k8s.specht-labs.de` is served by external-dns via the Cloudflare/Tailscale
wildcard, so no per-host DNS record is needed.

## Out of scope (this change)

- Repointing k8s-monitoring `podLogsViaLoki` / `nodeLogs` to the in-cluster
  `loki-gateway`. Logs continue to Grafana Cloud; in-cluster ingestion is a
  follow-up once Loki is verified healthy.
- Ruler / alerting rules, retention enforcement, and limits tuning (chart
  defaults for v1).

## Verification

- `kustomize build --enable-helm apps/loki/cluster/specht-labs-v2 | kubeconform
  -ignore-missing-schemas -strict -summary -` passes (the repo's `check-apps`
  mise task).
- After the user encrypts the `loki-objstore` secret, the overlay renders with
  the secret generator and SOPS decrypts cleanly.
- Post-deploy: all Loki pods reach Ready on cx23 nodes without OOM; a test push
  with an `X-Scope-OrgID` header through one tenant route lands queryable logs.
