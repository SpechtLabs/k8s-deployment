#!/usr/bin/env python3
"""Generate the Ceph CSI (RBD) dashboard for labk3s.

Run: python3 hack/gen-ceph-csi-dashboard.py > components/grafana-dashboards/ceph/ceph-csi-rbd.json

Everything is in the homelab Mimir tenant: ceph-csi's own metrics (liveness,
the provisioner/attacher/resizer sidecars' csi_sidecar_operations_seconds) via
k8s-monitoring's annotation autodiscovery on labk3s, kubelet volume stats and
kube-state-metrics from k8s-monitoring, and the Ceph side (pool, per-image RBD
stats for the k3s pool) from the storage Pis' Alloy (cluster=homelab-ceph).
PVCs and RBD images can't be joined (kube_persistentvolume_info, which holds
the CSI volume handle, isn't collected), so they are shown side by side.
"""
import json

DS = {"type": "prometheus", "uid": "${datasource}"}
K8S = 'cluster="$k8s_cluster"'
CSI = K8S + ', namespace="ceph-csi-rbd"'
DRIVER = 'driver_name="rbd.csi.ceph.com"'
# Sidecar calls that are only discovery/housekeeping, not volume operations.
NOISE = 'method_name!~".*/(Probe|GetPluginInfo|GetPluginCapabilities|ControllerGetCapabilities|NodeGetCapabilities|NodeGetInfo)"'
CEPH = 'cluster="$ceph_cluster"'
# PVCs of the storage class, as a filter: `and on(namespace, persistentvolumeclaim) $PVCS`.
PVCS = 'kube_persistentvolumeclaim_info{' + K8S + ', storageclass="$storageclass"}'
# Pool series carry pool_id; ceph_pool_metadata maps it to the name.
POOL = 'on(pool_id) group_left(name) ceph_pool_metadata{' + CEPH + ', name="$pool"}'

panels = []
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def gp(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False, "gridPos": gp(0, y, 24, 1), "panels": []}


def target(expr, legend="", instant=False, ref="A", fmt="time_series"):
    t = {"datasource": DS, "expr": expr, "refId": ref, "legendFormat": legend, "format": fmt}
    if instant:
        t["instant"] = True
        t["range"] = False
    return t


def thresholds(*steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def stat(title, x, y, w, h, expr, unit="none", desc="", th=None, decimals=None):
    fc = {"unit": unit, "thresholds": th or thresholds(("green", None))}
    if decimals is not None:
        fc["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": fc, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "none", "textMode": "value",
                    "justifyMode": "center", "orientation": "auto"},
        "targets": [target(expr, instant=True)],
    }


def ts(title, x, y, w, h, targets, unit="none", desc="", stack=False, legend_calcs=None, min0=True):
    custom = {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 15 if stack else 8, "showPoints": "never",
              "spanNulls": True, "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    defaults = {"unit": unit, "custom": custom}
    if min0:
        defaults["min"] = 0
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "table" if legend_calcs else "list", "placement": "bottom",
                               "calcs": legend_calcs or []},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": targets,
    }


def bargauge(title, x, y, w, h, expr, legend, unit="percent", desc=""):
    return {
        "id": nid(), "type": "bargauge", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": 100,
                                     "thresholds": thresholds(("green", None), ("orange", 75), ("red", 90))},
                        "overrides": []},
        "options": {"displayMode": "gradient", "orientation": "horizontal", "showUnfilled": True,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
        "targets": [target(expr, legend=legend, instant=True)],
    }


def volume_table(title, x, y, w, h, desc=""):
    """One row per PVC of the storage class: capacity, used, used %, inodes %, node."""
    ref = "and on(namespace, persistentvolumeclaim) " + PVCS
    exprs = {
        "A": ("kubelet_volume_stats_capacity_bytes{" + K8S + "} " + ref),
        "B": ("kubelet_volume_stats_used_bytes{" + K8S + "} " + ref),
        "C": ("100 * kubelet_volume_stats_used_bytes{" + K8S + "} / kubelet_volume_stats_capacity_bytes{" + K8S + "} " + ref),
        "D": ("100 * kubelet_volume_stats_inodes_used{" + K8S + "} / kubelet_volume_stats_inodes{" + K8S + "} " + ref),
    }
    targets = [target(e, instant=True, ref=r, fmt="table") for r, e in exprs.items()]
    keep = ["namespace", "persistentvolumeclaim", "node", "Value #A", "Value #B", "Value #C", "Value #D"]
    return {
        "id": nid(), "type": "table", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {
            "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
            "overrides": [
                {"matcher": {"id": "byName", "options": "Capacity"}, "properties": [{"id": "unit", "value": "bytes"}]},
                {"matcher": {"id": "byName", "options": "Used"}, "properties": [{"id": "unit", "value": "bytes"}]},
                *[{"matcher": {"id": "byName", "options": n},
                   "properties": [{"id": "unit", "value": "percent"}, {"id": "decimals", "value": 1},
                                  {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
                                  {"id": "thresholds", "value": thresholds(("green", None), ("orange", 75), ("red", 90))}]}
                  for n in ("Used %", "Inodes used %")],
            ],
        },
        "options": {"showHeader": True, "sortBy": [{"displayName": "Used %", "desc": True}]},
        "targets": targets,
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {}, "includeByName": {k: True for k in keep},
                "indexByName": {k: i for i, k in enumerate(keep)},
                "renameByName": {"namespace": "Namespace", "persistentvolumeclaim": "PVC", "node": "Node",
                                 "Value #A": "Capacity", "Value #B": "Used", "Value #C": "Used %",
                                 "Value #D": "Inodes used %"}}},
        ],
    }


y = 0
panels.append(row("Driver health", y)); y += 1
panels += [
    stat("Node plugins live", 0, y, 4, 4,
         'sum(csi_liveness{' + CSI + ', job="ceph-csi-rbd/nodeplugin"})',
         desc="Node plugin pods whose liveness probe reaches the CSI driver (one per labk3s node).",
         th=thresholds(("red", None), ("green", 1))),
    stat("Provisioners live", 4, y, 4, 4,
         'sum(csi_liveness{' + CSI + ', job="ceph-csi-rbd/provisioner"})',
         desc="Provisioner pods (leader-elected; one does the work, the other stands by).",
         th=thresholds(("red", None), ("green", 1))),
    stat("Restarts (24h)", 8, y, 4, 4,
         'sum(increase(kube_pod_container_status_restarts_total{' + CSI + '}[24h])) or vector(0)',
         desc="Container restarts in ceph-csi-rbd over the last 24 hours.",
         th=thresholds(("green", None), ("orange", 1), ("red", 5)), decimals=0),
    stat("PVCs", 12, y, 4, 4, 'count(' + PVCS + ') or vector(0)',
         desc="PersistentVolumeClaims of the storage class."),
    stat("Requested", 16, y, 4, 4,
         'sum(kube_persistentvolumeclaim_resource_requests_storage_bytes{' + K8S + '} and on(namespace, persistentvolumeclaim) ' + PVCS + ') or vector(0)',
         unit="bytes", desc="Sum of the PVCs' requested sizes (thin-provisioned in Ceph)."),
    stat("Pool used", 20, y, 4, 4,
         '100 * (ceph_pool_percent_used{' + CEPH + '} * ' + POOL + ')',
         unit="percent", desc="Ceph pool $pool: share of what it can still grow to (replicated).",
         th=thresholds(("green", None), ("orange", 70), ("red", 85)), decimals=2),
]
y += 4

panels.append(row("CSI operations (provisioner sidecars)", y)); y += 1
OPS = 'csi_sidecar_operations_seconds_count{' + CSI + ', ' + DRIVER + ', ' + NOISE + '}'
panels += [
    ts("Operations", 0, y, 8, 8,
       [target('sum by (method_name) (rate(' + OPS + '[$__rate_interval]))', legend="{{method_name}}")],
       unit="ops", desc="Volume operations the sidecars call on the driver: CreateVolume, DeleteVolume, ControllerPublish/Unpublish, ControllerExpand."),
    ts("Errors", 8, y, 8, 8,
       [target('sum by (method_name, grpc_status_code) (rate(csi_sidecar_operations_seconds_count{' + CSI + ', ' + DRIVER + ', grpc_status_code!="OK"}[$__rate_interval]))',
               legend="{{method_name}} {{grpc_status_code}}")],
       unit="ops", desc="Calls that returned a gRPC error, by method and code."),
    ts("Latency p95", 16, y, 8, 8,
       [target('histogram_quantile(0.95, sum by (le, method_name) (rate(csi_sidecar_operations_seconds_bucket{' + CSI + ', ' + DRIVER + ', ' + NOISE + '}[$__rate_interval])))',
               legend="{{method_name}}")],
       unit="s", desc="95th percentile duration of volume operations."),
]
y += 8
panels += [
    ts("PVC provisioning", 0, y, 12, 7,
       [target('sum by (class) (increase(controller_persistentvolumeclaim_provision_total{' + CSI + '}[$__rate_interval]))', legend="provisioned ({{class}})"),
        target('sum by (class) (increase(controller_persistentvolumeclaim_provision_failed_total{' + CSI + '}[$__rate_interval]))', legend="failed ({{class}})", ref="B")],
       unit="short", desc="PVCs provisioned and failed by the external-provisioner."),
    ts("Provisioning duration p95", 12, y, 12, 7,
       [target('histogram_quantile(0.95, sum by (le, class) (rate(controller_persistentvolumeclaim_provision_duration_seconds_bucket{' + CSI + '}[$__rate_interval])))', legend="{{class}}")],
       unit="s", desc="From PVC to bound PV, 95th percentile."),
]
y += 7

panels.append(row("Volumes (storage class $storageclass)", y)); y += 1
panels += [
    volume_table("Mounted volumes", 0, y, 14, 9,
                 desc="Kubelet volume stats of mounted PVCs of the storage class (unmounted ones report nothing)."),
    bargauge("Used", 14, y, 10, 9,
             '100 * kubelet_volume_stats_used_bytes{' + K8S + '} / kubelet_volume_stats_capacity_bytes{' + K8S + '} and on(namespace, persistentvolumeclaim) ' + PVCS,
             "{{namespace}}/{{persistentvolumeclaim}}"),
]
y += 9
panels += [
    ts("Volume usage", 0, y, 24, 7,
       [target('kubelet_volume_stats_used_bytes{' + K8S + '} and on(namespace, persistentvolumeclaim) ' + PVCS,
               legend="{{namespace}}/{{persistentvolumeclaim}}")],
       unit="bytes", desc="Used bytes per PVC over time."),
]
y += 7

panels.append(row("Ceph: pool $pool and its RBD images", y)); y += 1
RBD = '{' + CEPH + ', pool="$pool"}'
panels += [
    ts("Pool capacity", 0, y, 8, 8,
       [target('ceph_pool_stored{' + CEPH + '} * ' + POOL, legend="stored"),
        target('ceph_pool_max_avail{' + CEPH + '} * ' + POOL, legend="max available", ref="B")],
       unit="bytes", desc="Data stored in the pool (before replication) and what it can still take."),
    ts("Image IOPS", 8, y, 8, 8,
       [target('sum by (image) (rate(ceph_rbd_write_ops' + RBD + '[$__rate_interval]))', legend="{{image}} write"),
        target('sum by (image) (rate(ceph_rbd_read_ops' + RBD + '[$__rate_interval]))', legend="{{image}} read", ref="B")],
       unit="iops", desc="Per RBD image in the pool (mgr prometheus rbd_stats_pools). ceph-csi names them csi-vol-<uuid>."),
    ts("Image throughput", 16, y, 8, 8,
       [target('sum by (image) (rate(ceph_rbd_write_bytes' + RBD + '[$__rate_interval]))', legend="{{image}} write"),
        target('sum by (image) (rate(ceph_rbd_read_bytes' + RBD + '[$__rate_interval]))', legend="{{image}} read", ref="B")],
       unit="Bps"),
]
y += 8
panels += [
    ts("Image latency", 0, y, 24, 7,
       [target('sum by (image) (rate(ceph_rbd_write_latency_sum' + RBD + '[$__rate_interval])) / sum by (image) (rate(ceph_rbd_write_latency_count' + RBD + '[$__rate_interval]))', legend="{{image}} write"),
        target('sum by (image) (rate(ceph_rbd_read_latency_sum' + RBD + '[$__rate_interval])) / sum by (image) (rate(ceph_rbd_read_latency_count' + RBD + '[$__rate_interval]))', legend="{{image}} read", ref="B")],
       unit="s", desc="Average write/read latency per image as Ceph sees it."),
]


def query_var(name, label, query, current):
    return {"name": name, "label": label, "type": "query", "datasource": DS,
            "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
            "definition": query, "refresh": 2, "sort": 1, "includeAll": False, "multi": False,
            "current": {"selected": True, "text": current, "value": current}}


dashboard = {
    "uid": "ceph-csi-rbd",
    "title": "Ceph CSI (RBD)",
    "description": "ceph-csi on labk3s: driver health, volume operations, PVC usage and the backing Ceph pool.",
    "tags": ["ceph", "csi", "labk3s"],
    "timezone": "browser",
    "editable": False,
    "graphTooltip": 1,
    "refresh": "1m",
    "schemaVersion": 39,
    "time": {"from": "now-6h", "to": "now"},
    "links": [{"title": "Ceph dashboards", "type": "dashboards", "tags": ["ceph"], "asDropdown": True,
               "includeVars": False, "keepTime": True}],
    "templating": {"list": [
        {"name": "datasource", "label": "Data source", "type": "datasource", "query": "prometheus",
         "current": {"selected": True, "text": "Mimir (homelab)", "value": "mimir-homelab"}, "hide": 0},
        query_var("k8s_cluster", "Kubernetes cluster", "label_values(csi_liveness, cluster)", "labk3s"),
        query_var("storageclass", "Storage class",
                  'label_values(kube_persistentvolumeclaim_info{cluster="$k8s_cluster", storageclass=~"ceph.*"}, storageclass)',
                  "ceph-rbd"),
        query_var("ceph_cluster", "Ceph cluster", "label_values(ceph_health_status, cluster)", "homelab-ceph"),
        query_var("pool", "Pool", 'label_values(ceph_pool_metadata{cluster="$ceph_cluster"}, name)', "k3s"),
    ]},
    "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                              "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                              "name": "Annotations & Alerts", "type": "dashboard"}]},
    "panels": panels,
}

print(json.dumps(dashboard, indent=2))
