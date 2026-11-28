#!/usr/bin/env python3
"""Generate the UPS & NUT dashboard: is the house on battery, and will every host shut down?

Run: python3 hack/gen-ups-dashboard.py > components/grafana-dashboards/infrastructure/ups.json

The chain (SpechtLabs/homelab docs/elbschloss, reference/ups-and-nut): the
Ubiquiti UPS Tower, read by isa's upsd (a dummy-ups repeater), served to the
fleet as svc:nut. isa's upsmon is the primary that sets FSD on low battery;
every Pi and the NUC run upsmon as secondaries, the "early" ones powering off
60 s into an outage, the "late" ones (jumphost, timepi) on FSD.

Data, all in the homelab Mimir tenant via each host's Alloy textfile collector:
- ups_* from ups-metrics on isa (modules/nut-server), every 30 s: the UPS as
  isa's upsd serves it, upsd's login count, isa's primary upsmon;
- nut_client_* from nut-client-metrics on every NUT client
  (modules/nut-client), every 30 s: upsmon running, the UPS readable through
  svc:nut, the host's shutdown affinity.
upsd sees every client as 127.0.0.1 behind svc:nut, so only the clients' own
metrics say which host is missing. Logs: upsmon/upsd in the homelab Loki
tenant (journal, unit label).

The UPS alerts (apps/grafana-operator/cluster/specht-labs/grafanaalertrules-ups.yaml)
link here, to panels by id: ids are numbered in the order below, so moving a
panel means updating the rules' __panelId__.
"""
import json

DS = {"type": "prometheus", "uid": "${datasource}"}
LOGS = {"type": "loki", "uid": "${logs}"}
U = 'ups="ups"'


def host(expr):
    """instance is host:9100 on textfile series: a `host` label instead."""
    return 'label_replace(' + expr + ', "host", "$1", "instance", "([^:]+):.*")'


# The UPS's state as one number: 0 mains, 1 battery, 2 battery low, 3+ FSD.
STATE = ('max(ups_status{' + U + ', flag="OB"}) + max(ups_status{' + U + ', flag="LB"})'
         ' + 2 * max(ups_status{' + U + ', flag="FSD"})')
# Every NUT client that reported in the last week: a host that went dark
# still has a row, with its last report's age.
KNOWN = 'max by (host, affinity) (' + host('last_over_time(nut_client_info{' + U + '}[7d])') + ')'


def now(metric):
    """The client's current value, if it reported in the last 2 minutes."""
    return 'max by (host) (' + host('last_over_time(' + metric + '{' + U + '}[2m])') + ')'


panels = []
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def gp(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def row(title, y, collapsed=False, inner=None):
    return {"id": nid(), "type": "row", "title": title, "collapsed": collapsed, "gridPos": gp(0, y, 24, 1),
            "panels": inner or []}


def target(expr, legend="", instant=False, ref="A", fmt="time_series"):
    t = {"datasource": DS, "expr": expr, "refId": ref, "legendFormat": legend or "__auto", "format": fmt}
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


def rmap(lo, hi, text, color, index=10):
    return {"type": "range", "options": {"from": lo, "to": hi, "result": {"text": text, "color": color, "index": index}}}


RUNNING = vmap((0, "stopped", "red"), (1, "running", "green"))
YES_NO = vmap((0, "no", "red"), (1, "yes", "green"))
POWER = vmap((0, "On mains", "green"), (1, "On battery", "orange"), (2, "Battery low", "red")) + \
    [rmap(3, 10, "Forced shutdown", "dark-red")]


def stat(title, x, y, w, h, expr, desc="", th=None, mappings=None, unit="none", no_value="no data",
         decimals=None, graph=False):
    d = {"unit": unit, "thresholds": th or thresholds(("green", None)), "mappings": mappings or [],
         "noValue": no_value, "color": {"mode": "thresholds"}}
    if decimals is not None:
        d["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": d, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "area" if graph else "none", "textMode": "value",
                    "justifyMode": "center", "orientation": "auto", "wideLayout": True},
        "targets": [target(expr, instant=not graph)],
    }


def colored(name, mappings=None, th=None, unit=None, decimals=None):
    props = [{"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}}]
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    if th:
        props.append({"id": "thresholds", "value": th})
    if unit:
        props.append({"id": "unit", "value": unit})
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def plain(name, unit=None, mappings=None, decimals=None):
    props = []
    if unit:
        props.append({"id": "unit", "value": unit})
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def width(name, px):
    return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "custom.width", "value": px}]}


def table(title, x, y, w, h, exprs, columns, overrides, sort, desc="", no_value="-"):
    """exprs: {refId: expr}, instant tables keyed by the same labels, merged
    into one row per key. columns: [(field, display name)]."""
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


def timeline(title, x, y, w, h, targets, mappings, desc="", overrides=None, row_height=0.85, th=None):
    return {
        "id": nid(), "type": "state-timeline", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": {"mappings": mappings, "color": {"mode": "thresholds"},
                                     "thresholds": th or thresholds(("green", None)),
                                     "custom": {"fillOpacity": 80, "lineWidth": 0}},
                        "overrides": overrides or []},
        "options": {"showValue": "never", "mergeValues": True, "rowHeight": row_height, "alignValue": "left",
                    "legend": {"showLegend": False}, "tooltip": {"mode": "single", "sort": "none"}},
        "targets": targets,
    }


def series(title, x, y, w, h, targets, unit, desc="", overrides=None, min_=None, max_=None, decimals=None,
           legend="list", stack=False, bars=False, from_zero=True):
    d = {"unit": unit, "color": {"mode": "palette-classic"},
         "custom": {"drawStyle": "bars" if bars else "line", "lineWidth": 1, "fillOpacity": 80 if bars else 10,
                    "showPoints": "never", "spanNulls": False, "axisSoftMin": 0 if (min_ is None and from_zero) else None,
                    "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}
    if min_ is not None:
        d["min"] = min_
    if max_ is not None:
        d["max"] = max_
    if decimals is not None:
        d["decimals"] = decimals
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": gp(x, y, w, h),
        "fieldConfig": {"defaults": d, "overrides": overrides or []},
        "options": {"legend": {"showLegend": True, "displayMode": legend, "placement": "bottom",
                               "calcs": ["lastNotNull", "min", "max"] if legend == "table" else []},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": targets,
    }


def right_axis(name, unit, decimals=None, min_=None):
    props = [{"id": "unit", "value": unit}, {"id": "custom.axisPlacement", "value": "right"}]
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    if min_ is not None:
        props.append({"id": "min", "value": min_})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def color(name, c):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}


# ── Now ──────────────────────────────────────────────────────────────────────
y = 0
panels.append(row("Now", y)); y += 1
panels += [
    stat("Power", 0, y, 4, 4, STATE, mappings=POWER, no_value="no data",
         th=thresholds(("green", None), ("orange", 1), ("red", 2), ("dark-red", 3)),
         desc="On battery: the early hosts (labk3s, Ceph, the blades, the NUC) power off after 60 s. "
              "Battery low: isa sets FSD, jumphost and timepi go, isa goes last. "
              "No data: ups-metrics on isa isn't reporting (see Metrics age)."),
    stat("Battery", 4, y, 3, 4, 'max(ups_battery_charge_percent{' + U + '})', unit="percent",
         th=thresholds(("red", None), ("orange", 30), ("green", 60)),
         desc="battery.charge. It recharges to 100 % within hours after an outage."),
    stat("Runtime left", 7, y, 3, 4, 'min(ups_battery_runtime_seconds{' + U + '})', unit="s",
         th=thresholds(("red", None), ("orange", 600), ("green", 900)),
         desc="battery.runtime, the UPS's estimate at the current load. The ups-runtime-low alert "
              "pages under 10 minutes on battery."),
    stat("Load", 10, y, 2, 4, 'max(ups_load_percent{' + U + '})', unit="percent",
         th=thresholds(("green", None), ("orange", 70), ("red", 90)),
         desc="ups.load, percent of 600 W nominal. More load, less runtime."),
    stat("Mains", 12, y, 3, 4, 'max(ups_input_voltage_volts{' + U + '})', unit="volt", decimals=0,
         th=thresholds(("red", None), ("green", 207), ("red", 253)),
         desc="input.voltage. Outside 230 V ±10 % the UPS regulates or switches to battery."),
    stat("Primary (isa)", 15, y, 3, 4, 'max(ups_primary_monitor_up{' + U + '})', mappings=RUNNING,
         th=thresholds(("red", None), ("green", 1)),
         desc="isa's upsmon, the only one that sets FSD on low battery. Stopped: on low battery the "
              "secondaries still go after HOSTSYNC, but isa itself doesn't. Logged in is the Buckle "
              "check nut-server/primary."),
    stat("Clients missing", 18, y, 3, 4,
         '(count(' + KNOWN + ') + 1) - max(ups_clients{' + U + '})',
         th=thresholds(("green", None), ("red", 1)), no_value="?",
         desc="NUT clients (and isa's primary) that reported in the last 7 days but aren't logged in "
              "to upsd now. The Clients table says which."),
    stat("Metrics age", 21, y, 3, 4, 'time() - max(ups_metrics_last_success_timestamp_seconds{' + U + '})',
         unit="s", decimals=0, th=thresholds(("green", None), ("orange", 120), ("red", 300)),
         desc="Since ups-metrics on isa last read the UPS through upsd (every 30 s). Over 300 s: "
              "the alert ups-metrics-stale; every panel above is out of date."),
]
y += 4

# ── Clients ──────────────────────────────────────────────────────────────────
client_cols = [("host", "Host"), ("affinity", "Affinity"), ("Value #B", "Powers off"),
               ("Value #C", "FINALDELAY"), ("Value #D", "upsmon"), ("Value #E", "UPS reachable"),
               ("Value #F", "Round trip"), ("Value #G", "Last report")]
panels.append(table(
    "Clients", 0, y, 16, 16,
    {
        "A": KNOWN,
        # Early hosts: seconds on battery. Late hosts: -1, shown as "on FSD".
        "B": now('nut_client_onbatt_grace_seconds') + ' or (' + now('nut_client_info') + ' * 0 - 1)',
        "C": now('nut_client_finaldelay_seconds'),
        "D": now('nut_client_monitor_up'),
        "E": now('nut_client_ups_reachable'),
        "F": now('nut_client_ups_read_duration_seconds'),
        "G": 'time() - max by (host) (' + host('last_over_time(nut_client_metrics_timestamp_seconds{' + U + '}[7d])') + ')',
    },
    client_cols,
    [width("Host", 150), width("Affinity", 95), width("FINALDELAY", 130), width("upsmon", 90),
     width("UPS reachable", 135),
     plain("Powers off", unit="suffix: s on battery",
           mappings=vmap((-1, "on FSD (low battery)", "text"))),
     plain("FINALDELAY", unit="s"),
     colored("upsmon", mappings=RUNNING),
     colored("UPS reachable", mappings=YES_NO),
     colored("Round trip", unit="s", th=thresholds(("transparent", None), ("orange", 1), ("red", 5))),
     colored("Last report", unit="s", decimals=0, th=thresholds(("transparent", None), ("orange", 150), ("red", 300)))],
    [{"displayName": "Host", "desc": False}],
    desc="Every NUT client that reported in the last 7 days (nut-client-metrics, every 30 s). "
         "upsmon stopped or UPS not reachable: that host won't shut down on a power loss. "
         "Last report old and the rest '-': the host or its Alloy is down. "
         "Early hosts power off that long after the UPS goes on battery (ONLINE cancels it); "
         "late hosts on FSD, which isa sets on low battery. isa is the primary, not listed here.",
))
panels.append(series(
    "upsmon logins at upsd", 16, y, 8, 16,
    [target('max(ups_clients{' + U + '})', legend="logged in"),
     target('count(nut_client_info{' + U + '}) + 1', legend="clients reporting + isa", ref="B")],
    "none", decimals=0,
    overrides=[color("logged in", "green"),
               {"matcher": {"id": "byName", "options": "clients reporting + isa"},
                "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}},
                               {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}},
                               {"id": "custom.fillOpacity", "value": 0}]}],
    desc="`upsc -c ups@localhost` on isa: one login per running upsmon, isa's primary included. "
         "Below the dashed line: a host that is up isn't logged in. Both drop together: a host is down.",
))
y += 16

# ── Power over time ──────────────────────────────────────────────────────────
FLAG_COLORS = {"OL": "green", "OB": "orange", "LB": "red", "FSD": "dark-red", "CHRG": "blue",
               "DISCHRG": "orange", "RB": "red", "OVER": "red", "BYPASS": "orange", "OFF": "red"}
panels.append(row("Power over time", y)); y += 1
panels.append(timeline(
    "UPS status flags", 0, y, 24, 7,
    [target('max(ups_status{' + U + ', flag="' + f + '"})', legend=f, ref=f) for f in FLAG_COLORS],
    [],
    overrides=[{"matcher": {"id": "byFrameRefID", "options": f},
                "properties": [{"id": "thresholds", "value": thresholds(("transparent", None), (c, 1))}]}
               for f, c in FLAG_COLORS.items()],
    desc="ups.status as isa's upsd serves it (FSD is upsd's own flag). OL on mains, OB on battery, "
         "LB battery low, FSD forced shutdown, CHRG/DISCHRG charging, RB replace battery. "
         "A gap in every row: ups-metrics wasn't reporting.",
    row_height=0.8,
))
y += 7
panels += [
    series("Battery", 0, y, 12, 8,
           [target('max(ups_battery_charge_percent{' + U + '})', legend="charge"),
            target('min(ups_battery_runtime_seconds{' + U + '})', legend="runtime left", ref="B")],
           "percent", min_=0,
           overrides=[right_axis("runtime left", "s", min_=0), color("charge", "green"), color("runtime left", "blue"),
                      {"matcher": {"id": "byName", "options": "charge"}, "properties": [{"id": "max", "value": 100}]}],
           desc="Charge and the UPS's runtime estimate. Runtime moves with the load even on mains."),
    series("Load", 12, y, 12, 8,
           [target('max(ups_load_percent{' + U + '})', legend="load"),
            target('max(ups_realpower_watts{' + U + '})', legend="real power", ref="B")],
           "percent", min_=0,
           overrides=[right_axis("real power", "watt", min_=0), color("load", "purple"), color("real power", "yellow")],
           desc="ups.load (percent of 600 W) and ups.realpower."),
]
y += 8
panels += [
    series("Mains", 0, y, 12, 8,
           [target('max(ups_input_voltage_volts{' + U + '})', legend="input"),
            target('max(ups_output_voltage_volts{' + U + '})', legend="output", ref="B"),
            target('max(ups_input_frequency_hertz{' + U + '})', legend="frequency", ref="C")],
           "volt", decimals=1, from_zero=False,
           overrides=[right_axis("frequency", "hertz", decimals=2), color("input", "blue"),
                      color("output", "green"), color("frequency", "text")],
           desc="input.voltage, output.voltage and input.frequency. Input dropping to 0 with output "
                "holding: the UPS is on battery."),
    series("Battery voltage and temperature", 12, y, 12, 8,
           [target('max(ups_battery_voltage_volts{' + U + '})', legend="battery voltage"),
            target('max(ups_temperature_celsius{' + U + '})', legend="temperature", ref="B")],
           "volt", decimals=1, from_zero=False,
           overrides=[right_axis("temperature", "celsius", decimals=0), color("battery voltage", "green"),
                      color("temperature", "orange")],
           desc="battery.voltage (12 V lead-acid: ~13.5 V floating on mains) and ups.temperature."),
]
y += 8

# ── Clients over time ────────────────────────────────────────────────────────
CLIENT_STATE = vmap((0, "upsmon stopped, UPS unreachable", "red"), (1, "upsmon stopped", "red"),
                    (2, "UPS unreachable", "orange"), (3, "ok", "green"))
panels.append(row("Clients over time", y)); y += 1
panels += [
    timeline("Client state", 0, y, 12, 11,
             [target('max by (host) (' + host('nut_client_monitor_up{' + U + '}') + ') * 2 + '
                     'max by (host) (' + host('nut_client_ups_reachable{' + U + '}') + ')', legend="{{host}}")],
             CLIENT_STATE, th=thresholds(("red", None), ("orange", 2), ("green", 3)),
             desc="Each client's upsmon and its read of the UPS through svc:nut. A gap: the host "
                  "wrote nothing (down, or its Alloy is)."),
    series("Round trip to upsd", 12, y, 12, 11,
           [target('max by (host) (' + host('nut_client_ups_read_duration_seconds{' + U + '}') + ')', legend="{{host}}")],
           "s", legend="table",
           desc="How long `upsc ups@nut.sphinx-map.ts.net ups.status` takes from each client: "
                "the tailnet path to isa plus upsd."),
]
y += 11
panels.append({
    "id": nid(), "type": "timeseries", "title": "upsmon and upsd problems (logs)", "datasource": LOGS,
    "description": "Lines from nut-monitor (every client and isa) and nut-server (isa) that say "
                   "something went wrong: data stale, communications lost, poll failed, server "
                   "disconnected. 'Data stale' on many hosts at once: isa's repeater lost the UPS Tower.",
    "gridPos": gp(0, y, 24, 7),
    "fieldConfig": {"defaults": {"unit": "short", "decimals": 0, "color": {"mode": "palette-classic"},
                                 "custom": {"drawStyle": "bars", "fillOpacity": 80, "lineWidth": 1,
                                            "stacking": {"mode": "normal", "group": "A"}, "showPoints": "never"}},
                    "overrides": []},
    "options": {"legend": {"showLegend": True, "displayMode": "list", "placement": "right"},
                "tooltip": {"mode": "multi", "sort": "desc"}},
    "interval": "5m",
    "targets": [{"datasource": LOGS, "refId": "A", "legendFormat": "{{hostname}}", "queryType": "range",
                 "expr": 'sum by (hostname) (count_over_time({job="loki.source.journal.log_syslog", unit=~"nut-monitor.service|nut-server.service"}'
                         ' |~ "(?i)stale|lost|failed|disconnected|not responding" [$__interval]))'}],
})
y += 7

# ── Battery health ───────────────────────────────────────────────────────────
panels.append(row("Battery health", y)); y += 1
panels += [
    stat("Last self-test", 0, y, 5, 4, 'time() - max(ups_test_last_timestamp_seconds{' + U + '})',
         unit="s", decimals=0, th=thresholds(("green", None), ("orange", 8 * 86400), ("red", 15 * 86400)),
         desc="ups.test.date. The UPS tests itself weekly (ups.test.interval 604800); the date has no time, "
              "so this is since midnight UTC that day."),
    stat("Self-test result", 5, y, 5, 4, 'max(ups_test_failed{' + U + '})',
         mappings=vmap((0, "passed", "green"), (1, "failed", "red")), th=thresholds(("green", None), ("red", 1)),
         desc="ups.test.result. Failed (or a warning) for 1h: the alert ups-replace-battery."),
    stat("Replace battery", 10, y, 4, 4, 'max(ups_status{' + U + ', flag="RB"})',
         mappings=vmap((0, "no", "green"), (1, "yes", "red")), th=thresholds(("green", None), ("red", 1)),
         desc="The UPS's RB flag."),
    stat("On battery in this range", 14, y, 5, 4,
         'avg_over_time(ups_status{' + U + ', flag="OB"}[$__range]) * $__range_s', unit="s", decimals=0,
         th=thresholds(("green", None), ("orange", 1)), no_value="0",
         desc="Time the UPS spent on battery in the dashboard's time range."),
    stat("Battery voltage", 19, y, 5, 4, 'max(ups_battery_voltage_volts{' + U + '})', unit="volt", decimals=1,
         th=thresholds(("red", None), ("orange", 12), ("green", 13)), graph=True,
         desc="battery.voltage. On mains a healthy battery floats around 13.5 V."),
]
y += 4

# ── Logs ─────────────────────────────────────────────────────────────────────
panels.append(row("Logs", y)); y += 1
panels.append({
    "id": nid(), "type": "logs", "title": "NUT logs", "datasource": LOGS,
    "description": "upsmon on every client and isa, upsd and the driver on isa, ups-metrics and "
                   "nut-client-metrics errors. upssched's shutdown lines come through nut-monitor.",
    "gridPos": gp(0, y, 24, 12),
    "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "dedupStrategy": "none",
                "enableLogDetails": True, "prettifyLogMessage": False},
    "targets": [{"datasource": LOGS, "refId": "A", "queryType": "range",
                 "expr": '{job="loki.source.journal.log_syslog", unit=~"nut-monitor.service|nut-server.service|nut-driver@.*|ups-metrics.service|nut-client-metrics.service"}'
                         ' | json MESSAGE | MESSAGE != "" | line_format "{{.hostname}}  {{.MESSAGE}}"'}],
})
y += 12


def ann(name, expr, c):
    return {"name": name, "datasource": DS, "enable": True, "hide": False, "iconColor": c,
            "expr": expr, "step": "30s", "titleFormat": name, "textFormat": "",
            "useValueForTime": False}


dashboard = {
    "uid": "ups-nut",
    "title": "UPS & NUT",
    "description": "The homelab UPS (Ubiquiti UPS Tower) through isa's NUT server, and whether every NUT client will shut down.",
    "tags": ["ups", "nut", "power"],
    "timezone": "browser",
    "editable": False,
    "graphTooltip": 1,
    "refresh": "1m",
    "schemaVersion": 39,
    "time": {"from": "now-24h", "to": "now"},
    "links": [
        {"title": "Respond to a UPS alert", "type": "link", "targetBlank": True, "icon": "doc",
         "url": "https://backstage.k8s.specht-labs.de/docs/default/system/elbschloss/how-to/respond-to-a-ups-alert/"},
        {"title": "UPS and NUT reference", "type": "link", "targetBlank": True, "icon": "doc",
         "url": "https://backstage.k8s.specht-labs.de/docs/default/system/elbschloss/reference/ups-and-nut/"},
    ],
    "templating": {"list": [
        {"name": "datasource", "label": "Metrics", "type": "datasource", "query": "prometheus",
         "current": {"selected": True, "text": "Mimir (homelab)", "value": "mimir-homelab"}, "hide": 0},
        {"name": "logs", "label": "Logs", "type": "datasource", "query": "loki",
         "current": {"selected": True, "text": "Loki (homelab)", "value": "loki-homelab"}, "hide": 0},
    ]},
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True,
         "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
        ann("On battery", 'max(ups_status{' + U + ', flag="OB"}) == 1', "orange"),
        ann("Forced shutdown", 'max(ups_status{' + U + ', flag="FSD"}) == 1', "red"),
    ]},
    "panels": panels,
}

print(json.dumps(dashboard, indent=2))
