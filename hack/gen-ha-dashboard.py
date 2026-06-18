#!/usr/bin/env python3
"""Generate the Home Assistant diagnostics dashboard model JSON.
Run: python3 hack/gen-ha-dashboard.py > /tmp/ha-model.json
Datasources are template variables ($prom / $loki) filtered to the hass tenants
so one dashboard serves both hass and hass-schiltach."""
import json

# Single "Site" variable switches metrics + logs together (one datasource per
# tenant). Datasource UIDs are interpolated from $site — this renders in the
# image renderer, unlike datasource-type template variables.
PROM = "mimir-${site}"
LOKI = "loki-${site}"
pds = {"type": "prometheus", "uid": PROM}
lds = {"type": "loki", "uid": LOKI}
panels = []
_id = [0]
def nid():
    _id[0] += 1
    return _id[0]

def gp(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}

def row(title, y, collapsed=False, sub=None):
    return {"id": nid(), "type": "row", "title": title, "collapsed": collapsed,
            "gridPos": gp(0, y, 24, 1), "panels": sub or []}

def target(expr, ds=pds, legend="", instant=False, fmt="time_series", ref="A"):
    t = {"datasource": ds, "expr": expr, "refId": ref, "legendFormat": legend}
    if instant:
        t["instant"] = True
    if fmt:
        t["format"] = fmt
    return t

def stat(title, x, y, w, h, expr, unit="none", desc="", thresholds=None, mappings=None,
         colormode="value", reducer="lastNotNull", text_mode="auto"):
    fc = {"unit": unit, "thresholds": {"mode": "absolute",
          "steps": thresholds or [{"color": "green", "value": None}]}}
    if mappings:
        fc["mappings"] = mappings
    return {"id": nid(), "type": "stat", "title": title, "description": desc,
            "datasource": pds, "gridPos": gp(x, y, w, h),
            "fieldConfig": {"defaults": fc, "overrides": []},
            "options": {"reduceOptions": {"calcs": [reducer], "fields": "", "values": False},
                        "colorMode": colormode, "graphMode": "area", "textMode": text_mode,
                        "justifyMode": "auto"},
            "targets": [target(expr, instant=True)]}

def ts(title, x, y, w, h, targets, unit="none", desc="", stack=False, fill=10, legend_table=False,
       thresholds=None, ds=pds, ymin=None, colors=None):
    custom = {"drawStyle": "line", "lineWidth": 1, "fillOpacity": fill,
              "showPoints": "never", "spanNulls": True}
    if stack:
        custom["stacking"] = {"mode": "normal", "group": "A"}
    opts = {"tooltip": {"mode": "multi", "sort": "desc"},
            "legend": {"displayMode": "table" if legend_table else "list",
                       "placement": "bottom" if not legend_table else "right",
                       "calcs": ["lastNotNull", "max"] if legend_table else []}}
    fc = {"unit": unit, "custom": custom}
    if ymin is not None:
        fc["min"] = ymin
    if thresholds:
        fc["thresholds"] = {"mode": "absolute", "steps": thresholds}
        fc["custom"]["thresholdsStyle"] = {"mode": "dashed"}
    overrides = []
    for name, col in (colors or {}).items():
        overrides.append({"matcher": {"id": "byName", "options": name},
                          "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": col}}]})
    return {"id": nid(), "type": "timeseries", "title": title, "description": desc,
            "datasource": ds, "gridPos": gp(x, y, w, h),
            "fieldConfig": {"defaults": fc, "overrides": overrides},
            "options": opts, "targets": targets}

def table(title, x, y, w, h, expr, desc="", excl=None, rename=None, unit_overrides=None, sortby=None, ds=pds, order=None):
    # hostname/instance/component/job are noise in a single-host tenant — always hide.
    base_excl = {"Time": True, "__name__": True, "job": True, "instance": True,
                 "component": True, "hostname": True}
    merged_excl = {**base_excl, **(excl or {})}
    organize = {"excludeByName": merged_excl, "renameByName": rename or {}}
    if order:
        organize["indexByName"] = {name: i for i, name in enumerate(order)}
    transformations = [
        {"id": "labelsToFields", "options": {"mode": "columns"}},
        {"id": "merge", "options": {}},
        {"id": "organize", "options": organize},
    ]
    opts = {"showHeader": True, "footer": {"show": False}}
    if sortby:
        opts["sortBy"] = [{"displayName": sortby, "desc": True}]
    p = {"id": nid(), "type": "table", "title": title, "description": desc,
         "datasource": ds, "gridPos": gp(x, y, w, h),
         "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True}},
                         "overrides": unit_overrides or []},
         "options": opts, "transformations": transformations,
         "targets": [target(expr, ds=ds, instant=True, fmt="table")]}
    return p

def logs(title, x, y, w, h, expr, desc=""):
    return {"id": nid(), "type": "logs", "title": title, "description": desc,
            "datasource": lds, "gridPos": gp(x, y, w, h),
            "options": {"showTime": True, "wrapLogMessage": True, "prettifyLogMessage": False,
                        "enableLogDetails": True, "dedupStrategy": "none",
                        "sortOrder": "Descending"},
            "targets": [target(expr, ds=lds, fmt="logs")]}

def pie(title, x, y, w, h, expr, desc="", legend="{{domain}}"):
    return {"id": nid(), "type": "piechart", "title": title, "description": desc,
            "datasource": pds, "gridPos": gp(x, y, w, h),
            "fieldConfig": {"defaults": {"custom": {"hideFrom": {"tooltip": False, "viz": False,
                            "legend": False}}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "pieType": "donut", "tooltip": {"mode": "multi", "sort": "desc"},
                        "legend": {"showLegend": False, "displayMode": "list", "placement": "right"},
                        "displayLabels": ["value"]},
            "targets": [target(expr, instant=True, legend=legend)]}

# ---------- Row 1: Health & triage ----------
y = 0
panels.append(row("Health & triage", y)); y += 1
panels.append(stat("HA scrape up", 0, y, 3, 4, "max(up)", unit="bool_on_off", colormode="background",
    desc="Is the Home Assistant Prometheus endpoint being scraped? Red = HA exporter down / ingest broken.",
    mappings=[{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"},
                                            "1": {"text": "UP", "color": "green"}}}],
    thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}], text_mode="value"))
panels.append(stat("Total entities", 3, y, 3, 4, "count(hass_entity_available)",
    desc="Total entities exposed by Home Assistant."))
panels.append(stat("Unavailable entities", 6, y, 4, 4, "count(hass_entity_available == 0)",
    desc="Entities currently reporting unavailable. The primary triage signal.", colormode="background",
    thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 1},
                {"color": "orange", "value": 50}, {"color": "red", "value": 200}]))
panels.append(stat("Availability", 10, y, 3, 4, "100 * avg(hass_entity_available)", unit="percent",
    desc="Share of entities currently available.", colormode="background", reducer="lastNotNull",
    thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 80},
                {"color": "yellow", "value": 90}, {"color": "green", "value": 98}]))
panels.append(stat("Stale > 1h", 13, y, 3, 4,
    "count((time() - (hass_last_updated_time_seconds > 1.0e9)) > 3600)",
    desc="Entities with a valid last-update timestamp older than 1h (epoch-0/never-updated entities excluded).",
    thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 1},
                {"color": "orange", "value": 50}]))
panels.append(stat("Log errors (1h)", 16, y, 4, 4,
    'sum(count_over_time({service_name="homeassistant"} | logfmt | level=~"error|err|fatal" [1h]))',
    desc="Error-level log lines in the last hour (logs source).",
    thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 1},
                {"color": "red", "value": 25}]))
panels[-1]["datasource"] = lds
panels[-1]["targets"][0]["datasource"] = lds
panels.append(stat("Automations / 5m", 20, y, 4, 4,
    "sum(increase(hass_automation_triggered_count_total[5m]))",
    desc="Automation triggers in the last 5 minutes (overall activity heartbeat).",
    thresholds=[{"color": "green", "value": None}]))
y += 4

# ---------- Row 2: Entity availability ----------
panels.append(row("Entity availability", y)); y += 1
panels.append(ts("Available vs unavailable entities", 0, y, 12, 8, [
    target("count(hass_entity_available == 1)", legend="available"),
    target("count(hass_entity_available == 0)", legend="unavailable", ref="B")],
    desc="Entity availability over time (stacked = total entities). A jump in 'unavailable' points to an integration/device outage.",
    stack=True, fill=30, ymin=0, colors={"available": "green", "unavailable": "red"}))
panels.append(pie("Unavailable by domain", 12, y, 6, 8,
    "count by (domain) (hass_entity_available == 0)",
    desc="Which entity domains are unavailable. Concentration in one domain ⇒ one integration is down.",
    legend="{{domain}}"))
panels.append(table("Currently unavailable entities", 18, y, 6, 8,
    "hass_entity_available == 0",
    desc="The actionable list: every entity reporting unavailable right now.",
    excl={"Time": True, "__name__": True, "Value": True, "job": True, "instance": True,
          "component": True, "entity": True},
    rename={"friendly_name": "entity", "domain": "domain"},
    order=["friendly_name", "domain"]))
y += 8

# ---------- Row 3: Staleness ----------
panels.append(row("Staleness (entities not updating)", y)); y += 1
panels.append(table("Stalest entities", 0, y, 12, 8,
    "topk(25, time() - (hass_last_updated_time_seconds > 1.0e9))",
    desc="Entities with the oldest valid last-update time. High age = stuck sensor / dead integration (epoch-0 entities excluded).",
    excl={"Time": True, "__name__": True, "job": True, "instance": True, "component": True,
          "entity": True},
    rename={"friendly_name": "entity", "domain": "domain", "Value": "age (s)", "hostname": "host"},
    unit_overrides=[{"matcher": {"id": "byName", "options": "age (s)"},
                     "properties": [{"id": "unit", "value": "s"},
                                    {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                                    {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                        {"color": "green", "value": None}, {"color": "yellow", "value": 1800},
                                        {"color": "red", "value": 3600}]}}]}],
    sortby="age (s)"))
panels.append(ts("Entities updated per minute (freshness)", 12, y, 12, 8, [
    target('count(changes(hass_last_updated_time_seconds[5m]) > bool 0)', legend="entities updating")],
    desc="How many entities pushed a fresh update in the last 5m window. A drop = HA stopped updating state.",
    fill=20))
y += 8

# ---------- Row 4: Environment & devices ----------
panels.append(row("Environment & devices", y)); y += 1
panels.append(ts("Temperatures", 0, y, 12, 8, [
    target("hass_sensor_temperature_celsius", legend="{{friendly_name}}")],
    unit="celsius", desc="All temperature sensors.", fill=0, legend_table=True))
panels.append(table("Low batteries", 12, y, 6, 8,
    "bottomk(20, hass_sensor_battery_percent)",
    desc="Lowest battery levels — replace these. Sorted ascending.",
    excl={"Time": True, "__name__": True, "job": True, "instance": True, "component": True,
          "entity": True, "domain": True},
    rename={"friendly_name": "device", "Value": "battery %", "hostname": "host"},
    unit_overrides=[{"matcher": {"id": "byName", "options": "battery %"},
                     "properties": [{"id": "unit", "value": "percent"},
                                    {"id": "custom.cellOptions", "value": {"type": "gauge"}},
                                    {"id": "max", "value": 100}, {"id": "min", "value": 0},
                                    {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                        {"color": "red", "value": None}, {"color": "orange", "value": 20},
                                        {"color": "green", "value": 50}]}}]}],
    sortby=None))
panels[-1]["options"]["sortBy"] = [{"displayName": "battery %", "desc": False}]
panels.append(ts("Power draw (top 10)", 18, y, 6, 8, [
    target("topk(10, hass_sensor_power_w)", legend="{{friendly_name}}")],
    unit="watt", desc="Highest instantaneous power consumers.", fill=10, legend_table=False))
y += 8

# ---------- Row 5: Automations ----------
panels.append(row("Automations", y, collapsed=True, sub=[]))
arow = panels[-1]["panels"]
def addsub(p):
    arow.append(p)
_save = panels
panels = arow
yy = y + 1
panels.append(ts("Automation trigger rate", 0, yy, 12, 8, [
    target("sum(rate(hass_automation_triggered_count_total[5m]))", legend="triggers/s")],
    unit="ops", desc="Overall automation trigger rate."))
panels.append(table("Most active automations (1h)", 12, yy, 12, 8,
    "topk(20, increase(hass_automation_triggered_count_total[1h]))",
    desc="Automations that fired most in the last hour.",
    excl={"Time": True, "__name__": True, "job": True, "instance": True, "component": True,
          "entity": True, "domain": True},
    rename={"friendly_name": "automation", "Value": "triggers (1h)", "hostname": "host"},
    sortby="triggers (1h)"))
panels = _save

# ---------- Row 6: Logs ----------
panels.append(row("Logs", y + 1)); yo = y + 2
panels.append(ts("Log volume by level", 0, yo, 24, 6, [
    target('sum by (level) (count_over_time({service_name="homeassistant"} | logfmt [$__auto]))',
           ds=lds, legend="{{level}}")],
    unit="logs", desc="Log line rate by level. Spikes in warn/error precede or explain incidents.",
    stack=True, fill=40, ds=lds))
panels.append(logs("Home Assistant logs", 0, yo + 6, 24, 12,
    '{service_name="homeassistant"} | logfmt | level=~"$level"',
    desc="Live logs from the logs source. Use the Level variable to filter."))

dashboard = {
    "uid": "homeassistant-diagnostics",
    "title": "Home Assistant — Diagnostics",
    "tags": ["home-assistant", "infrastructure", "homelab"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "1m",
    "time": {"from": "now-6h", "to": "now"},
    "editable": True,
    "graphTooltip": 1,
    "templating": {"list": [
        {"name": "site", "label": "Site", "type": "custom",
         "query": "hass,hass-schiltach", "includeAll": False, "multi": False,
         "current": {"text": "hass", "value": "hass", "selected": True},
         "options": [{"text": "hass", "value": "hass", "selected": True},
                     {"text": "hass-schiltach", "value": "hass-schiltach", "selected": False}],
         "hide": 0},
        {"name": "level", "label": "Log level", "type": "custom",
         "query": "error,err,fatal,warn,warning,info,debug", "includeAll": True, "allValue": ".+",
         "multi": True, "current": {"text": "All", "value": "$__all"}, "hide": 0},
    ]},
    "panels": panels,
}
print(json.dumps(dashboard, indent=2))
