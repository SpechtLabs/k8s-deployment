#!/usr/bin/env python3
"""Generate the Ceph - Status dashboard: what is broken, and on which host.

Run: python3 hack/gen-ceph-status-dashboard.py > components/grafana-dashboards/ceph/ceph-status.json

The ceph-mixin dashboards count OSDs and mons but never say which one is down
or where it runs. This one starts from the hosts: per host, how many cephadm
daemons run, whether its OSD is up and its mon in quorum, and whether its
exporters are scraped; then the active health checks, every daemon, OSD and
mon by name, and state timelines to see when something stopped. The ceph-health
alerts (apps/grafana-operator/cluster/specht-labs/grafanaalertrules-ceph.yaml)
link here, to panels by id: ids are numbered in the order below, so moving a
panel means updating the rules' __panelId__.

Data: the active mgr's prometheus module (job ceph_mgr) and ceph-exporter on
each storage Pi, written to the homelab Mimir tenant by Alloy
(SpechtLabs/homelab, vars/group-ceph.yaml). ceph_cephadm_daemon_status comes from
cephadm's inventory, which it refreshes every few minutes; ceph_osd_up and
ceph_mon_quorum_status are the cluster's own view and change at once.
"""
import json

DS = {"type": "prometheus", "uid": "${datasource}"}
C = 'cluster="$cluster"'
# Muted on purpose (SpechtLabs/homelab vars/group-ceph.yaml, ceph_health_mutes): the
# mgr still exports them as active, so they are shown as "muted".
MUTED = "AUTH_INSECURE_CLIENT_KEY_TYPE|AUTH_INSECURE_KEYS_ALLOWED|AUTH_INSECURE_KEYS_CREATABLE"

# Series from the active mgr carry its scrape target as `instance`; after a
# failover two mgrs' series overlap for a scrape or two. Aggregating by the
# daemon first keeps the joins one-to-one.
OSD_HOST = 'max by (ceph_daemon, hostname) (ceph_osd_metadata{' + C + '})'
MON_HOST = 'max by (ceph_daemon, hostname) (ceph_mon_metadata{' + C + '})'
OSD_UP = 'max by (ceph_daemon) (ceph_osd_up{' + C + '}) * on(ceph_daemon) group_left(hostname) ' + OSD_HOST
OSD_IN = 'max by (ceph_daemon) (ceph_osd_in{' + C + '}) * on(ceph_daemon) group_left(hostname) ' + OSD_HOST
MON_Q = 'max by (ceph_daemon) (ceph_mon_quorum_status{' + C + '}) * on(ceph_daemon) group_left(hostname) ' + MON_HOST
DAEMONS = 'max by (hostname, daemon_name, service_type) (ceph_cephadm_daemon_status{' + C + '})'
# Alloy on each host scrapes its own ceph-exporter (and mgr); `instance` is host:port.
EXPORTER_UP = 'max by (hostname) (label_replace(up{' + C + ', job="ceph_exporter"}, "hostname", "$1", "instance", "([^:]+):.*"))'

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


def vmap(*entries):
    """value mappings: (value, text, color)."""
    return [{"type": "value", "options": {str(v): {"text": t, "color": c, "index": i}
                                          for i, (v, t, c) in enumerate(entries)}}]


DAEMON_STATES = vmap((-2, "unknown", "orange"), (-1, "error", "red"), (0, "stopped", "red"),
                     (1, "running", "green"), (2, "starting", "orange"))
UP_DOWN = vmap((0, "down", "red"), (1, "up", "green"))
IN_OUT = vmap((0, "out", "orange"), (1, "in", "green"))
QUORUM = vmap((0, "out of quorum", "red"), (1, "in quorum", "green"))
HEALTH = vmap((0, "HEALTH_OK", "green"), (1, "HEALTH_WARN", "orange"), (2, "HEALTH_ERR", "red"))


def stat(title, x, y, w, h, expr, desc="", th=None, mappings=None, unit="none"):
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": {"unit": unit, "thresholds": th or thresholds(("green", None)),
                                     "mappings": mappings or [], "noValue": "0"},
                        "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "none", "textMode": "value",
                    "justifyMode": "center", "orientation": "auto"},
        "targets": [target(expr, instant=True)],
    }


def colored(name, mappings=None, th=None, unit=None):
    props = [{"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}}]
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    if th:
        props.append({"id": "thresholds", "value": th})
    if unit:
        props.append({"id": "unit", "value": unit})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def table(title, x, y, w, h, exprs, columns, overrides, sort, desc="", no_value=""):
    """exprs: {refId: expr}, all instant tables with the same label set, merged
    into one row per label combination. columns: [(field, display name)]."""
    return {
        "id": nid(), "type": "table", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}},
                                     "noValue": no_value},
                        "overrides": overrides},
        "options": {"showHeader": True, "cellHeight": "sm", "sortBy": sort},
        "targets": [target(e, instant=True, ref=r, fmt="table") for r, e in exprs.items()],
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {}, "includeByName": {k: True for k, _ in columns},
                "indexByName": {k: i for i, (k, _) in enumerate(columns)},
                "renameByName": dict(columns)}},
        ],
    }


def timeline(title, x, y, w, h, targets, mappings, desc="", th=None):
    return {
        "id": nid(), "type": "state-timeline", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": {"mappings": mappings, "color": {"mode": "thresholds"},
                                     "thresholds": th or thresholds(("green", None)),
                                     "custom": {"fillOpacity": 80, "lineWidth": 0}},
                        "overrides": []},
        "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.85, "alignValue": "left",
                    "legend": {"showLegend": False}, "tooltip": {"mode": "single", "sort": "none"}},
        "targets": targets,
    }


y = 0
panels.append(row("Now", y)); y += 1
panels += [
    stat("Health", 0, y, 4, 4, 'max(ceph_health_status{' + C + '})', mappings=HEALTH,
         desc="The cluster's overall status; muted checks don't count.",
         th=thresholds(("green", None), ("orange", 1), ("red", 2))),
    stat("Daemons not running", 4, y, 4, 4,
         'count(ceph_cephadm_daemon_status{' + C + '} != 1) or vector(0)',
         desc="cephadm daemons (mon, mgr, osd, rgw, crash, ceph-exporter) in any state but running. "
              "The Daemons table says which and where.",
         th=thresholds(("green", None), ("red", 1))),
    stat("OSDs down", 8, y, 4, 4, 'count(ceph_osd_up{' + C + '} == 0) or vector(0)',
         th=thresholds(("green", None), ("orange", 1), ("red", 2)),
         desc="Size-3 pools with min_size 2: one OSD down keeps I/O going, two block writes."),
    stat("Mons out of quorum", 12, y, 4, 4, 'count(ceph_mon_quorum_status{' + C + '} == 0) or vector(0)',
         th=thresholds(("green", None), ("orange", 1), ("red", 2)),
         desc="Three mons; the cluster needs two in quorum."),
    stat("PGs not active+clean", 16, y, 4, 4,
         'sum(ceph_pg_total{' + C + '}) - sum(ceph_pg_clean{' + C + '} and ceph_pg_active{' + C + '})',
         th=thresholds(("green", None), ("orange", 1)),
         desc="Degraded, undersized, peering or recovering placement groups."),
    stat("Objects degraded", 20, y, 4, 4,
         'sum(ceph_num_objects_degraded{' + C + '})',
         th=thresholds(("green", None), ("orange", 1)),
         desc="Object copies that are missing a replica (ceph -s: objects degraded)."),
]
y += 4

host_cols = [("hostname", "Host"), ("Value #A", "Daemons running"), ("Value #B", "Not running"),
             ("Value #C", "OSD"), ("Value #D", "Mon"), ("Value #E", "Exporter scraped")]
panels.append(table(
    "Hosts", 0, y, 24, 5,
    {
        "A": 'count by (hostname) (ceph_cephadm_daemon_status{' + C + '} == 1) or count by (hostname) (ceph_cephadm_daemon_status{' + C + '}) * 0',
        "B": 'count by (hostname) (ceph_cephadm_daemon_status{' + C + '} != 1) or count by (hostname) (ceph_cephadm_daemon_status{' + C + '}) * 0',
        "C": 'min by (hostname) (' + OSD_UP + ')',
        "D": 'min by (hostname) (' + MON_Q + ')',
        "E": EXPORTER_UP,
    },
    host_cols,
    [colored("Not running", th=thresholds(("green", None), ("red", 1))),
     colored("OSD", mappings=UP_DOWN), colored("Mon", mappings=QUORUM),
     colored("Exporter scraped", mappings=vmap((0, "no", "red"), (1, "yes", "green")))],
    [{"displayName": "Host", "desc": False}],
    desc="One row per storage Pi. Not running > 0: see Daemons. OSD down or mon out of quorum with "
         "everything running: the daemon runs but can't reach the others (network, tailnet). "
         "Exporter not scraped and the rest stale: the host itself or its Alloy is down.",
    no_value="-",
))
y += 5

panels.append(table(
    "Active health checks", 0, y, 8, 8,
    {"A": 'max by (name, severity) (ceph_health_detail{' + C + ', name!~"' + MUTED + '"} == 1)'
          ' or max by (name, severity) (label_replace(ceph_health_detail{' + C + ', name=~"' + MUTED + '"} == 1, "severity", "muted", "", ""))'},
    [("name", "Check"), ("severity", "Severity")],
    [colored("Severity", mappings=[{"type": "value", "options": {
        "HEALTH_WARN": {"text": "HEALTH_WARN", "color": "orange", "index": 0},
        "HEALTH_ERR": {"text": "HEALTH_ERR", "color": "red", "index": 1},
        "muted": {"text": "muted", "color": "transparent", "index": 2}}}])],
    [{"displayName": "Severity", "desc": False}],
    desc="What `ceph health detail` reports. The AUTH_INSECURE_* checks are muted on purpose "
         "(client.k3s's AES-128 key, SpechtLabs/homelab ceph_health_mutes). For the PGs or daemons a "
         "check is about: `sudo cephadm shell -- ceph health detail` on any storage Pi.",
))
panels.append(table(
    "Daemons", 8, y, 16, 8,
    {"A": DAEMONS},
    [("hostname", "Host"), ("service_type", "Type"), ("daemon_name", "Daemon"), ("Value", "Status")],
    [colored("Status", mappings=DAEMON_STATES)],
    [{"displayName": "Status", "desc": False}],
    desc="Every daemon cephadm deployed, by host (`ceph orch ps`). cephadm refreshes this every few "
         "minutes. A stopped daemon on host H: `ssh H sudo systemctl status ceph-<fsid>@<daemon>`; "
         "start it with `sudo cephadm shell -- ceph orch daemon start <daemon>`.",
))
y += 8

panels.append(table(
    "OSDs", 0, y, 12, 5,
    {"A": OSD_UP, "B": OSD_IN,
     "C": 'max by (ceph_daemon) (ceph_osd_stat_bytes_used{' + C + '} / ceph_osd_stat_bytes{' + C + '}) * on(ceph_daemon) group_left(hostname) ' + OSD_HOST},
    [("ceph_daemon", "OSD"), ("hostname", "Host"), ("Value #A", "Up"), ("Value #B", "In"), ("Value #C", "Used")],
    [colored("Up", mappings=UP_DOWN), colored("In", mappings=IN_OUT),
     colored("Used", th=thresholds(("green", None), ("orange", 0.75), ("red", 0.85)), unit="percentunit")],
    [{"displayName": "OSD", "desc": False}],
    desc="Down: the cluster has lost contact. Out: Ceph has moved its data elsewhere "
         "(after 10 min down, mon_osd_down_out_interval).",
))
panels.append(table(
    "Monitors", 12, y, 12, 5,
    {"A": MON_Q},
    [("ceph_daemon", "Mon"), ("hostname", "Host"), ("Value", "Quorum")],
    [colored("Quorum", mappings=QUORUM)],
    [{"displayName": "Mon", "desc": False}],
))
y += 5

panels.append(row("History", y)); y += 1
panels += [
    timeline("Daemon status", 0, y, 24, 12,
             [target(DAEMONS, legend="{{hostname}}  {{daemon_name}}")], DAEMON_STATES,
             desc="cephadm's view of every daemon over time, by host."),
]
y += 12
panels += [
    timeline("OSD up", 0, y, 12, 5, [target(OSD_UP, legend="{{hostname}}  {{ceph_daemon}}")], UP_DOWN),
    timeline("Mon quorum", 12, y, 12, 5, [target(MON_Q, legend="{{hostname}}  {{ceph_daemon}}")], QUORUM),
]
y += 5
panels += [
    timeline("Health checks", 0, y, 12, 8,
             [target('max by (name) (ceph_health_detail{' + C + ', name!~"' + MUTED + '"})', legend="{{name}}")],
             vmap((0, "clear", "transparent"), (1, "active", "orange")),
             desc="Each health check over time (muted ones left out)."),
    timeline("Exporters scraped", 12, y, 12, 8,
             [target('max by (instance) (up{' + C + '})', legend="{{instance}}")],
             vmap((0, "down", "red"), (1, "up", "green")),
             desc="Alloy on each storage Pi scraping its own mgr (:9283) and ceph-exporter (:9926). "
                  "A gap with no data means that host's Alloy wrote nothing: the host was down."),
]


def query_var(name, label, query, current):
    return {"name": name, "label": label, "type": "query", "datasource": DS,
            "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
            "definition": query, "refresh": 2, "sort": 1, "includeAll": False, "multi": False,
            "current": {"selected": True, "text": current, "value": current}}


dashboard = {
    "uid": "ceph-status",
    "title": "Ceph - Status",
    "description": "What is broken in the homelab Ceph cluster, and on which storage Pi.",
    "tags": ["ceph"],
    "timezone": "browser",
    "editable": False,
    "graphTooltip": 1,
    "refresh": "1m",
    "schemaVersion": 39,
    "time": {"from": "now-24h", "to": "now"},
    "links": [{"title": "Ceph dashboards", "type": "dashboards", "tags": ["ceph"], "asDropdown": True,
               "includeVars": False, "keepTime": True}],
    "templating": {"list": [
        {"name": "datasource", "label": "Data source", "type": "datasource", "query": "prometheus",
         "current": {"selected": True, "text": "Mimir (homelab)", "value": "mimir-homelab"}, "hide": 0},
        query_var("cluster", "Ceph cluster", "label_values(ceph_health_status, cluster)", "homelab-ceph"),
    ]},
    "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                              "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                              "name": "Annotations & Alerts", "type": "dashboard"}]},
    "panels": panels,
}

print(json.dumps(dashboard, indent=2))
