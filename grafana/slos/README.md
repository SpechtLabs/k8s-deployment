# Grafana SLO definitions

Service Level Objectives for SpechtLabs and homelab services, managed as code.

Grafana Cloud SLOs are **not** Kubernetes resources — the grafana-operator has no
SLO CRD (it ships `GrafanaAlertRuleGroup`, `GrafanaContactPoint`, … but no `SLO`
kind) — so these are synced with `gcx` against the Grafana Cloud SLO API.

This is the **SLO half** of a hybrid model:

- **SLOs (here)** — error-budget objects with the native SLO UI and auto-generated
  burn alerts, synced via `gcx slo definitions push`.
- **Health targets** — instantaneous binary checks (synthetic down, no pods,
  under-replicated, immediate 5xx), delivered the operator-native way as a
  `GrafanaAlertRuleGroup` in
  `apps/grafana-operator/cluster/specht-labs/grafanaalertrules-static-pages.yaml`
  (ArgoCD-applied). They are **not** duplicated here.

See [`../../docs/static-pages-slos.md`](../../docs/static-pages-slos.md) for which
signal is an SLO vs. a health target and why.

## Files

| File | SLO | Objective |
|------|-----|-----------|
| `static-pages-proxy-availability.yaml` | Page-serving availability (non-5xx ratio) | 99.9% / 28d |
| `static-pages-proxy-latency.yaml` | Page-serving latency (<1s ratio) | 95% / 28d |
| `homelab-buckle-availability.yaml` | Buckle UI/API answers `/readyz` | 99.5% / 28d |
| `homelab-tsidp-availability.yaml` | tsidp serves its OIDC discovery | 99.9% / 28d |
| `homelab-home-assistant-availability.yaml` | Home Assistant answers | 99.5% / 28d |
| `homelab-labk3s-api-availability.yaml` | labk3s API server answers (401: k3s has no anonymous auth) | 99.5% / 28d |
| `homelab-nas-dsm-availability.yaml` | Synology DSM answers | 99.5% / 28d |
| `homelab-jellyfin-availability.yaml` | Jellyfin `/health` through svc:stream | 99.5% / 28d |
| `homelab-ceph-availability.yaml` | Ceph not HEALTH_ERR and every PG active | 99.9% / 28d |
| `homelab-clock-accuracy-ptp.yaml` | PTP clients within 10 µs of their source | 99.5% / 28d |
| `homelab-clock-accuracy-ntp.yaml` | NTP clients within 100 µs of their source | 99.5% / 28d |
| `homelab-timepi-stratum1.yaml` | timepi on GPS PPS (stratum 1) | 80% / 28d (antenna-bound; never pages) |

**Data sources.** Each SLO's `destinationDatasource` is the self-hosted Mimir
tenant its metrics live in (`mimir-homelab`, `mimir-spechtlabs`): the SLO plugin
evaluates its recording rules there and writes the SLI next to the raw metrics.
(`sourceDatasourceUid` from the SLO API docs is ignored by this stack.) The
homelab availability SLIs are `probe_success{job="blackbox", service}` from
Alloy's black-box exporter on isa, every 30 s (cedi/homelab,
`vars/group-o11y-collector.yaml`).

**Alerting.** Fast burn carries `severity: critical` (pages through Grafana IRM),
slow burn `severity: warning` (one push); routing is
`apps/grafana-operator/cluster/specht-labs/grafananotificationpolicy.yaml`.

## Sync

```bash
# Preview
gcx slo definitions push grafana/slos/*.yaml --dry-run

# Apply
gcx slo definitions push grafana/slos/*.yaml

# Inspect live status + error budget
gcx slo definitions status
```

Pushing an SLO auto-generates its fast-burn / slow-burn alert rules in Grafana.

## CI (optional)

To make this true GitOps, run the push from CI on merge to `main` (the runner
needs a Grafana Cloud token with SLO write access exported as the usual `gcx`
auth env vars):

```yaml
- run: gcx slo definitions push grafana/slos/*.yaml
```
