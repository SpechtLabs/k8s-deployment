# Self-hosted Pyroscope on specht-labs-v2

**Date:** 2026-06-18
**Status:** Approved design

## Goal

Stand up a new, self-hosted Pyroscope on the `specht-labs-v2` cluster, mirroring
how Mimir (`apps/mimir`) and Loki (`apps/loki`) were set up there. Continuous
profiles are stored in a dedicated Hetzner Object Storage bucket, separate from
the Mimir blocks and Loki chunks buckets. This is a brand-new app
(`apps/pyroscope`); there is no v1 `grafana-pyroscope` to leave untouched, so the
work is purely greenfield.

## Decisions

| Decision | Choice |
|---|---|
| Helm chart | `pyroscope` chart `2.1.0` (Pyroscope app `2.1.0`) |
| Topology | **Monolithic single-binary** (`architecture.microservices.enabled: false`) |
| Tenancy | `multitenancy_enabled: true`, 4 per-tenant HTTPRoutes on the tailnet gateway |
| Profile routing | Out of scope — no in-cluster profile shipping is wired up yet |
| Object storage | Hetzner bucket `specht-labs-pyroscope` (created by user), `hel1` endpoint |
| Namespace | `lgtm` |

### Why monolithic, not microservices

Loki's `Distributed` mode degrades cleanly to RF1 / 1-replica-per-component (~8
small pods). Pyroscope's microservices mode does **not**: the chart's
`architecture.microservices` defaults bake in RF3 and a 3-peer raft metastore
(`metastore.raft.bootstrap-expect-peers: 3`), with per-component memory limits of
8–16Gi. Forcing it to single replicas fights the chart and reproduces exactly the
OOM-the-node failure mode the Loki design warns about on cx23.

The chart's default **monolithic single-binary** mode runs the whole read/write/
compact path in one process against object storage. That is the pyroscope-
idiomatic small-scale path and the structural analog of the Loki design's intent
(object storage, RF1, a hard memory guardrail, fits a cx23 node), even though the
component layout differs from loki-distributed.

## Layout

Mirrors `apps/loki`:

```
apps/pyroscope/
  base/
    kustomization.yaml          # helmCharts: pyroscope 2.1.0, releaseName pyroscope, ns lgtm, valuesFile helm-values.yaml
    helm-values.yaml            # monolithic, multitenancy, s3, memory cap, PVC, subcharts off
    charts/pyroscope-2.1.0/     # chart cache, downloaded by `kustomize build --enable-helm` (gitignored, not committed)
  cluster/specht-labs-v2/
    kustomization.yaml          # resources: ../../base + ./httproutes.yaml + ./servicemonitor.yaml; generators: ./secret-generator.yaml
    httproutes.yaml             # 4 tenant HTTPRoutes -> pyroscope:4040 (http2)
    pyroscope-objstore.secret.yaml   # SOPS-encrypted: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (created by user)
    secret-generator.yaml       # ksops generator -> pyroscope-objstore.secret.yaml
    servicemonitor.yaml         # standalone ServiceMonitor for pyroscope's own metrics
```

`base/kustomization.yaml` follows `apps/loki/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: lgtm
helmCharts:
  - name: pyroscope
    repo: https://grafana.github.io/helm-charts
    version: 2.1.0
    releaseName: pyroscope
    namespace: lgtm
    valuesFile: helm-values.yaml
```

## Registration

In `argo-apps/specht-labs-v2/lgtm.yaml`, add a live list element next to mimir and
loki:

```yaml
- name: pyroscope
  path: apps/pyroscope/cluster/specht-labs-v2
  namespace: lgtm
```

## Components

Monolithic mode renders a single `pyroscope` StatefulSet plus its `pyroscope`,
`pyroscope-headless`, and `pyroscope-memberlist` Services. The HTTPRoute backend
is the `pyroscope` Service on port `4040` (named `http2`); there is no separate
nginx/gateway component in this chart (unlike Loki).

Disabled subcharts (the Pyroscope analog of Loki's "not needed for v1" trims):

- `alloy.enabled: false` and `agent.enabled: false` — the chart bundles an Alloy
  (or grafana-agent) StatefulSet to scrape and push profiles. Profile ingestion
  is out of scope for v1, so neither is deployed.
- `minio.enabled: false` — profiles live in Hetzner Object Storage, not bundled
  MinIO.

## Resource sizing

Same guardrail as Mimir and Loki: **the pod gets an explicit memory limit; CPU
request only; no CPU limit.** The single binary holds the in-memory profile head
and builds blocks, so the memory cap (~1Gi) is what makes a profile-ingest or
block-build burst OOM-kill the pyroscope pod itself rather than ballooning and
taking down the cx23 node (the failure that killed the kubelet on 2026-06-10).

The chart-recommended memory lever `pyroscopedb.max-block-duration` is lowered
from the 3h default to `30m`, so the in-memory head flushes to blocks (and to
object storage) more often and cannot grow unbounded between flushes. Exact
numbers are tuned during implementation against the cx23 memory budget.

## Storage

Single Hetzner bucket, S3 backend, set via `pyroscope.structuredConfig` (the
chart's default `config` only configures storage when bundled MinIO is enabled):

```yaml
pyroscope:
  structuredConfig:
    multitenancy_enabled: true
    storage:
      backend: s3
      s3:
        endpoint: hel1.your-objectstorage.com
        region: hel1
        bucket_name: specht-labs-pyroscope
        access_key_id: ${AWS_ACCESS_KEY_ID}
        secret_access_key: ${AWS_SECRET_ACCESS_KEY}
        insecure: false
```

S3 credentials are delivered by the SOPS + ksops secret `pyroscope-objstore` (env
vars `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, matching the Mimir/Loki
convention on this cluster), consumed via `pyroscope.extraEnvFrom` and expanded by
`-config.expand-env=true`. The render confirms the env-expansion arg renders from
`pyroscope.extraArgs: {config.expand-env: "true"}` and that `${AWS_*}` placeholders
survive into the rendered config file. `log.level` is overridden from the chart
default `debug` to `info`.

A PVC (`pyroscope.persistence.enabled: true`, ~10Gi) backs the local pyroscopedb
head/WAL so recent, not-yet-flushed profiles survive a pod restart — the analog of
the Loki ingester WAL claim.

## Tenancy

`multitenancy_enabled: true` with 4 HTTPRoutes on the `tailnet` Gateway
(`envoy-gateway-system`, `sectionName: http`), backend `pyroscope:4040`, each
injecting `X-Scope-OrgID` via a RequestHeaderModifier. Structure copied verbatim
from `apps/loki/cluster/specht-labs-v2/httproutes.yaml` (explicit group/kind on
parentRefs/backendRefs and the default `/` PathPrefix match, to avoid permanent
ArgoCD OutOfSync from webhook defaulting).

| Hostname | Tenant (X-Scope-OrgID) |
|---|---|
| `homelab-pyroscope.k8s.specht-labs.de` | homelab |
| `hass-pyroscope.k8s.specht-labs.de` | hass |
| `hass-schiltach-pyroscope.k8s.specht-labs.de` | hass-schiltach |
| `spechtlabs-pyroscope.k8s.specht-labs.de` | spechtlabs |

The routes are scaffolded for all 4 tenants up front (consistent with the Loki
spec), even though only the `spechtlabs` tenant — in-cluster instrumented apps —
will push profiles for now; Pi/Home-Assistant tenants emit logs, not pprof
profiles. `*.k8s.specht-labs.de` is served by external-dns via the
Cloudflare/Tailscale wildcard, so no per-host DNS record is needed.

## Monitoring

The chart's `serviceMonitor.enabled` is left `false`; a standalone ServiceMonitor
in the cluster overlay (Loki pattern) selects the pyroscope Service on the
`http2` port at `/metrics`. The grafana-k8s-monitoring alloy-metrics collector
discovers it and ships Pyroscope's own metrics to the self-hosted Mimir.

## Out of scope (this change)

- Wiring profile ingestion into the in-cluster `pyroscope` (k8s-monitoring /
  Alloy `pyroscope.receive`, or app-side pprof push). Profile shipping is a
  follow-up once Pyroscope is verified healthy.
- Tenant limits/overrides tuning and retention enforcement (chart defaults for
  v1).

## Verification

- `mise run check-apps` renders every app cluster overlay and validates with
  kubeconform; the pyroscope overlay must pass (`kustomize build
  --enable-alpha-plugins --enable-helm apps/pyroscope/cluster/specht-labs-v2 |
  kubeconform -ignore-missing-schemas -strict -summary -`).
- After the user encrypts the `pyroscope-objstore` secret, the overlay renders
  with the secret generator and SOPS decrypts cleanly.
- Post-deploy: the pyroscope pod reaches Ready on a cx23 node without OOM; a test
  profile push with an `X-Scope-OrgID` header through the spechtlabs route lands
  queryable profiles.
