# Envoy Gateway on specht-labs-v2 — Design

**Date:** 2026-05-30
**Status:** Approved (pending spec review)
**Scope:** Platform-only. Deploy Envoy Gateway as the modern (Gateway API) replacement
for ingress-nginx on the new `specht-labs-v2` cluster (Kubernetes v1.35.4), entirely
through the repository's ArgoCD GitOps pattern. No application HTTPRoutes are shipped —
those come later, per app.

## Goals

- Envoy Gateway controller + Gateway API/EG CRDs deployed via GitOps.
- A single shared `Gateway` that future apps attach `HTTPRoute`s to from any namespace.
- TLS via cert-manager using ACME HTTP-01 solved **through the Gateway**
  (`gatewayHTTPRoute`), issuing a certificate per hostname.
- Exposed via a Hetzner Cloud load balancer, mirroring the proven ingress-nginx LB config.
- Non-disruptive: the existing v1 (`specht-labs`) cluster and its nginx LB are untouched.

## Non-Goals

- Migrating existing application `Ingress` resources to `HTTPRoute` (the v2 cluster has no
  app workloads deployed yet).
- DNS-01 / wildcard certificates.
- Removing or modifying ingress-nginx on the v1 cluster.

## Context: repository conventions

The repo has two packaging styles:

- **Umbrella Helm chart** — `charts/<name>/` (Chart.yaml wrapping an upstream chart +
  `values.yaml`). Used by `cilium`, `ingress-nginx`, `hcloud-ccm`.
- **Kustomize overlay** — `kustomize/bases/<name>/` inflated by
  `kustomize/overlays/specht-labs-v2/<name>/`, often via kustomize `helmCharts:`. Used by
  `cert-manager`, `argocd`, `kube-prometheus-stack`.

Each component is wired by an ArgoCD `Application` (or `ApplicationSet`) under
`argo-apps/specht-labs-v2/`, pointing `source.path` at either a chart or an overlay. The
meta app-of-apps `argo-apps/specht-labs-v2/specht-labs.yaml` (`1-meta-specht-labs-cluster`,
`prune: false`, `selfHeal: false`) renders that directory.

**Chosen approach:** all-kustomize overlay (matches `cert-manager`/`argocd`). The
`gateway-helm` chart is inflated through kustomize `helmCharts:`, and the platform custom
resources are plain manifests in the same base.

## Upstream facts (verified 2026-05-30)

- Chart: `oci://docker.io/envoyproxy/gateway-helm`, version **1.8.0** (appVersion v1.8.0).
- The default install applies **both** Gateway API CRDs and Envoy Gateway CRDs.
- Default namespace: `envoy-gateway-system`.
- GatewayClass controller name: `gateway.envoyproxy.io/gatewayclass-controller`.
- cert-manager **1.20.2** (already deployed): Gateway API support is enabled with the Helm
  value `config.enableGatewayAPI: true` (no longer a feature gate since 1.15). cert-manager
  needs the Gateway API CRDs present to activate this.

## File layout

New files:

```
kustomize/bases/envoy-gateway/
  kustomization.yaml          # helmCharts: gateway-helm 1.8.0 (OCI) -> ns envoy-gateway-system
                              #  + the CR manifests below as resources
  helm-values.yaml            # minimal controller tuning
  gatewayclass.yaml           # GatewayClass "envoy" -> parametersRef EnvoyProxy
  envoyproxy.yaml             # EnvoyProxy: LoadBalancer Service + Hetzner annotations
  gateway.yaml                # shared Gateway: :80 (redirect) + :443 (TLS), allowedRoutes All
  redirect-httproute.yaml     # platform-owned HTTP->HTTPS 301 redirect, attached to :80

kustomize/overlays/specht-labs-v2/envoy-gateway/
  kustomization.yaml          # namespace: envoy-gateway-system; resources: ../../../bases/envoy-gateway/

argo-apps/specht-labs-v2/envoy-gateway.yaml   # ArgoCD Application -> overlay path (sync-wave 0)
```

Edited existing files:

```
kustomize/bases/cluster-issuer/letsencrypt-prod.yaml   # solver -> http01.gatewayHTTPRoute
kustomize/bases/cert-manager/helm-values.yaml          # add config.enableGatewayAPI: true
argo-apps/specht-labs-v2/cert-manager.yaml             # add sync-wave "1"
argo-apps/specht-labs-v2/cluster-issuer.yaml           # add sync-wave "1"
```

## Resource design

### kustomize base `kustomization.yaml`

Inflates the chart and includes the CRs:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: envoy-gateway-system

helmCharts:
  - name: gateway-helm
    repo: oci://docker.io/envoyproxy        # OCI registry base
    version: 1.8.0
    releaseName: envoy-gateway
    namespace: envoy-gateway-system
    valuesFile: helm-values.yaml

resources:
  - gatewayclass.yaml
  - envoyproxy.yaml
  - gateway.yaml
  - redirect-httproute.yaml
```

> Implementation note: the exact `helmCharts` OCI reference form (`repo:` base vs full
> `oci://.../gateway-helm` in `name:`) is verified during implementation with
> `kustomize build --enable-helm`. The chart coordinates above are correct; only the field
> split may need adjustment.

### GatewayClass `envoy`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: envoy
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
  parametersRef:
    group: gateway.envoyproxy.io
    kind: EnvoyProxy
    name: hetzner-lb
    namespace: envoy-gateway-system
```

### EnvoyProxy `hetzner-lb` (the Hetzner LB knob)

Mirrors the ingress-nginx Service config; **new LB name** so the v1 nginx LB is untouched.

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: hetzner-lb
  namespace: envoy-gateway-system
spec:
  provider:
    type: Kubernetes
    kubernetes:
      envoyService:
        type: LoadBalancer
        externalTrafficPolicy: Local
        annotations:
          load-balancer.hetzner.cloud/location: "nbg1"
          load-balancer.hetzner.cloud/name: "cedi-dev-gateway-lb"
          load-balancer.hetzner.cloud/type: "lb11"
          load-balancer.hetzner.cloud/algorithm-type: "least_connections"
          load-balancer.hetzner.cloud/health-check-protocol: "http"
          load-balancer.hetzner.cloud/disable-private-ingress: "true"
```

> The nginx config also pinned `healthCheckNodePort: 32596` for its `Local` policy. Envoy
> Gateway provisions its own Service; we let the health-check port be assigned dynamically
> rather than hard-pinning a NodePort. (Revisit only if the Hetzner health check needs a
> fixed port.)

### Shared Gateway `shared`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shared
  namespace: envoy-gateway-system
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  gatewayClassName: envoy
  listeners:
    - name: http
      protocol: HTTP
      port: 80
      allowedRoutes:
        namespaces:
          from: All
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs: []     # cert-manager populates per-host certs from the annotation
      allowedRoutes:
        namespaces:
          from: All
```

> cert-manager's `cluster-issuer` annotation on a Gateway drives `gateway-shim`, which
> issues certificates for the hostnames of HTTPS listeners and writes the cert Secrets into
> the Gateway's namespace (`envoy-gateway-system`). Implementation will confirm whether the
> listener requires an explicit hostname/certificateRef placeholder for the shim to act, or
> whether per-host listeners are appended as apps onboard. Platform ships with the shared
> Gateway; host-specific listeners are added when the first app is onboarded (out of scope
> here).

### Platform redirect HTTPRoute

Attached to the `:80` listener, 301-redirects all HTTP to HTTPS so apps only define HTTPS
routes:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: https-redirect
  namespace: envoy-gateway-system
spec:
  parentRefs:
    - name: shared
      sectionName: http
  rules:
    - filters:
        - type: RequestRedirect
          requestRedirect:
            scheme: https
            statusCode: 301
```

### cert-manager edits

`kustomize/bases/cert-manager/helm-values.yaml` — add:

```yaml
config:
  enableGatewayAPI: true
```

`kustomize/bases/cluster-issuer/letsencrypt-prod.yaml` — change the solver:

```yaml
    solvers:
      - http01:
          gatewayHTTPRoute: {}
```

(letsencrypt-staging.yaml left as-is unless we later toggle it on.)

## ArgoCD wiring & sync ordering

A new `argo-apps/specht-labs-v2/envoy-gateway.yaml` `Application`, following the repo
pattern, pointing at `kustomize/overlays/specht-labs-v2/envoy-gateway`, destination
namespace `envoy-gateway-system`, `automated { prune: true, selfHeal: true }`,
`CreateNamespace=true`.

Sync ordering via `argocd.argoproj.io/sync-wave`:

- **Wave 0** — `envoy-gateway`: installs Gateway API + EG CRDs, controller, GatewayClass,
  EnvoyProxy, Gateway, redirect HTTPRoute. Adds sync options:
  - `ServerSideApply=true`
  - `SkipDryRunOnMissingResource=true`

  These resolve the "CRDs and the CRs that use them in one Application" race: the CRs would
  otherwise fail client-side dry-run before their CRDs are established.

- **Wave 1** — `cert-manager` and `cluster-issuer`: re-synced after the Gateway API CRDs
  exist, so `enableGatewayAPI: true` activates and the `gatewayHTTPRoute` solver is valid.
  This adds a sync-wave annotation to the existing `cert-manager.yaml` and
  `cluster-issuer.yaml` Applications.

> Sync-waves and these sync options are **new to this repo** (none currently use them). This
> is a deliberate, documented introduction to make the cross-Application ordering
> deterministic. The meta app-of-apps is manual (`selfHeal: false`), so on first bootstrap
> the waves guide a clean apply; on steady state cert-manager self-heals regardless.

## Runtime data flow (once synced)

1. EnvoyProxy → controller provisions an Envoy Deployment + `LoadBalancer` Service →
   Hetzner CCM creates `cedi-dev-gateway-lb` and assigns an external IP.
2. Shared Gateway: `:80` bound to the platform redirect HTTPRoute (301 → https); `:443`
   TLS-terminating.
3. A future app creates an `HTTPRoute` in its own namespace with `parentRefs` to
   `shared`/`envoy-gateway-system`; `allowedRoutes.from: All` permits the attachment.
4. cert-manager (`cluster-issuer` annotation on the Gateway) solves HTTP-01 by injecting a
   temporary HTTPRoute through the same Gateway, then writes the per-host cert Secret that
   the `:443` listener references.

## Failure handling & edge cases

- **HTTP-01 self-dependency:** the ACME challenge is solved *through* the Gateway, so the
  `:80` path must be internet-reachable (LB provisioned, DNS pointing at it) before certs go
  `Ready`. Expected one-time bootstrap ordering, not a defect.
- **Cross-namespace cert Secret:** cert-manager writes the listener cert Secret into the
  Gateway namespace (`envoy-gateway-system`); no `ReferenceGrant` needed for the listener.
- **ReferenceGrant** is only required later if an app's HTTPRoute targets a backend Service
  in a *different* namespace than the route. Same-namespace route→service needs none.
- **Old nginx LB untouched:** new LB name (`cedi-dev-gateway-lb`) means no disruption to v1.
- **Renovate:** the kustomize `helmCharts` `gateway-helm` version may not be auto-tracked by
  the current `renovate.json` (no explicit kustomize-helm datasource rule). Flagged;
  out of scope for this platform deploy. May need a follow-up renovate hint.

## Acceptance checks (manual, post-sync)

- `kubectl get gatewayclass envoy` → `Accepted=True`.
- `kubectl -n envoy-gateway-system get gateway shared` → `Programmed=True` with an address.
- Hetzner console shows `cedi-dev-gateway-lb` with a public IP and healthy targets.
- `kubectl -n envoy-gateway-system get pods` → controller + provisioned envoy Running.
- cert-manager pod logs show Gateway API support enabled (no CRD errors).
- (Smoke test, not shipped) a temporary HTTPRoute + hostname obtains a `Ready` certificate
  and serves HTTPS through the LB.

## Out of scope / future work

- First app onboarding: per-host HTTPS listener (or hostname on the shared listener),
  app HTTPRoute, and any ReferenceGrant.
- Decommissioning ingress-nginx (only after all apps migrate, on whichever cluster).
- Renovate tracking for the gateway-helm chart version.
