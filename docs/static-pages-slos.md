# Static Pages — SLOs & health targets

Research notes and rationale behind the Static Pages SLOs in
[`../grafana/slos/`](../grafana/slos/) and the
[`Static Pages / Overview`](../kustomize/bases/grafana-dashboards/static-pages/static-pages.json)
dashboard. Every number here is taken from live telemetry (Grafana Cloud
`grafanacloud-prom`, `service_name="static-pages"`), not assumed.

> Data windows: "clean baseline" = the 3 days ending 2026-06-16; "30d" = the
> trailing 30 days, which still contains the resolved 502 incident.

## 1. What Static Pages actually emits

There are **no hand-written metrics** in the app. Observability comes from three
layers, each of which gives a different SLI surface:

| Source | Metrics | Covers |
|--------|---------|--------|
| Beyla (eBPF) | `http_server_request_duration_seconds_*` | **Page-serving proxy** — the user-facing signal. Has `http_request_method`, `http_response_status_code`, `http_route`, `cluster`, `k8s_pod_name`. |
| `go-gin-prometheus` | `staticpages_request*` | **Upload API** only (`:8081`). Very low volume (CI-triggered). |
| OTel traces → span-metrics | `traces_spanmetrics_*` + Tempo | Per-request traces with rich `proxy.*` attributes. Drill-down target from the dashboard. |
| Synthetic Monitoring | `probe_*` | **External blackbox** — one active scripted check ("platform") from 3 locations (Frankfurt, N. California, Singapore). |

The reverse proxy is a `httputil.ReverseProxy`, **not** gin, so it is invisible to
`staticpages_*`. The user-facing SLIs therefore come from **Beyla**, not the app's
own Prometheus metrics. This is the single most important fact for SLO design here.

## 2. The baseline (and the trap in it)

Naive 30-day availability (non-5xx / total) = **95.65%** — which looks like a
barely-two-nines service. That number is a **trap**:

- All 4,469 of the 28-day 5xx responses are **502s from a single incident**
  (2026-06-05 → 2026-06-12, peaking ~1,500 / 3h on Jun 10–11).
- The incident resolved at ~2026-06-12 18:00, coinciding with commit `70e6a25`.
- Since then: **0 5xx**. Steady-state availability is **≈100%**.

Setting an SLO against the incident-contaminated 30d window would bake the outage
into the target and hide the next one. **The targets below are derived from the
clean post-fix baseline** (the choice made when this was scoped).

Other baseline facts:

- **404 is ~38% of GET traffic** (12.5k of 33k over 3d). For a static host this is
  a *correct, served* response, not a failure — so 404 is **excluded from the
  error definition**. Counting it as an error would report ~62% "availability",
  which is meaningless.
- **403 on the upload API is an expected OIDC auth rejection**, not a service
  error (5,588 over 30d).
- Latency: p50 124ms, p90 491ms, **p99 2.25s**. The long tail is the 404 fallback
  path (multi-path probe fan-out): 2xx requests are 98.2% < 1s, but 404s are only
  95.3% < 1s.

## 3. Recommended SLOs

Two request-based SLOs on the proxy, both aspirational from the clean baseline:

### Availability — 99.9% over 28d
- **SLI**: `http_server_request_duration_seconds_count{...,code!~"5.."}` / total.
- **Budget**: at ~94.9k GET/28d, 0.1% ≈ **~95 failed requests / 28d**.
- **Steady-state burn**: ~0 (no 5xx since the fix) → full budget headroom.
- **What it catches**: a 502 recurrence. The June incident (4,469 × 5xx) was
  **~47× the budget** — fast-burn alerts would have paged within minutes.

### Latency — 95% of requests < 1s over 28d
- **SLI**: `http_server_request_duration_seconds_bucket{le="1.0"}` / total.
- **Baseline**: 97.4% blended. Budget = 5%; steady-state consumes ~52% of it.
- **Caveat / refinement**: the blended ratio mixes fast 2xx (98.2% < 1s) with the
  slow 404 fallback (95.3% < 1s). Because 404s are 38% of traffic, they dominate
  the budget. If 404 latency is considered "don't care", scope the SLI to served
  content (`code=~"2..|3.."`) and the baseline rises to ~98.2%, allowing a tighter
  96–97% target. Kept blended for v1 because slow 404s are still a real user
  experience; revisit once the proxy probe path is redesigned.

> Not turned into SLOs (deliberately): **upload API** and **synthetic uptime** —
> see §4.

## 4. SLOs vs. health targets for Static Pages

A **health target** is a threshold on a current-state signal ("probe is up",
"pods ≥ 2", "cert > 14 days"): binary, instantaneous, alert-on-breach. An **SLO**
is a ratio of good events over a rolling window with an **error budget** and
burn-rate alerting. They answer different questions — "is it healthy *right now*?"
vs. "have we been good *enough* over the last 28 days?" Static Pages needs both,
and which fits depends on the signal:

| Signal | SLO or health target? | Why |
|--------|----------------------|-----|
| Proxy availability (5xx) | **SLO** | High, steady request volume → ratios are statistically meaningful; an error budget tolerates blips while catching sustained burn. |
| Proxy latency (<1s) | **SLO** | Same — enough events to make a percentile/ratio trustworthy. |
| Synthetic check (`probe_success`) | **Health target** | One scripted check from 3 probes ≈ a few samples/min. A "99.9% of probes" ratio is dominated by tiny sample counts and flaps on a single transient failure. Treat it as a heartbeat: *currently up?* and *uptime over a window for reporting*, alert on consecutive failures, not on a budget. |
| Upload API (`staticpages_*`) | **Health target** | Traffic is near-zero and bursty (CI pushes); the dominant code is an *expected* 403 auth rejection. A request-ratio SLO would be all noise — a handful of requests can swing it from 100% to 0%. Watch "did the last upload succeed?" and process health instead. |
| Pods up / restarts / FDs / cert expiry | **Health target** | State, not events. No "budget" semantics — you want a hard line and an immediate page. |

### The core trade-off

- **SLOs** decouple alerting from instantaneous noise. A 502 blip that recovers in
  seconds burns a sliver of budget and does **not** page; a sustained burn does.
  That is exactly right for the proxy, where occasional origin hiccups are
  expected and only *sustained* failure hurts users. The cost is that SLOs need
  **volume** to be meaningful and a **window** before they react — useless for a
  cert that expires or a check that's flat-out down.
- **Health targets** are simple, instantaneous, and unambiguous — ideal for
  low-volume or binary signals (synthetic check, upload API, pod count, cert
  expiry). The cost is alert noise: every transient breach is a potential page,
  with no notion of "we can absorb a few".

For a low-traffic, mostly-static service like this one, the failure mode of
over-SLO-ing is real: turning the synthetic check or the upload API into
request-ratio SLOs produces flaky budgets driven by tiny sample sizes. The clean
split is **SLOs for the high-volume proxy golden signals, health targets for
everything blackbox / low-volume / stateful.** The dashboard reflects this — the
proxy rows carry SLI thresholds, while synthetic, API, and runtime rows are
plain health panels.

## 5. Delivery (GitOps)

grafana-operator manages Grafana Cloud as an **external** instance
(`instanceSelector: {dashboards: grafana-cloud}`), but it has **no SLO CRD**.
So delivery is hybrid, split by what each tool can own:

| Artifact | Mechanism | Location |
|----------|-----------|----------|
| Dashboard | grafana-operator `GrafanaDashboard` + `configMapRef` (ArgoCD) | `overlays/specht-labs-v2/grafana-operator/grafanadashboards-static-pages.yaml` (JSON in `bases/grafana-dashboards/static-pages/`) |
| **Health targets** | grafana-operator `GrafanaAlertRuleGroup` (ArgoCD) | `overlays/specht-labs-v2/grafana-operator/grafanaalertrules-static-pages.yaml` |
| Folder ("Applications") | grafana-operator `GrafanaFolder` (ArgoCD) | `overlays/specht-labs-v2/grafana-operator/grafana-applications-folder.yaml` |
| **SLOs** (error budgets) | Grafana Cloud SLO plugin via `gcx slo definitions push` | `grafana/slos/` |

Everything except the SLO objects is operator-native and ArgoCD-applied in the
v2 overlay. The SLOs stay in the SLO plugin (for the error-budget UI and reporting)
and are the only piece synced outside ArgoCD. The dashboard also keeps a v1
sidecar entry in `bases/grafana-dashboards/kustomization.yaml` for the
self-hosted-Grafana cluster.

### Health targets shipped

`GrafanaAlertRuleGroup/static-pages-health` (all verified against live data):

| Rule | Fires when | Severity |
|------|-----------|----------|
| `sp-synthetic-down` | `avg(probe_success) < 0.5` for 5m | critical |
| `sp-target-absent` | `sum(up) < 1` for 5m | critical |
| `sp-under-replicated` | `sum(up) < 2` for 15m | warning |
| `sp-proxy-5xx` | 5xx ratio `> 2%` for 10m | warning |

The SLO **burn-rate** alerts are intentionally not in this group — the SLO plugin
generates its own fast/slow-burn alerts from the definitions in `grafana/slos/`.

## 6. Open follow-ups

- **Route the alerts**: the health rules and SLO burn alerts currently use the
  default notification policy. Add a `GrafanaContactPoint` + notification policy
  (or OnCall integration) and set `notificationSettings` on the group.
- **Scope latency to 2xx** once the proxy 404-probe path is redesigned (the
  HEAD-probe-then-GET fan-out is the documented source of the slow tail).
- **Per-domain SLOs**: Beyla currently labels by service, not by hosted domain.
  If per-tenant objectives are wanted, derive them from span-metrics
  (`proxy.domain`) or per-route synthetic checks.
- **Cert-expiry health target** once SSL probing is enabled
  (`probe_ssl_earliest_cert_expiry` has no data today).
