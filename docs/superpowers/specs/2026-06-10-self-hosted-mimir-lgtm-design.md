# Self-hosted Mimir (LGTM scaffold) on specht-labs-v2

Date: 2026-06-10
Status: Approved (design), pending implementation plan

## Goal

Run a self-hosted Grafana Mimir on the specht-labs-v2 cloud cluster so the
Raspberry Pi homelab can remote-write metrics into durable, in-cloud storage
without running a TSDB on the Pis and without sending the data to Grafana Cloud
hosted Mimir.

This round migrates **only Mimir**, but lands the **LGTM ApplicationSet
scaffold** (Loki / Grafana / Tempo / Mimir) so the other three are a one-line
uncomment later. Everything deploys into the `lgtm` namespace.

## Scope

In scope:
- Mimir (right-sized distributed topology) deployed via the `mimir-distributed`
  Helm chart, pinned.
- Hetzner Object Storage (S3-compatible) for blocks.
- SOPS-encrypted S3 credentials.
- In-cluster Service plus one per-tenant HTTPRoute on the existing tailnet
  Gateway as the remote-write ingest path (header-injected `X-Scope-OrgID`).
- `lgtm` ApplicationSet with Mimir active and Loki/Tempo/Grafana stubbed.

Out of scope (later rounds):
- Loki / Tempo / Grafana deployment.
- Mimir ruler and alertmanager.
- Memcached caches.
- Dashboards and recording/alerting rules.
- Migrating any specht-labs-v2 self-metrics into this Mimir (separate decision;
  the cost PR drops those rather than offloading them).

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Sizing | Right-sized distributed: same microservices topology as `small.yaml`, 1 replica each, `replication_factor: 1`, small resource requests, caches off. |
| Architecture | Kafka ingest-storage (chart 6.0.6 / Mimir 3.0 default): distributor -> Kafka -> ingester. The chart bundles a single-node KRaft Kafka (`apache/kafka-native`, no Zookeeper). Topic partitions trimmed from the demo default of 100 to 8. |
| Chart version | `mimir-distributed` 6.0.6 (Mimir 3.0.4), pinned. |
| Object storage | Hetzner Object Storage (S3), one bucket. Blocks off-cluster so they survive cluster rebuilds. |
| Write path | One HTTPRoute per tenant on the existing tailnet-only Envoy Gateway (`tailnet`/`http`). Plain HTTP, private over WireGuard. Each route injects the tenant's `X-Scope-OrgID` header. |
| Multitenancy | Enabled. Tenants created implicitly on first write. Tenant tagging done by the Gateway (per-hostname header injection), so clients need no custom-header config. |
| Reference config | Grafana's `mimir-distributed/small.yaml` used as the structural reference only; our sizing/storage applied via `mimir.structuredConfig`. |

## Architecture

### Repo layout

```
argo-apps/specht-labs-v2/lgtm.yaml              # ApplicationSet; mimir active, loki/tempo/grafana commented
kustomize/bases/mimir/
  kustomization.yaml                             # helmCharts: mimir-distributed (pinned) + valuesFile
  helm-values.yaml                               # right-sized values + structuredConfig
kustomize/overlays/specht-labs-v2/mimir/
  kustomization.yaml                             # namespace: lgtm; references base; SOPS generator
  secret-generator.yaml                          # ksops generator
  mimir-objstore.secret.yaml                     # SOPS-encrypted Hetzner S3 access/secret keys
  httproutes.yaml                                # one HTTPRoute per tenant (X-Scope-OrgID injection)
```

This mirrors the existing base/overlay split (see `grafana-k8s-monitoring`) and
the AppSet conventions in `monitoring.yaml` / `network.yaml`.

### Mimir topology (1 replica each)

Enabled (replicas: 1): distributor, ingester, querier, query-frontend,
query-scheduler, store-gateway, compactor, overrides-exporter, the front proxy
(`gateway`, nginx), and the bundled single-node `kafka` (ingest-storage).

Disabled for v1: alertmanager, ruler, `rollout_operator` (only needed for
zone-aware rollouts), chunks/index/metadata/results caches (already off by
default), bundled MinIO.

`structuredConfig` highlights:
- `multitenancy_enabled: true`
- `ingester.ring.replication_factor: 1` and
  `store_gateway.sharding_ring.replication_factor: 1`
- `ingest_storage.kafka.auto_create_topic_default_partitions: 8` (down from 100)
- Object storage via `common.storage.backend: s3` + `common.storage.s3`
  pointing at Hetzner (`endpoint: <region>.your-objectstorage.com`,
  `bucket_name`).
- Credentials via env expansion: `access_key_id: ${AWS_ACCESS_KEY_ID}`,
  `secret_access_key: ${AWS_SECRET_ACCESS_KEY}`. The chart already sets
  `-config.expand-env=true` on every component.

Footprint: ~10 pods. `zoneAwareReplication` disabled on ingester and
store-gateway (single zone, RF1).

### Storage

- Blocks: Hetzner Object Storage bucket (e.g. `specht-labs-mimir-blocks`).
- Local working set via hcloud-csi PVCs (default StorageClass `hcloud-volumes`):
  ingester ~10Gi, store-gateway ~5Gi, compactor ~10Gi, kafka 5Gi (chart
  default). All tunable.

### Secrets

S3 access key + secret key in a SOPS-encrypted Secret (ksops generator, same
pattern as other overlays). Injected into Mimir pods as `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` env (chart `global.extraEnvFrom` or equivalent),
referenced from `structuredConfig` via env expansion. No plaintext creds in
values or git.

### Tenants

Multitenancy is enabled. Tenants are not pre-declared; Mimir creates them on
first write. Initial tenant IDs:

| Tenant ID | Source | Ingest hostname |
|-----------|--------|-----------------|
| `homelab` | Raspberry Pi homelab | `homelab-mimir.k8s.specht-labs.de` |
| `hass` | My Home Assistant | `hass-mimir.k8s.specht-labs.de` |
| `hass-schiltach` | Dad's Home Assistant (Schiltach) | `hass-schiltach-mimir.k8s.specht-labs.de` |

Per-tenant limits (ingestion rate, max series, retention) are available via
Mimir's runtime `overrides` config but are left at defaults for v1.

### Ingest path

One `HTTPRoute` per tenant in `lgtm`, all attached to the same Gateway:
- `parentRefs`: `tailnet` / `envoy-gateway-system` / sectionName `http`.
- `hostnames`: the per-tenant hostname from the table above (external-dns
  publishes `*.k8s` at the tailscale target).
- `filters`: `RequestHeaderModifier` that **sets** `X-Scope-OrgID` to the
  tenant ID. This is why clients need no custom-header config.
- `backendRefs`: Mimir front-proxy Service, HTTP port.

Routes and backend are all in `lgtm`, so no ReferenceGrant. The `http` listener
allows routes from all namespaces. A source remote-writes to
`http://<tenant-host>/api/v1/push`; the Gateway stamps the tenant header.

Security model: Mimir trusts the `X-Scope-OrgID` header and does no auth on it.
Isolation rests on (a) the LB being tailnet-only and (b) the Gateway being the
only path that sets the header. A malicious actor already on the tailnet could
still spoof a tenant by calling the Service directly; acceptable for this
homelab. Per-tenant tokens/auth can be added in front later if isolation needs
to be stronger (e.g. before exposing dad's HA more widely).

### LGTM ApplicationSet

`lgtm.yaml` ApplicationSet, same template as `monitoring`/`network`:
- generator list element **mimir** -> `kustomize/overlays/specht-labs-v2/mimir`,
  namespace `lgtm`.
- **loki / tempo / grafana** present as commented-out list elements.
- `syncPolicy.automated` (prune + selfHeal), `CreateNamespace=true`,
  `ServerSideApply=true`, `SkipDryRunOnMissingResource=true`.

## Prerequisites (user actions)

1. Create a Hetzner Object Storage bucket and an access key / secret key pair.
2. Provide them so they can be SOPS-encrypted into `mimir-objstore.secret.yaml`.
3. Confirm the bucket region for the S3 endpoint.

## Verification

- `kustomize build --enable-helm kustomize/bases/mimir` renders clean.
- Rendered config shows `multitenancy_enabled: true`, `replication_factor: 1`,
  and the Hetzner S3 endpoint.
- Post-sync: Mimir pods Ready, `/ready` green.
- A test write to `http://homelab-mimir.k8s.specht-labs.de/api/v1/push` returns
  200, and a query for that sample with `X-Scope-OrgID: homelab` returns it,
  while the same query under another tenant returns nothing (isolation holds).

## Risks / notes

- Single ingester + RF1 means no metrics HA: an ingester restart can lose the
  most recent unflushed window. With ingest-storage, Kafka buffers the write so
  a restarting ingester replays from the topic, which softens this. Scale
  ingesters + RF to 3 later if needed.
- Single-node Kafka is a SPOF: if it's down, writes stop (ingesters consume
  from it). Consistent with the non-HA homelab posture; revisit if uptime
  matters more later.
- Mimir lives on the cluster it may also monitor; for pure homelab-Pi metrics
  this is fine (the source is off-cluster).
- Exact chart value keys (front proxy component name, env injection field) are
  resolved against the pinned chart version during implementation.
