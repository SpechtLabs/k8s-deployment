# Cut specht-labs-v2 k8s-monitoring over to self-hosted LGTM

**Date:** 2026-06-29
**Status:** Approved design

## Goal

The Grafana Cloud trial ends around 2026-07-01. Repoint the `specht-labs-v2`
`grafana-k8s-monitoring` Alloy collectors so every signal — metrics, logs,
traces, profiles, Beyla RED, cluster events, OpenCost — ships to the in-cluster
self-hosted LGTM stack (namespace `lgtm`, tenant `spechtlabs`) instead of Grafana
Cloud. After this change nothing the cluster collects is written to Cloud.

Scope is the **data-shipping layer only**. The viewing layer stays as-is: a
free-tier Cloud Grafana keeps querying self-hosted LGTM over the PDC tunnel, and
the `grafana-operator` datasources/dashboards are untouched. Moving the viewing
layer self-hosted is a separate, later effort.

The migration is already scaffolded: the `lgtm` namespace ships per-tenant
HTTPRoutes for `spechtlabs`, and `selfhosted-mimir` already exists as a
destination (ServiceMonitor/PodMonitor scrapes route there today). This change
finishes what those route comments anticipate ("when alloy-logs is later
repointed here").

## Decisions

| Decision | Choice |
|---|---|
| Routing | Alloy writes **directly** to in-cluster `*.lgtm.svc.cluster.local` services, not via the tailnet gateway hostnames |
| Tenant | `tenantId: spechtlabs` set explicitly on every destination (Mimir runs `multitenancy_enabled: true`) |
| OpenCost | Keep; repoint its query source to in-cluster Mimir; `customPricing` (Hetzner cx23) stays |
| Beyla / autoInstrumentation | Keep RED → Mimir, traces → Tempo; drop the Cloud-only Knowledge-Graph wiring |
| Viewing layer (PDC, Cloud Grafana, datasources) | Untouched |
| Cloud ingest secret (`grafana.secret.yaml`) | Left in place, unreferenced; optional follow-up prune |
| Edit target | `apps/grafana-k8s-monitoring/base/helm-values.yaml` is **v2-only** (labk3s inflates its own chart), so editing base touches only specht-labs-v2 |

### Why direct in-cluster services, not the gateway hostnames

The `spechtlabs-*.k8s.specht-labs.de` gateway routes exist for *external* clients
and inject the tenant header for them; the route comments state ingestion does
not depend on the gateway. In-cluster, writing straight to the service with an
explicit `tenantId` avoids a needless DNS + proxy hop and mirrors how
`selfhosted-mimir` already works. The tailnet-egress pattern that `cluster/labk3s`
uses is only needed because labk3s is a *different* cluster reaching v2 over the
tailnet; v2 reaches its own LGTM locally.

## In-cluster endpoints (namespace `lgtm`, tenant `spechtlabs`)

| Signal | Destination name | Type | URL |
|---|---|---|---|
| metrics | `selfhosted-mimir` *(exists)* | prometheus | `http://mimir-gateway.lgtm.svc.cluster.local/api/v1/push` |
| logs | `selfhosted-loki` *(new)* | loki | `http://loki-gateway.lgtm.svc.cluster.local/loki/api/v1/push` |
| traces | `selfhosted-tempo` *(new)* | otlp (traces only) | `http://tempo-distributor.lgtm.svc.cluster.local:4318` |
| profiles | `selfhosted-pyroscope` *(new)* | pyroscope | `http://pyroscope.lgtm.svc.cluster.local:4040` |

## Changes

### `apps/grafana-k8s-monitoring/base/helm-values.yaml`

**Destinations:**
- Remove `grafana-cloud-metrics`, `grafana-cloud-logs`, `gc-otlp-endpoint`,
  `grafana-cloud-profiles`.
- Remove `collectorCommon.alloy.remoteConfig` (Cloud Fleet Management — no
  self-hosted equivalent).
- Keep `selfhosted-mimir`; add the `container_id|image_id` labeldrop to its
  `metricProcessingRules` (cardinality control, matching labk3s). The argocd
  Knowledge-Graph relabel exception lived inside `grafana-cloud-metrics`, so it
  is gone once that destination is removed.
- Add `selfhosted-loki`, `selfhosted-tempo`, `selfhosted-pyroscope` per the table
  above, each with `tenantId: spechtlabs`. `selfhosted-tempo` enables `traces`
  only (`metrics` / `logs` disabled).

**Feature → destination routing** (each is currently on a Cloud destination or
defaults to one):

| Feature | New destination(s) |
|---|---|
| `clusterMetrics`, `hostMetrics`, `costMetrics`, `annotationAutodiscovery` | `[selfhosted-mimir]` |
| `clusterEvents`, `nodeLogs`, `podLogsViaLoki`, `kubernetesManifests` | `[selfhosted-loki]` |
| `applicationObservability` | `[selfhosted-mimir, selfhosted-loki, selfhosted-tempo]` |
| `autoInstrumentation` (Beyla RED) | `[selfhosted-mimir]` (traces already flow via `deliverTracesToApplicationObservability` → Tempo) |
| `profiling` (eBPF) | `selfhosted-pyroscope` |

**OpenCost** (`telemetryServices.opencost`):
- `metricsSource: selfhosted-mimir`.
- Drop the Cloud `prometheus.external.url` and `existingSecretName`; let the chart
  derive the query URL + `X-Scope-OrgID: spechtlabs` from the destination.
- Keep `customPricing` (Hetzner cx23 net EUR) and `exporter.defaultClusterId`.

### `apps/argocd/cluster/specht-labs-v2/kustomization.yaml`

Remove the `scrape-to-cloud` component reference and the argocd-server
Knowledge-Graph scrape annotation patch. `components/scrape-to-cloud` stays in
the repo (reusable), just unwired from argocd.

### Left untouched

PDC agent (`pdc-agent.yaml`, `pdc.secret.yaml`), Cloud Grafana frontend,
`grafana-operator` datasources/dashboards. `grafana.secret.yaml` (Cloud ingest
tokens) becomes unreferenced but stays on disk — a SOPS secret is not deleted
casually, and keeping it makes rollback trivial. Pruning it is an optional
follow-up.

## Risks / things to prove at render time

1. **OpenCost tenant header.** The chart must inject `X-Scope-OrgID: spechtlabs`
   into OpenCost's queries against multitenant Mimir when `metricsSource` points
   at `selfhosted-mimir`. If the rendered Deployment lacks the header, add it via
   `opencost.extraEnv` (or a per-query header config). This is the one unproven
   detail.
2. **`profiling` destination selection.** The chart should route `profiling` to
   the sole pyroscope-type destination automatically; set it explicitly if the
   render shows otherwise.
3. **No Cloud leakage.** Rendered output must contain zero `grafana.net` URLs.

## Verification

- `kustomize build --enable-helm apps/grafana-k8s-monitoring/cluster/specht-labs-v2`
  renders clean (mise-provided `kustomize` + `helm`).
- `grep grafana.net` over the render returns nothing.
- kubeconform CI passes.
- Post-sync: the `spechtlabs` tenant shows fresh series, logs, traces and
  profiles; the existing Cloud datasources (via PDC) render them.

## Rollback

Revert the commit. Cloud destinations and the Fleet-Management config come back;
`grafana.secret.yaml` and the PDC agent never left, so the old path is intact.
