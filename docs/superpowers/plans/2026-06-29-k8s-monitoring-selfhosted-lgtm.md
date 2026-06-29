# Cut specht-labs-v2 k8s-monitoring to self-hosted LGTM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint the `specht-labs-v2` `grafana-k8s-monitoring` Alloy collectors so every signal (metrics, logs, traces, profiles, Beyla RED, cluster events, OpenCost) ships to the in-cluster self-hosted LGTM stack instead of Grafana Cloud, before the Cloud trial ends ~2026-07-01.

**Architecture:** `apps/grafana-k8s-monitoring/base/helm-values.yaml` is the v2-only chart config (labk3s inflates its own chart, so editing base touches only v2). Replace the four Grafana Cloud push destinations + Fleet Management with four in-cluster LGTM destinations (`*.lgtm.svc.cluster.local`, tenant `spechtlabs`), re-route every feature to them, repoint OpenCost's query source to in-cluster Mimir, and drop the Cloud-only Knowledge-Graph scrape on argocd. The viewing layer (PDC, Cloud Grafana, grafana-operator datasources) is left untouched.

**Tech Stack:** Kustomize 5.8.1 + Helm 4.2.1 (helm inflation via `kustomize build --enable-helm`), kubeconform 0.8.0, ksops 4.5.1 + SOPS/age, all pinned in `mise.toml`. Chart: `k8s-monitoring` 4.1.6. GitOps via ArgoCD; deploy = commit to `main`.

## Global Constraints

- All tools run through mise: `mise exec -- <tool>` or `mise run <task>`. Never install tools another way.
- In-cluster LGTM lives in namespace `lgtm`; the cluster's own tenant is `spechtlabs` (set via `tenantId`, which the chart renders as `X-Scope-OrgID`). Mimir/Loki/Tempo/Pyroscope all run `multitenancy_enabled: true`.
- In-cluster endpoints (tenant `spechtlabs`): metrics `http://mimir-gateway.lgtm.svc.cluster.local/api/v1/push`; logs `http://loki-gateway.lgtm.svc.cluster.local/loki/api/v1/push`; traces (OTLP/HTTP) `http://tempo-distributor.lgtm.svc.cluster.local:4318`; profiles `http://pyroscope.lgtm.svc.cluster.local:4040`; Mimir PromQL query base `http://mimir-gateway.lgtm.svc.cluster.local/prometheus`.
- `scrapeInterval: 60s` stays (cardinality/storage lever).
- Commit directly to `main` (house style, no feature branches/PRs).
- House CI gate: `mise run check` (renders every `apps/*/cluster/*` overlay through kustomize+helm and validates with kubeconform). Must stay green.
- Do NOT touch: `pdc-agent.yaml`, `pdc.secret.yaml`, or anything under `grafana-operator`/`components/grafana-*`.
- `secret-generator.yaml` IS edited (correction found at render time): removing the Cloud destinations + `remoteConfig` strands the nine `behavior: replace` SOPS secrets in `grafana.secret.yaml` (no chart-rendered base to replace → overlay fails to render). Drop the `- ./grafana.secret.yaml` line from `cluster/specht-labs-v2/secret-generator.yaml` (keep `pdc.secret.yaml`). Leave the `grafana.secret.yaml` file on disk, dormant. (Applied during execution as a follow-up fix commit after the full-overlay render surfaced it.)

---

### Task 1: Repoint base helm-values to self-hosted LGTM + drop the obsolete OpenCost patch

**Files:**
- Modify (full rewrite): `apps/grafana-k8s-monitoring/base/helm-values.yaml`
- Modify: `apps/grafana-k8s-monitoring/base/kustomization.yaml` (remove the now-obsolete json6902 OpenCost `CONFIG_PATH` patch)

**Interfaces:**
- Produces: destinations named `selfhosted-mimir`, `selfhosted-loki`, `selfhosted-tempo`, `selfhosted-pyroscope`. No later task depends on these names; Task 2 is independent.

**Why the kustomization patch is removed:** the existing json6902 patch strips a *duplicate* `CONFIG_PATH=/tmp` env from the OpenCost Deployment at hardcoded index 22. Setting the Mimir tenant header via `opencost.exporter.extraEnv` overrides the wrapper default that produced that duplicate, so the render now contains exactly one `CONFIG_PATH` (`/tmp/custom-config`). The patch's `test` op at index 22 fails (verified by trial render: `testing value /spec/template/spec/containers/0/env/22/name failed`), and there is no longer any duplicate to remove. Remove the patch.

- [ ] **Step 1: Replace `apps/grafana-k8s-monitoring/base/helm-values.yaml` with the full content below**

```yaml
cluster:
  name: specht-labs
global:
  # Pin metrics collection to 1/min. Keeps self-hosted Mimir series churn and
  # block storage down; also the chart default, set explicitly so a chart bump
  # can't silently lower it.
  scrapeInterval: 60s
destinations:
  # Self-hosted LGTM on this cluster (lgtm namespace), tenant `spechtlabs`.
  # In-cluster writes, no auth; tenantId sets X-Scope-OrgID (Mimir/Loki/Tempo/
  # Pyroscope all run multitenancy). Plain HTTP — traffic stays on the cluster network.
  selfhosted-mimir:
    type: prometheus
    url: http://mimir-gateway.lgtm.svc.cluster.local/api/v1/push
    tenantId: spechtlabs
    metricProcessingRules: |
      write_relabel_config {
        regex = "container_id|image_id"
        action = "labeldrop"
      }
  selfhosted-loki:
    type: loki
    url: http://loki-gateway.lgtm.svc.cluster.local/loki/api/v1/push
    tenantId: spechtlabs
  selfhosted-tempo:
    type: otlp
    url: http://tempo-distributor.lgtm.svc.cluster.local:4318
    protocol: http
    tenantId: spechtlabs
    metrics:
      enabled: false
    logs:
      enabled: false
    traces:
      enabled: true
  selfhosted-pyroscope:
    type: pyroscope
    url: http://pyroscope.lgtm.svc.cluster.local:4040
    tenantId: spechtlabs
clusterMetrics:
  enabled: true
  collector: alloy-metrics
  destinations: [selfhosted-mimir]
hostMetrics:
  enabled: true
  collector: alloy-metrics
  destinations: [selfhosted-mimir]
  linuxHosts:
    enabled: true
  windowsHosts:
    enabled: false
  energyMetrics:
    enabled: false
costMetrics:
  enabled: true
  collector: alloy-metrics
  destinations: [selfhosted-mimir]
annotationAutodiscovery:
  enabled: true
  collector: alloy-metrics
  destinations: [selfhosted-mimir]
prometheusOperatorObjects:
  enabled: true
  collector: alloy-metrics
  destinations: [selfhosted-mimir]
clusterEvents:
  enabled: true
  collector: alloy-singleton
  destinations: [selfhosted-loki]
nodeLogs:
  enabled: true
  collector: alloy-logs
  destinations: [selfhosted-loki]
podLogsViaLoki:
  enabled: true
  collector: alloy-logs
  destinations: [selfhosted-loki]
kubernetesManifests:
  enabled: true
  collector: alloy-singleton
  destinations: [selfhosted-loki]
applicationObservability:
  enabled: true
  collector: alloy-receiver
  # App metrics -> Mimir, logs -> Loki, traces -> Tempo.
  destinations: [selfhosted-mimir, selfhosted-loki, selfhosted-tempo]
  receivers:
    otlp:
      grpc:
        enabled: true
        port: 4317
      http:
        enabled: true
        port: 4318
    zipkin:
      enabled: true
      port: 9411
autoInstrumentation:
  enabled: true
  collector: alloy-metrics
  # Beyla RED -> Mimir; Beyla traces flow via applicationObservability -> Tempo.
  destinations: [selfhosted-mimir]
  beyla:
    deliverTracesToApplicationObservability: true
profiling:
  enabled: true
  collector: alloy-profiles
  # Auto-routes to the sole pyroscope-type destination (selfhosted-pyroscope);
  # the feature takes no explicit `destinations` list.
  ebpf:
    enabled: true
collectors:
  alloy-metrics:
    presets:
      - clustered
      - statefulset
  alloy-singleton:
    presets:
      - singleton
  alloy-logs:
    presets:
      - filesystem-log-reader
      - daemonset
  alloy-receiver:
    presets:
      - deployment
  alloy-profiles:
    presets:
      - privileged
      - daemonset
# collectorCommon.alloy.remoteConfig (Grafana Cloud Fleet Management) removed —
# no self-hosted equivalent; collectors run their rendered config.
telemetryServices:
  kube-state-metrics:
    deploy: true
  node-exporter:
    deploy: true
  windows-exporter:
    deploy: false
  opencost:
    deploy: true
    metricsSource: selfhosted-mimir
    opencost:
      exporter:
        defaultClusterId: specht-labs
        # Mimir runs multitenancy_enabled: true — OpenCost must send the tenant
        # org id on its PromQL queries or Mimir answers 401. Setting this also
        # overrides the wrapper's default CONFIG_PATH=/tmp, removing the duplicate
        # CONFIG_PATH that the (now-deleted) base kustomization patch guarded against.
        extraEnv:
          PROMETHEUS_HEADER_X_SCOPE_ORGID: spechtlabs
      prometheus:
        # Mimir's PromQL API lives under /prometheus (not the /api/v1/push write path).
        external:
          url: http://mimir-gateway.lgtm.svc.cluster.local/prometheus
      customPricing:
        enabled: true
        costModel:
          description: Hetzner Cloud CPX22 pricing, net EUR.
          CPU: 0.0032
          RAM: 0.0016
          GPU: 0
          storage: 0
          zoneNetworkEgress: 0
          regionNetworkEgress: 0
          internetNetworkEgress: 1
  kepler:
    deploy: false
  k8s-manifest-tail:
    deploy: true
    config:
      objects:
        - apiVersion: v1
          kind: Pod
        - apiVersion: apps/v1
          kind: Deployment
        - apiVersion: apps/v1
          kind: StatefulSet
        - apiVersion: apps/v1
          kind: DaemonSet
```

- [ ] **Step 2: Remove the obsolete json6902 OpenCost patch from `apps/grafana-k8s-monitoring/base/kustomization.yaml`**

Delete the entire `patches:` block (the OpenCost `CONFIG_PATH` test/remove patch and its comment), leaving only the `helmCharts:` section. The file must end as:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring

helmCharts:
  - name: k8s-monitoring
    repo: https://grafana.github.io/helm-charts
    version: 4.1.6
    releaseName: grafana-k8s-monitoring
    namespace: monitoring
    valuesFile: helm-values.yaml

  - name: alloy-crd
    repo: https://grafana.github.io/helm-charts
    version: 1.0.0
    releaseName: grafana-alloy-crd
    namespace: monitoring
```

> Note: the `k8s-monitoring` chart version must match whatever is currently pinned in the repo (renovate keeps it current — `4.1.6` at plan time, also used by the labk3s overlay). Do not downgrade it; only the `valuesFile` content and the removal of the `patches:` block are this task's changes to the kustomization.

- [ ] **Step 3: Render base and verify it succeeds (the json6902 test no longer blocks it)**

Run:
```bash
mise exec -- kustomize build --enable-helm apps/grafana-k8s-monitoring/base > /tmp/v2-mon.yaml && echo "RENDER OK ($(wc -l < /tmp/v2-mon.yaml) lines)"
```
Expected: `RENDER OK ...` (no `testing value .../env/22/name failed`).

- [ ] **Step 4: Assert zero Grafana Cloud leakage**

Run:
```bash
grep -nE "grafana\.net|grafana-cloud|fleet-management|REPLACE_ME" /tmp/v2-mon.yaml || echo "CLEAN: no cloud references"
```
Expected: `CLEAN: no cloud references`.

- [ ] **Step 5: Assert all self-hosted endpoints + tenant are wired**

Run:
```bash
grep -oE "http://(mimir-gateway|loki-gateway|tempo-distributor|pyroscope)\.lgtm\.svc\.cluster\.local[^\" ]*" /tmp/v2-mon.yaml | sort -u
```
Expected exactly these five lines:
```
http://loki-gateway.lgtm.svc.cluster.local/loki/api/v1/push
http://mimir-gateway.lgtm.svc.cluster.local/api/v1/push
http://mimir-gateway.lgtm.svc.cluster.local/prometheus
http://pyroscope.lgtm.svc.cluster.local:4040
http://tempo-distributor.lgtm.svc.cluster.local:4318
```

- [ ] **Step 6: Assert OpenCost has exactly one CONFIG_PATH and the tenant header**

Run:
```bash
python3 - <<'PY'
import yaml
for d in yaml.safe_load_all(open("/tmp/v2-mon.yaml")):
    if d and d.get("kind")=="Deployment" and d.get("metadata",{}).get("name","").endswith("opencost"):
        env=d["spec"]["template"]["spec"]["containers"][0]["env"]
        by={e["name"]:e.get("value") for e in env if "name" in e}
        cps=[e for e in env if e.get("name")=="CONFIG_PATH"]
        print("CONFIG_PATH count:", len(cps), [e.get("value") for e in cps])
        print("PROM endpoint:", by.get("PROMETHEUS_SERVER_ENDPOINT"))
        print("tenant header:", by.get("PROMETHEUS_HEADER_X_SCOPE_ORGID"))
PY
```
Expected:
```
CONFIG_PATH count: 1 ['/tmp/custom-config']
PROM endpoint: http://mimir-gateway.lgtm.svc.cluster.local/prometheus
tenant header: spechtlabs
```

- [ ] **Step 7: Commit**

```bash
git add apps/grafana-k8s-monitoring/base/helm-values.yaml apps/grafana-k8s-monitoring/base/kustomization.yaml
git commit -m "feat(monitoring): ship v2 k8s-monitoring to self-hosted LGTM, drop Grafana Cloud"
```

---

### Task 2: Drop the Cloud-only Knowledge-Graph scrape on argocd

**Files:**
- Modify: `apps/argocd/cluster/specht-labs-v2/kustomization.yaml` (remove the argocd-server scrape-to-cloud annotation patch)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: nothing consumed downstream.

**Context:** argocd's full metrics already reach Mimir via its ServiceMonitors (`prometheusOperatorObjects -> selfhosted-mimir`). The patch below additionally annotated argocd-server for annotation-autodiscovery scraping, whose sole purpose was feeding `grpc_server` RED to the Grafana Cloud Knowledge Graph. With `annotationAutodiscovery` now pointing at Mimir, keeping the annotation would double-scrape argocd into Mimir; the KG it fed no longer exists. Remove it. Leave the `argocd-cmd-params-cm` OTLP-repoint patch immediately below it untouched — it points argocd traces at the in-cluster Alloy receiver, which now forwards to self-hosted Tempo.

- [ ] **Step 1: Remove the argocd-server scrape annotation patch**

In `apps/argocd/cluster/specht-labs-v2/kustomization.yaml`, delete this block (the comment plus the patch), which sits between the `argocd-cm` patch and the `argocd-cmd-params-cm` patch:

```yaml
  # argocd full metrics go to the self-hosted
  # Mimir via its ServiceMonitors (prometheusOperatorObjects -> selfhosted-mimir).
  # Additionally scrape argocd-server's metrics port to Grafana Cloud via
  # annotation-autodiscovery so the Knowledge Graph keeps its grpc_server RED.
  # The grafana-k8s-monitoring Cloud destination keeps only grpc_server_* from
  # job "argocd-server" and drops the rest of this (duplicate) scrape.
  # Annotations are inlined here (not the scrape-to-cloud component) because a
  # Component's labelSelector can't see a label added by an overlay patch.
  - target:
      kind: Deployment
      name: argocd-server
    patch: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: argocd-server
      spec:
        template:
          metadata:
            annotations:
              k8s.grafana.com/scrape: "true"
              k8s.grafana.com/metrics.portName: "metrics"
              k8s.grafana.com/job: "argocd-server"
```

- [ ] **Step 2: Assert the scrape annotation is gone from source**

Run:
```bash
grep -c "k8s.grafana.com/scrape" apps/argocd/cluster/specht-labs-v2/kustomization.yaml
```
Expected: `0`.

- [ ] **Step 3: Assert the OTLP-repoint patch survived**

Run:
```bash
grep -c "grafana-k8s-monitoring-alloy-receiver.monitoring.svc.cluster.local:4317" apps/argocd/cluster/specht-labs-v2/kustomization.yaml
```
Expected: `1`.

- [ ] **Step 4: Commit**

```bash
git add apps/argocd/cluster/specht-labs-v2/kustomization.yaml
git commit -m "feat(argocd): drop Cloud-only Knowledge-Graph scrape on v2"
```

---

## Final verification & deploy

- [ ] **CI-parity gate.** Run the full validation the same way CI does:
  ```bash
  mise run check
  ```
  Expected: every `apps/*/cluster/*` overlay renders and kubeconform reports no failures. (This needs SOPS/age available locally, the same as CI; the `KUBECONFIG` in `mise.toml` is unrelated to rendering.)

- [ ] **Cross-overlay Cloud-leak sweep.** Render the two changed v2 overlays and confirm no Cloud endpoints remain:
  ```bash
  for o in apps/grafana-k8s-monitoring/cluster/specht-labs-v2 apps/argocd/cluster/specht-labs-v2; do
    mise exec -- kustomize build --enable-alpha-plugins --enable-helm "$o"
  done | grep -nE "grafana\.net|prometheus-prod-|logs-prod-|otlp-gateway-|profiles-prod-|fleet-management" || echo "CLEAN: no cloud endpoints in v2 overlays"
  ```
  Expected: `CLEAN: no cloud endpoints in v2 overlays`. (PDC's `grafana-pdc-agent` Deployment and the orphan `grafana.secret.yaml` Secret may still appear — that's the untouched viewing layer, not an ingest endpoint.)

- [ ] **Push to main** (deploy): `git push`. ArgoCD's `monitoring` and argocd Applications sync automatically.

- [ ] **Post-sync data checks** (after ArgoCD reports Synced/Healthy):
  - Alloy collector pods in `monitoring` are Running; `mise exec -- kubectl -n monitoring logs deploy/grafana-k8s-monitoring-alloy-receiver` shows no export errors to the `lgtm` services.
  - In the existing Cloud Grafana (via PDC), the `spechtlabs`-tenant Mimir/Loki/Tempo/Pyroscope datasources show fresh data with `cluster="specht-labs"` timestamped after the deploy.
  - OpenCost: `mise exec -- kubectl -n monitoring logs deploy/grafana-k8s-monitoring-opencost` shows successful Prometheus queries (no 401 from Mimir), confirming the tenant header works end-to-end.

## Rollback

`git revert` the two commits and push. The Cloud destinations, Fleet Management config, and the argocd KG scrape return; PDC, `grafana.secret.yaml`, and the viewing layer never changed, so the pre-migration path is fully intact.
