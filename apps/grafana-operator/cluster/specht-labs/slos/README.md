# Grafana SLO definitions

Service Level Objectives for SpechtLabs and homelab services, managed as code.

Each file is a `GrafanaManifest` wrapping a Grafana Cloud SLO
(`slo.ext.grafana.app/v1alpha1`, kind `SLO`). The grafana-operator on the
specht-labs cluster applies them through Grafana's app-platform API, like the
rule groups, contact point and notification policy next door: Argo CD syncs this
directory on merge to `main`. Nothing is pushed by hand. An SLO created or
edited in the UI or with `gcx` is overwritten (or, if it has no file here, left
unmanaged): add or change it here.

This is the **SLO half** of a hybrid model:

- **SLOs (here)** — error-budget objects with the native SLO UI and auto-generated
  burn alerts, applied by the grafana-operator.
- **Health targets** — instantaneous binary checks (synthetic down, no pods,
  under-replicated, immediate 5xx), delivered the operator-native way as a
  `GrafanaAlertRuleGroup` in
  `../grafanaalertrules-static-pages.yaml`
  (ArgoCD-applied). They are **not** duplicated here.

See [`docs/static-pages-slos.md`](../../../../../docs/static-pages-slos.md) for which
signal is an SLO vs. a health target and why.

## Files

| File | SLO | Objective |
|------|-----|-----------|
| `static-pages-proxy-availability.yaml` | Page-serving availability (non-5xx ratio) | 99.9% / 28d |
| `static-pages-proxy-latency.yaml` | Page-serving latency (<1s ratio) | 95% / 28d |
| `bogen-web-availability.yaml` | Bogen Web: non-5xx at the gateway | 99.5% / 28d |
| `bogen-web-latency.yaml` | Bogen Web: upstream answers < 1s | 98% / 28d |
| `tunnel-hornberg-availability.yaml` | Tunnel Hornberg: non-5xx at the gateway | 99.5% / 28d |
| `tunnel-hornberg-latency.yaml` | Tunnel Hornberg: upstream answers < 2.5s | 98% / 28d |
| `gibson-availability.yaml` | Gibson SSH: TCP connects forwarded (TCPRoute) | 99.5% / 28d |
| `mimir-ingest-availability.yaml` | Mimir pushes accepted (2xx at the distributor) | 99.9% / 28d |
| `loki-ingest-availability.yaml` | Loki pushes accepted | 99.9% / 28d |
| `tempo-ingest-availability.yaml` | Tempo OTLP/HTTP pushes accepted | 99.5% / 28d |
| `mimir-query-availability.yaml` | Mimir queries answered (no 5xx/499): the path every alert is evaluated through | 99.5% / 28d |
| `mimir-query-latency.yaml` | Mimir queries answered < 2.5s | 99% / 28d |
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

**specht-labs SLIs.** Apps behind Envoy Gateway are measured at the gateway
(`envoy_cluster_upstream_rq_xx` / `_rq_time` per `envoy_cluster_name`), not in the
pod: that leaves out kubelet probes, which make up most of what Beyla sees for the
small apps, and still counts a dead backend, because Envoy records its "no healthy
upstream" 503 there. Ingestion and query are measured by Beyla on the LGTM
distributors/query-frontend, which every writer and every alert evaluation goes
through. Ingestion counts any non-2xx as bad, including Mimir's 400 for tenant
series limits and Tempo's 429. Not SLOs: static-pages' upload API (too few,
mostly-403 requests), tka and ArgoCD (no user traffic, only probes), and stateful
failures. Those are health targets in
`apps/grafana-operator/cluster/specht-labs/grafanaalertrules-platform.yaml`, which also
alert when an SLO can't: telemetry missing, SLO recordings stopped, ingest
stalled. SLO ids must be ≤ 21 characters.

**Alerting.** Fast burn carries `severity: critical` (pages through Grafana IRM),
slow burn `severity: warning` (one push); routing is
`apps/grafana-operator/cluster/specht-labs/grafananotificationpolicy.yaml`.

## Changing an SLO

Edit or add the file here (and list a new one in `kustomization.yaml`), merge to
`main`, and Argo CD plus the operator do the rest. Check the result with:

```bash
kush exec specht-labs-admin@specht-labs -n grafana-operator -- kubectl get grafanamanifests
gcx slo definitions status        # read-only: SLI and error budget
```

The operator keeps the SLO's `metadata.name` as its UUID, so existing SLOs are
updated in place and keep their history.
