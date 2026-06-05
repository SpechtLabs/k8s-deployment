# StaticPages on specht-labs-v2 — Design

**Date:** 2026-06-05
**Status:** Draft (pending spec review)
**Scope:** Port the StaticPages deployment from the v1 `specht-labs` cluster to the new
`specht-labs-v2` cluster (Envoy Gateway / Gateway API), as a **true cutover** to the real
production domains. Introduces the first DNS-01 / wildcard certificate setup on v2 and the
first gateway-terminated-TLS app (argocd uses TLS passthrough).

## Goals

- StaticPages running on v2 via the repo's ArgoCD GitOps pattern, mirroring v1.
- Served on the **real production domains** (cutover, not a `*.v2` staging alias).
- TLS terminated at the shared Envoy Gateway using **wildcard certificates** issued by
  cert-manager via **Cloudflare DNS-01**.
- Branch previews (`preview.branch: true`) keep working under valid TLS thanks to wildcard
  certs.

## Non-Goals

- Decommissioning the v1 `specht-labs` StaticPages deployment or its nginx ingress (a
  follow-up once DNS is flipped and v2 is verified).
- Flipping real DNS records to the v2 load balancer (an operational step, done by the user
  outside this repo; this spec only makes v2 *ready* to serve those hosts).
- Changing StaticPages app behaviour, page configs, buckets, or repos. The
  `configs.pages[]` list is copied verbatim — only the ingress→gateway exposure changes.

## Decisions (from brainstorming)

1. **Domain scope:** true cutover — v2 serves the real production domains, not `*.v2`
   aliases. (The opening "`*.v2.specht-labs.de`" framing was superseded.)
2. **Previews:** add a DNS-01 wildcard issuer so previews get valid TLS.
3. **Issuer strategy:** switch the v2 `letsencrypt-prod` ClusterIssuer entirely to
   Cloudflare DNS-01 (mirrors `kustomize/overlays/labk3s/cluster-issuer`), rather than
   adding a second issuer. argocd's `argocd-server-tls` Certificate keeps the same
   `issuerRef: letsencrypt-prod` and is simply issued via DNS-01 instead of HTTP-01.

## Context: what v1 does (verified by rendering the chart)

`kustomize build --enable-helm kustomize/bases/static-pages` renders:

- Two Services:
  - `static-pages-proxy` — port **8080** (named `http`), serves page content.
  - `static-pages-api` — port **8081** (named `api`), management API.
- One Ingress (`ingressClassName: nginx`) whose host rules are **auto-generated from
  `configs.pages[].domain`**, not from `staticpages.ingress.hosts`:
  - `pages.specht-labs.de` path `/api` → `static-pages-api:8081`
  - `pages.specht-labs.de` path `/` → `static-pages-proxy:8080`
  - each other domain, path `/` → `static-pages-proxy:8080`
- TLS secret `staticpages-tls` covering all 8 hosts.

The 8 production hostnames (from `configs.pages[].domain`):

| # | hostname | zone |
|---|----------|------|
| 1 | `specht-labs.de` (apex) | specht-labs.de |
| 2 | `pages.specht-labs.de` | specht-labs.de |
| 3 | `calendarapi.specht-labs.de` | specht-labs.de |
| 4 | `tka.specht-labs.de` | specht-labs.de |
| 5 | `dev-page.specht-labs.de` | specht-labs.de |
| 6 | `golint.specht-labs.de` | specht-labs.de |
| 7 | `granary.specht-labs.de` | specht-labs.de |
| 8 | `gold-specht.de` (apex) | gold-specht.de |

> Note: the chart's `staticpages.ingress.hosts` value (`pages.specht-labs.de`) only seeds
> the `/api` rule + the chart's own `staticpages-tls`; the proxy host rules come from the
> page configs. In v2 the rendered Ingress is deleted and replaced by HTTPRoutes, so this
> distinction only matters for understanding the routing we must reproduce.

## Context: v2 platform conventions

- Apps attach `HTTPRoute`/`TLSRoute` to the single shared `Gateway`
  (`shared`, ns `envoy-gateway-system`). All app listeners accumulate in
  `kustomize/bases/envoy-gateway/gateway.yaml` (single Gateway → single Envoy → single
  Hetzner LB). See `docs/superpowers/specs/2026-05-30-envoy-gateway-design.md`.
- argocd v2 precedent: deletes the chart's Ingress with a `$patch: delete`, adds a
  `Certificate` + route. We reuse both moves.
- labk3s precedent for DNS-01: `kustomize/overlays/labk3s/cluster-issuer/` patches
  `letsencrypt-prod` to `dns01.cloudflare` with secret `cloudflare-api-token` (key
  `api-token`). The encrypted secret uses the same 4 age recipients as everything else, so
  the ciphertext is reusable verbatim.

## Approach

Switch the v2 `letsencrypt-prod` ClusterIssuer to Cloudflare DNS-01; issue **one wildcard
Certificate** covering both zones; add wildcard **Terminate** listeners to the shared
Gateway; replace the chart Ingress with **HTTPRoutes** to the proxy/api Services.

Wildcard `*.specht-labs.de` matches exactly **one** label, so it does **not** collide with
the existing passthrough listener for `argocd.v2.specht-labs.de` (two labels). The two
listeners coexist on port 443, disambiguated by SNI.

## File layout

### New files

```
kustomize/overlays/specht-labs-v2/static-pages/
  kustomization.yaml          # base + secret-generator + image override; deletes chart Ingress
  secret-generator.yaml       # ksops -> s3.secret.yaml
  s3.secret.yaml              # SOPS-encrypted S3 creds (copied verbatim from v1 overlay)
  httproute.yaml              # HTTPRoute(s): pages /api -> api:8081; all hosts / -> proxy:8080

kustomize/bases/envoy-gateway/
  static-pages-certs.yaml     # cert-manager Certificate -> secret static-pages-tls (wildcard SANs)

kustomize/overlays/specht-labs-v2/cluster-issuer/
  cloudflare-api-token.secret.yaml   # SOPS-encrypted Cloudflare token (copied from labk3s)
  secret-generator.yaml              # ksops -> cloudflare-api-token.secret.yaml

argo-apps/specht-labs-v2/
  static-pages.yaml           # ArgoCD Application -> overlay path, ns static-pages
```

### Edited files

```
kustomize/overlays/specht-labs-v2/cluster-issuer/letsencrypt-prod.yaml  # http01 -> dns01.cloudflare
kustomize/overlays/specht-labs-v2/cluster-issuer/kustomization.yaml     # add generators: secret-generator
kustomize/bases/envoy-gateway/gateway.yaml                              # add wildcard Terminate listeners
kustomize/bases/envoy-gateway/kustomization.yaml                        # add static-pages-certs.yaml resource
```

## Resource design

### 1. Cluster-issuer → Cloudflare DNS-01

`kustomize/overlays/specht-labs-v2/cluster-issuer/letsencrypt-prod.yaml` — replace the
`http01.gatewayHTTPRoute` solver with:

```yaml
    solvers:
      - dns01:
          cloudflare:
            apiTokenSecretRef:
              name: cloudflare-api-token
              key: api-token
```

`kustomization.yaml` — add the secret generator (and keep `resources: [letsencrypt-prod.yaml]`):

```yaml
generators:
  - ./secret-generator.yaml
```

`secret-generator.yaml` (ksops) + `cloudflare-api-token.secret.yaml` copied verbatim from
`kustomize/overlays/labk3s/cluster-issuer/`. The Secret lands in namespace `cert-manager`
(the overlay's namespace), where cert-manager reads it.

> The Cloudflare API token must have **Zone:DNS:Edit** for both the `specht-labs.de` and
> `gold-specht.de` zones. Assumption to verify: the labk3s token already covers both. If it
> only covers `specht-labs.de`, the `gold-specht.de` cert will fail and we either widen the
> token or drop gold-specht from the wildcard cert.

> The argo-app `cluster-issuer.yaml` keeps `sync-wave: "1"`; its comment ("solver needs
> Gateway API CRDs") becomes stale under DNS-01 but is harmless. Update the comment to
> reflect DNS-01 to avoid drift.

### 2. Wildcard Certificate

`kustomize/bases/envoy-gateway/static-pages-certs.yaml`:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: static-pages-tls
  namespace: envoy-gateway-system
spec:
  secretName: static-pages-tls
  dnsNames:
    - specht-labs.de
    - "*.specht-labs.de"
    - gold-specht.de
    - "*.gold-specht.de"
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
    group: cert-manager.io
```

The Secret lives in `envoy-gateway-system` so the Gateway listeners can reference it
directly (no ReferenceGrant needed for listener certs).

### 3. Shared Gateway listeners

Append to `kustomize/bases/envoy-gateway/gateway.yaml` `spec.listeners` (alongside the
existing `http` and `argocd-tls` listeners). Gateway API listener `hostname` does not allow
multi-SAN, so each distinct hostname/wildcard is its own listener; all reference the one
`static-pages-tls` Secret:

```yaml
    - name: specht-labs-wildcard
      protocol: HTTPS
      port: 443
      hostname: "*.specht-labs.de"
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: static-pages-tls
      allowedRoutes:
        namespaces:
          from: All
    - name: specht-labs-apex
      protocol: HTTPS
      port: 443
      hostname: specht-labs.de
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: static-pages-tls
      allowedRoutes:
        namespaces:
          from: All
    - name: gold-specht-wildcard
      protocol: HTTPS
      port: 443
      hostname: "*.gold-specht.de"
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: static-pages-tls
      allowedRoutes:
        namespaces:
          from: All
    - name: gold-specht-apex
      protocol: HTTPS
      port: 443
      hostname: gold-specht.de
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: static-pages-tls
      allowedRoutes:
        namespaces:
          from: All
```

> Why wildcard listeners rather than one per domain: the 6 single-label hosts
> (`pages.`, `calendarapi.`, `tka.`, `dev-page.`, `golint.`, `granary.`) plus any
> one-level preview host (`branch.specht-labs.de`) are all covered by the single
> `*.specht-labs.de` listener. Apexes need their own listeners (a wildcard label does not
> match the bare apex).

### 4. HTTPRoutes

`kustomize/overlays/specht-labs-v2/static-pages/httproute.yaml`, namespace `static-pages`
(same namespace as the backend Services → no ReferenceGrant). Two routes:

**Route A — management API** (most-specific path on `pages.specht-labs.de`):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: static-pages-api
  namespace: static-pages
spec:
  parentRefs:
    - name: shared
      namespace: envoy-gateway-system
  hostnames:
    - pages.specht-labs.de
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api
      backendRefs:
        - name: static-pages-api
          port: 8081
```

**Route B — page proxy** (catch-all `/` for every served host):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: static-pages-proxy
  namespace: static-pages
spec:
  parentRefs:
    - name: shared
      namespace: envoy-gateway-system
  hostnames:
    - specht-labs.de
    - "*.specht-labs.de"
    - gold-specht.de
    - "*.gold-specht.de"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: static-pages-proxy
          port: 8080
```

Route B uses wildcard hostnames so branch previews route to the proxy. Path specificity is
evaluated across routes attached to the same Gateway, so Route A's `/api` on
`pages.specht-labs.de` wins over Route B's `/` for that host (Envoy Gateway supports
cross-route precedence by path). `parentRefs` omit `sectionName`, so each route binds to
every listener whose hostname intersects its hostnames + `allowedRoutes`.

> Faithfulness note: v1 scopes `/api` to `pages.specht-labs.de` only. Keeping Route A on a
> single explicit hostname (not the wildcard) preserves that — `/api` on other hosts falls
> through to the proxy, exactly as in v1.

### 5. StaticPages overlay

`kustomize/overlays/specht-labs-v2/static-pages/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: static-pages

resources:
  - ../../../bases/static-pages
  - httproute.yaml

generators:
  - ./secret-generator.yaml

images:
  - name: ghcr.io/spechtlabs/staticpages
    newTag: v0.1.5

patches:
  # v2 routes via the Envoy Gateway (HTTPRoutes above); drop the nginx Ingress the chart
  # renders from the shared base. Base stays unchanged for v1 (specht-labs).
  - target:
      kind: Ingress
      name: static-pages
    patch: |
      $patch: delete
      apiVersion: networking.k8s.io/v1
      kind: Ingress
      metadata:
        name: static-pages
```

`secret-generator.yaml` and `s3.secret.yaml` copied verbatim from
`kustomize/overlays/specht-labs/static-pages/` (same age recipients → no re-encryption).

> The base `helm-values.yaml` still has `ingress.enabled: true`; we delete the rendered
> object rather than templating it off, matching the argocd v2 approach and keeping the
> shared base untouched for v1.

### 6. ArgoCD Application

`argo-apps/specht-labs-v2/static-pages.yaml` — copy of the v1 app, `source.path` →
`kustomize/overlays/specht-labs-v2/static-pages`, destination namespace `static-pages`,
`automated { prune: true, selfHeal: true }`, `CreateNamespace=true`. No sync-wave needed
(cert-manager/gateway already exist by the time apps sync); the meta app-of-apps
(`1-meta-specht-labs-cluster`) renders the directory.

## Runtime data flow (once synced)

1. cert-manager sees the `static-pages-tls` Certificate, solves DNS-01 via Cloudflare for
   all 4 SANs, writes Secret `static-pages-tls` in `envoy-gateway-system`.
2. The 4 new Terminate listeners on the shared Gateway come up `Programmed` referencing
   that Secret.
3. Client hits e.g. `https://specht-labs.de` → Hetzner LB → Envoy terminates TLS on the
   matching listener → Route B → `static-pages-proxy:8080`.
4. `https://pages.specht-labs.de/api/...` → Route A → `static-pages-api:8081`; other paths
   on that host → Route B → proxy.
5. `http://...` → existing `:80` redirect HTTPRoute → 301 to https.

## Failure handling & edge cases

- **Cloudflare token scope:** must cover both `specht-labs.de` and `gold-specht.de` zones
  (Zone:DNS:Edit). If not, split into two certs/tokens or drop gold-specht. Verify before
  apply.
- **argocd cert via DNS-01:** `argocd-server-tls` now issues via DNS-01 — strictly an
  improvement (no `:80` dependency). No change to its manifests required.
- **SNI coexistence on :443:** passthrough `argocd-tls` (`argocd.v2.specht-labs.de`, two
  labels) vs terminate `*.specht-labs.de` (one label) do not overlap. Confirm with
  `kubectl get gateway shared -o yaml` that all listeners report `Programmed=True` and
  there are no `Conflicted` conditions.
- **Cross-route path precedence:** relies on Envoy Gateway honouring path specificity
  across two HTTPRoutes sharing `pages.specht-labs.de`. If it instead requires a single
  route, fold Route A's `/api` rule into Route B as a higher-precedence rule scoped by an
  additional hostname match (fallback documented here, applied only if needed).
- **Stale comments:** `gateway.yaml` and `cluster-issuer.yaml`/argocd overlay comments
  reference HTTP-01/`:80` ACME. Update the cluster-issuer-related comments to DNS-01; the
  `:80` listener itself stays (HTTP→HTTPS redirect).
- **No disruption to v1:** v1 `specht-labs` overlay, its nginx ingress, and the shared
  `bases/static-pages` are untouched. Cutover happens only when DNS for these hosts is
  pointed at the v2 LB (an external step).

## Open question for spec review

**Preview hostname format.** All page configs keep `preview.branch: true`. The wildcard
certs/listeners/routes cover **one-level** preview hosts (`branch.specht-labs.de`). If
StaticPages emits **two-level** preview hosts (e.g. `branch.pages.specht-labs.de`), we must
add `*.pages.specht-labs.de` (and any other parent) to: the Certificate `dnsNames`, a new
Gateway listener, and Route B `hostnames`. **Confirm the preview host scheme before
implementing**; default assumption is one-level.

## Acceptance checks (manual, post-sync)

- `kubectl -n cert-manager get clusterissuer letsencrypt-prod -o yaml` shows the
  `dns01.cloudflare` solver.
- `kubectl -n envoy-gateway-system get certificate static-pages-tls` → `Ready=True`.
- `kubectl -n envoy-gateway-system get gateway shared -o yaml` → all listeners
  `Programmed=True`, no `Conflicted`.
- `kubectl -n static-pages get httproute` → both routes `Accepted=True`,
  `ResolvedRefs=True`.
- From a host with `/etc/hosts` pointed at the v2 LB IP (pre-DNS-flip smoke test):
  `curl -ksv https://specht-labs.de` serves page content; `https://pages.specht-labs.de/api`
  reaches the API; cert chain is the Let's Encrypt wildcard.
- `https://argocd.v2.specht-labs.de` still works (passthrough unaffected).

## Out of scope / future work

- Pointing real DNS records at the v2 LB (operational cutover step).
- Decommissioning v1 StaticPages + nginx after the cutover is verified.
- Two-level preview wildcard SANs (pending the open question's answer).
- Renovate tracking for the `static-pages` chart version.
