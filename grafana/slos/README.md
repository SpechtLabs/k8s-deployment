# Grafana SLO definitions

Service Level Objectives for SpechtLabs services, managed as code.

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

The rationale, the data the targets are derived from, and the SLO-vs-health-target
trade-off analysis live in [`../../docs/static-pages-slos.md`](../../docs/static-pages-slos.md).

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
