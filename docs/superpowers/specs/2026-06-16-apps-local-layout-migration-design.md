# Migrate `kustomize/` to a per-app local layout

**Date:** 2026-06-16
**Status:** Approved — ready for implementation planning

## Problem

Kustomize config is split across a global `kustomize/bases/` directory and
per-cluster `kustomize/overlays/<cluster>/` trees. Navigating a single app means
jumping between `bases/<app>/` and one overlay dir per cluster, which are far
apart in the file tree. We want each app to be **local**: its base and every
cluster overlay co-located under one `apps/<app>/` directory, so the whole app
is one subtree.

The `apps/argocd/` example is already wired up by hand and serves as the
reference implementation for the target convention.

## Target layout

```
apps/
  <app>/
    base/                  # shared base: kustomization.yaml, helm-values.yaml, vendored charts/
    components/            # OPTIONAL: app-local components shared across this app's clusters
    cluster/
      labk3s/              # per-cluster overlay; resources: [../../base]
      specht-labs/
      specht-labs-v2/
components/                # repo-root: resources/components shared across DIFFERENT apps
  scrape-to-cloud/
  grafana-dashboards/      # promoted from bases/ (see Cross-app shared bases)
  grafana-datasources/
  grafana-plugins/
argo-apps/                 # UNCHANGED location & grouping; only `path:` fields repointed
```

## Mapping rules

| Old | New |
|-----|-----|
| `kustomize/bases/<app>/` | `apps/<app>/base/` (vendored `charts/` move with it) |
| `kustomize/overlays/<cluster>/<app>/` | `apps/<app>/cluster/<cluster>/` |
| `kustomize/components/<c>/` | `components/<c>/` (repo root) |
| cross-app shared bases | `components/<c>/` (repo root) |

Relative-path rewrites inside the moved files:

- Overlay → base: `../../../bases/<app>/` becomes `../../base/`
  (overlay is now `apps/<app>/cluster/<cluster>/`, base is `apps/<app>/base/`).
- Overlay → repo-root component / cross-app shared base: rewritten to the correct
  relative depth from `apps/<app>/cluster/<cluster>/`, i.e. `../../../../components/<c>/`.
- Any other relative `resources`/`patches`/`generators` paths that stay inside
  the moved directory are unchanged.

## Decisions (locked)

1. **Cross-app shared bases → repo-root `components/`.**
   `bases/grafana-dashboards` (referenced by both the specht-labs `grafana`
   overlay and the v2 `grafana-operator` overlay), plus `grafana-datasources`
   and `grafana-plugins`, are promoted to `components/`. They are referenced as
   `resources` (they remain ordinary resource kustomizations; promoting them to
   `kind: Component` is out of scope). Their internal subdirs
   (`kubernetes-infra-apps`, `envoy-gateway`, `infrastructure`, `static-pages`,
   `mimir`, `kubernetes-mixin`, `dashboards`) move as-is.

2. **`cluster-api` splits into two apps.** The specht-labs overlay uses
   `bases/cluster-api`; the v2 overlay (dir named `cluster-api`) actually uses a
   *different* base, `bases/cluster-api-v2`. These are genuinely different
   stacks, so:
   - `apps/cluster-api/` ← `bases/cluster-api` + `overlays/specht-labs/cluster-api`
   - `apps/cluster-api-v2/` ← `bases/cluster-api-v2` + `overlays/specht-labs-v2/cluster-api`
     (the v2 argo-app `path:` becomes `apps/cluster-api-v2/cluster/specht-labs-v2`).

3. **`argo-apps/` stays put.** It is the GitOps entrypoint and is inherently
   cluster-grouped — each cluster's root app-of-apps points at its
   `argo-apps/<cluster>/` dir. Only the `path:` fields inside the
   Application/ApplicationSet manifests are repointed from
   `kustomize/overlays/<cluster>/<app>` to `apps/<app>/cluster/<cluster>`.
   AppSet list-generators with multiple inline paths (network, monitoring, lgtm,
   hcloud, observability, certificates, exporters, …) have each path string
   rewritten.

4. **`kustomize/` is deleted only at the very end**, after the full migration is
   verified complete and nothing remains to migrate. Until then it stays in
   place as the implicit parity reference. No partial deletion.

## Edge cases

- **Self-inflating overlays** (v2 `cert-manager`, v2 `cluster-issuer`) don't
  reference a shared base — they inflate their own `helmCharts`. The app's
  `base/` simply isn't referenced by that cluster overlay; for apps where *no*
  cluster uses a shared base (e.g. `external-dns`, `grafana-operator` — there is
  no `bases/external-dns` / `bases/grafana-operator`), there is no `base/` dir
  and the `cluster/<cluster>/` overlay is self-contained.
- **Single-cluster apps** (karakeep, urlshortener, robusta, mimir,
  envoy-gateway, external-dns, cluster-api-operator, grafana-operator,
  grafana-k8s-monitoring, kube-prometheus-stack, grafana, grafana-loki,
  grafana-mimir, grafana-oncall, grafana-tempo) get a `cluster/` with a single
  subdir.
- **`.yamllint.yml`** contains `kustomize/` path globs — update them to `apps/`.
- **Docs** referencing old paths (`docs/**`, `Readme.md`, `grafana/slos/README.md`,
  `charts/cert-checker/values.yaml` comment refs, `grafana/kg-suppressions/`)
  are updated opportunistically; they do not gate cluster health.

## Migration sequence (per-app, build-parity verified)

Work one app at a time. For each app:

1. `git mv` the base and each cluster overlay into `apps/<app>/...`; rewrite the
   relative paths per the rules above.
2. **Parity gate:** render the old path (from git, since `kustomize/` is still
   present) and the new path with `kustomize build --enable-helm`, and diff. The
   output must be **byte-identical** except for the deliberately changed path
   strings. A clean diff proves ArgoCD will see zero change in rendered manifests.
3. Repoint the corresponding `argo-apps` `path:` field(s).
4. Commit directly to `main` (repo house style — no feature branches/PRs).

Ordering:

1. **`components/` first** — `scrape-to-cloud`, then `grafana-dashboards` /
   `grafana-datasources` / `grafana-plugins` — because other apps reference them.
2. **Clean 1:1 apps** — the bulk (argocd already done; verify it against the gate).
3. **Special cases last** — `cluster-api` / `cluster-api-v2` split, the
   self-inflating v2 overlays, and `grafana` (which consumes the promoted
   components).

Final step, only once every app is migrated and verified: delete `kustomize/`
and update `.yamllint.yml` + docs.

## Verification

- Per-app: byte-identical `kustomize build --enable-helm` diff (old vs new path).
- Repo-wide at the end: `grep -rn "kustomize/overlays\|kustomize/bases"` returns
  no matches in `argo-apps/` or active config (docs excepted until updated).
- ArgoCD: each repointed Application/ApplicationSet syncs with no rendered drift.

## Out of scope

- Reorganizing `argo-apps/` itself.
- The repo-root `charts/` dir (custom Helm charts like `hcloud-ccm`) and the
  `manifests/` dir — unrelated to the kustomize layout.
- Converting promoted shared bases to `kind: Component`.
- Any change to rendered manifest content (this is a pure move/rewrite).
