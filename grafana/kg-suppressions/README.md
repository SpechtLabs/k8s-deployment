# Knowledge Graph alert suppressions

Suppressions for Grafana Cloud **Asserts / Knowledge Graph** assertions — the signals that
color the Entity Graph red — managed as code.

Like SLOs (see [`../slos`](../slos)), KG suppressions are **not** Kubernetes resources: the
grafana-operator has no CRD for them, so they are synced with `gcx` against the Knowledge
Graph API rather than applied by ArgoCD.

## What belongs here (and what does not)

Only assertions that are **benign-by-design** or a **cascade of a signal already owned
elsewhere** (an SLO or a health-target alert). Suppressing does **not** drop telemetry —
metrics and traces keep flowing; only the graph-coloring assertion is disabled.

Do **not** suppress a real, user-impacting failure. If page-serving breaks, that must show
up via the [static-pages SLOs](../slos) and health alerts — not be hidden here.

## Current suppressions

| Suppression | Why it is noise |
|-------------|-----------------|
| `mimir-tenant-deletion-marker-404` | Compactor polls object storage for a deletion marker that doesn't exist; the expected 404 is miscounted as a span error. |
| `mimir-internal-push-p99-buildup` | Auto-threshold p99 anomaly on Mimir's internal `/api/v1/push` (~190ms); object storage is fast. Real latency signal is Mimir's own dashboards/SLOs. |
| `tailscale-operator-saas-log-latency` | Latency anomaly shipping logs to `log.tailscale.com` (Tailscale SaaS) — external dependency, not a cluster fault. |
| `argocd-repo-server-span-errors` / `-span-anomalies` | Internal gRPC/Redis mesh + (pending-fix) OTLP-export span errors on repo-server. |
| `argocd-application-controller-span-errors` / `-span-anomalies` | Cascade of repo-server RPC failures on the application controller. |
| `argocd-server-span-errors` / `-span-anomalies` | API-server internal gRPC/Redis span mesh (AGGREGATED). |
| `grafana-operator-grafanacloud-client-errors` | ~1 req/min client errors to the Grafana Cloud API; self-recovering. |
| `static-pages-cdn-resets-and-4xx` | CDN keepalive resets (app falls back to direct B2 — SLO stays 100%) + bot 4xx. |
| `envoy-gateway-static-pages-cascade` | Shared gateway is red only because it proxies to static-pages above. |

## Sync

```bash
# Apply
gcx kg suppressions create -f grafana/kg-suppressions/suppressions.yaml

# Inspect live suppressions
gcx kg suppressions list

# Remove one
gcx kg suppressions delete <name>
```

The Entity Graph reads `asserts:*` recording rules and `traces_*` series over a query
lookback window, so old red state lingers for ~5–15 min after a suppression is applied
before the graph fully stabilizes.

## CI (optional)

To make this true GitOps, run the sync from CI on merge to `main` (the runner needs a
Grafana Cloud token with Knowledge Graph write access exported as the usual `gcx` auth
env vars):

```yaml
- run: gcx kg suppressions create -f grafana/kg-suppressions/suppressions.yaml
```
