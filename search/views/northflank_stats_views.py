"""
Northflank operational statistics API.

Collects service/addon metadata via the Northflank REST API
(https://api.northflank.com/v1/) and returns a chart-friendly JSON
payload for dashboards.

Requires env var:
    NORTHFLANK_API_TOKEN  – a Northflank Bearer token (starts with "nf-ey…")

Optional env vars:
    NORTHFLANK_PROJECT_ID         – default project (default: rbt-project)
    NORTHFLANK_STATS_CACHE_TTL    – cache seconds (default: 300)
    NORTHFLANK_STATS_HISTORY_HOURS – history window (default: 24)
    NORTHFLANK_STATS_TOKEN        – optional viewer auth token
"""

import json
import logging
import os
import ssl
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timedelta

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

NF_API_BASE = "https://api.northflank.com/v1"
DEFAULT_PROJECT_ID = os.getenv("NORTHFLANK_PROJECT_ID", "rbt-project")
DEFAULT_CACHE_TTL_SECONDS = int(os.getenv("NORTHFLANK_STATS_CACHE_TTL", "300"))
DEFAULT_HISTORY_RETENTION_HOURS = int(os.getenv("NORTHFLANK_STATS_HISTORY_HOURS", "24"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_response(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, X-Stats-Token"
    return response


def _get_nf_token():
    """Return the Northflank API token from env or local CLI config fallback."""
    token = os.getenv("NORTHFLANK_API_TOKEN", "").strip()
    if token:
        return token

    # Fallback: read from local CLI config (works in dev, not in Docker)
    config_path = os.path.expanduser("~/.northflank/config.json")
    try:
        with open(config_path, "r") as f:
            raw = f.read()
        # The config file is JSON with contexts array
        config = json.loads(raw)
        current_name = config.get("current", "")
        for ctx in config.get("contexts", []):
            if ctx.get("name") == current_name:
                return ctx.get("token", "")
        # If no match, return first available token
        contexts = config.get("contexts", [])
        if contexts:
            return contexts[0].get("token", "")
    except Exception:
        pass

    return ""


def _nf_api_get(path, token):
    """
    GET a Northflank REST API endpoint.

    Returns {"ok": True, "data": <parsed JSON>} on success,
    or {"ok": False, "error": "…"} on failure.
    """
    url = f"{NF_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            return {"ok": True, "data": data}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.warning("Northflank API %s → HTTP %s: %s", path, exc.code, body)
        return {"ok": False, "error": f"HTTP {exc.code}: {body}"}
    except Exception as exc:
        logger.warning("Northflank API %s → %s", path, exc)
        return {"ok": False, "error": str(exc)}


def _normalize_status(value):
    status_text = str(value or "").lower()
    if "running" in status_text or "completed" in status_text or "success" in status_text:
        return "running"
    if "paused" in status_text or "stopped" in status_text or "suspend" in status_text:
        return "paused"
    if "deploy" in status_text or "build" in status_text:
        return "deploying"
    return "unknown"


def _safe_float(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("mb", "").replace("gb", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _get_nested(data, *keys, default=None):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


# ---------------------------------------------------------------------------
# Parsers — turn raw Northflank REST API responses into chart-ready dicts
# ---------------------------------------------------------------------------

def _parse_services(api_response):
    """
    Parse GET /v1/projects/{id}/services response.

    The REST API returns: {"data": {"services": [...]}}
    """
    raw = api_response if isinstance(api_response, dict) else {}
    services = _get_nested(raw, "data", "services", default=[])
    if not isinstance(services, list):
        services = []

    status_counts = {"running": 0, "paused": 0, "deploying": 0, "unknown": 0}
    type_counts = {}
    region_counts = {}

    total_instances = 0.0
    total_cpu = 0.0
    total_memory = 0.0

    normalized = []

    for item in services:
        if not isinstance(item, dict):
            continue

        service_id = item.get("id") or item.get("appId") or item.get("name")
        service_type = item.get("serviceType") or item.get("type") or "unknown"

        # Deployment status – may be nested under deployment.status
        deployment = item.get("deployment") or {}
        if not isinstance(deployment, dict):
            deployment = {}

        status_raw = deployment.get("status") or item.get("status")
        if isinstance(status_raw, dict):
            status_raw = json.dumps(status_raw)
        normalized_status = _normalize_status(status_raw)

        # disabled flag overrides
        if item.get("disabledCI") and item.get("disabledCD"):
            normalized_status = "paused"
        elif item.get("disabled"):
            normalized_status = "paused"

        # Region / datacenter
        region = (
            _get_nested(deployment, "region")
            or _get_nested(deployment, "datacenter")
            or item.get("region")
            or "unknown"
        )

        # Compute specs – several possible nesting paths
        instances = (
            _get_nested(deployment, "instances")
            or _get_nested(deployment, "internal", "nfCompute", "replicas")
            or item.get("instances")
            or 0
        )
        cpu = (
            _get_nested(deployment, "internal", "nfCompute", "cpu")
            or _get_nested(deployment, "resources", "cpu")
            or item.get("cpu")
            or 0
        )
        memory = (
            _get_nested(deployment, "internal", "nfCompute", "memory")
            or _get_nested(deployment, "resources", "memory")
            or item.get("memory")
            or 0
        )

        instances_val = _safe_float(instances)
        cpu_val = _safe_float(cpu)
        memory_val = _safe_float(memory)

        total_instances += instances_val
        total_cpu += cpu_val
        total_memory += memory_val

        status_counts[normalized_status] = status_counts.get(normalized_status, 0) + 1
        type_counts[service_type] = type_counts.get(service_type, 0) + 1
        region_counts[region] = region_counts.get(region, 0) + 1

        # Extra fields from detail endpoint
        billing = item.get("billing") or {}
        storage = _get_nested(deployment, "storage", default={})
        ephemeral_storage = _safe_float(_get_nested(storage, "ephemeralStorage", "storageSize"))

        normalized.append({
            "id": service_id,
            "name": item.get("name") or service_id,
            "description": item.get("description") or "",
            "type": service_type,
            "status": normalized_status,
            "region": region,
            "plan": billing.get("deploymentPlan") or "unknown",
            "capacity": {
                "instances": instances_val,
                "cpu": cpu_val,
                "memory": memory_val,
                "ephemeral_storage_mb": ephemeral_storage,
            },
        })

    return {
        "items": normalized,
        "counts": {
            "total": len(normalized),
            "status": status_counts,
            "types": type_counts,
            "regions": region_counts,
        },
        "capacity": {
            "instances": round(total_instances, 2),
            "cpu": round(total_cpu, 2),
            "memory": round(total_memory, 2),
        },
    }


def _parse_addons(api_response):
    """
    Parse GET /v1/projects/{id}/addons response.

    The REST API returns: {"data": {"addons": [...]}}
    """
    raw = api_response if isinstance(api_response, dict) else {}
    addons = _get_nested(raw, "data", "addons", default=[])
    if not isinstance(addons, list):
        addons = []

    status_counts = {"running": 0, "paused": 0, "unknown": 0}
    spec_counts = {}
    normalized = []

    for item in addons:
        if not isinstance(item, dict):
            continue

        addon_id = item.get("id") or item.get("addonId") or item.get("name")
        addon_name = item.get("name") or addon_id
        addon_type = item.get("type") or _get_nested(item, "spec", "type") or "unknown"

        status = _normalize_status(item.get("status"))
        if status == "deploying":
            status = "running"

        status_counts[status] = status_counts.get(status, 0) + 1
        spec_counts[addon_type] = spec_counts.get(addon_type, 0) + 1

        normalized.append({
            "id": addon_id,
            "name": addon_name,
            "type": addon_type,
            "status": status,
        })

    return {
        "items": normalized,
        "counts": {
            "total": len(normalized),
            "status": status_counts,
            "types": spec_counts,
        },
    }


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _append_history_point(project_id, snapshot, retention_hours):
    history_key = f"northflank_stats_history_{project_id}"
    existing = cache.get(history_key, [])

    if not isinstance(existing, list):
        existing = []

    existing.append(snapshot)

    cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
    filtered = []
    for point in existing:
        timestamp = point.get("timestamp")
        if not timestamp:
            continue
        try:
            point_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            point_dt = point_dt.replace(tzinfo=None)
        except Exception:
            continue
        if point_dt >= cutoff:
            filtered.append(point)

    filtered = filtered[-2000:]
    cache.set(history_key, filtered, timeout=retention_hours * 3600)
    return filtered


def _extract_lookback_history(history, lookback_hours):
    if not history:
        return []
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
    result = []
    for point in history:
        timestamp = point.get("timestamp")
        if not timestamp:
            continue
        try:
            point_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            point_dt = point_dt.replace(tzinfo=None)
        except Exception:
            continue
        if point_dt >= cutoff:
            result.append(point)
    return result


# ---------------------------------------------------------------------------
# Main API view
# ---------------------------------------------------------------------------

@require_GET
def northflank_stats_api(request):
    """
    Return Northflank operational stats as chart-ready JSON.

    Query params:
    - project_id: Northflank project ID (default from env or rbt-project)
    - refresh: 1 to bypass cache
    - lookback_hours: history points to return (default 24, max 168)

    Optional security:
    - If NORTHFLANK_STATS_TOKEN is set in env, request must include
      ``X-Stats-Token: <token>``.
    """
    try:
        # Optional viewer auth
        expected_token = os.getenv("NORTHFLANK_STATS_TOKEN", "").strip()
        if expected_token:
            provided = request.headers.get("X-Stats-Token", "").strip()
            if provided != expected_token:
                return _json_response({"error": "Unauthorized"}, status=401)

        project_id = (
            request.GET.get("project_id", DEFAULT_PROJECT_ID).strip()
            or DEFAULT_PROJECT_ID
        )
        refresh = request.GET.get("refresh") in {"1", "true", "yes"}

        try:
            lookback_hours = int(request.GET.get("lookback_hours", "24"))
        except (TypeError, ValueError):
            lookback_hours = 24
        lookback_hours = max(1, min(lookback_hours, 168))

        cache_key = f"northflank_stats_snapshot_{project_id}"

        if not refresh:
            cached = cache.get(cache_key)
            if cached:
                return _json_response(cached)

        # ---- Northflank REST API calls ----
        nf_token = _get_nf_token()
        if not nf_token:
            return _json_response(
                {"error": "NORTHFLANK_API_TOKEN not configured. "
                          "Set the env var to a Northflank Bearer token."},
                status=500,
            )

        warnings = []

        services_result = _nf_api_get(
            f"/projects/{project_id}/services", nf_token
        )
        addons_result = _nf_api_get(
            f"/projects/{project_id}/addons", nf_token
        )

        if not services_result["ok"]:
            warnings.append(f"Services unavailable: {services_result.get('error')}")
        if not addons_result["ok"]:
            warnings.append(f"Addons unavailable: {addons_result.get('error')}")

        # Enrich each service with detail endpoint data (has deployment, billing, etc.)
        if services_result["ok"]:
            raw_services = _get_nested(services_result.get("data", {}), "data", "services", default=[])
            enriched = []
            for svc in (raw_services if isinstance(raw_services, list) else []):
                svc_id = svc.get("id")
                if svc_id:
                    detail = _nf_api_get(
                        f"/projects/{project_id}/services/{svc_id}", nf_token
                    )
                    if detail["ok"]:
                        enriched.append(detail["data"].get("data", svc))
                    else:
                        enriched.append(svc)
                else:
                    enriched.append(svc)
            # Re-wrap in the expected structure
            services_result["data"] = {"data": {"services": enriched}}

        parsed_services = _parse_services(
            services_result.get("data", {}) if services_result["ok"] else {}
        )
        parsed_addons = _parse_addons(
            addons_result.get("data", {}) if addons_result["ok"] else {}
        )

        running_services = parsed_services["counts"]["status"].get("running", 0)
        paused_services = parsed_services["counts"]["status"].get("paused", 0)
        running_addons = parsed_addons["counts"]["status"].get("running", 0)
        paused_addons = parsed_addons["counts"]["status"].get("paused", 0)

        timestamp = datetime.utcnow().isoformat() + "Z"
        history_point = {
            "timestamp": timestamp,
            "running_services": running_services,
            "paused_services": paused_services,
            "running_addons": running_addons,
            "paused_addons": paused_addons,
        }

        history = _append_history_point(
            project_id=project_id,
            snapshot=history_point,
            retention_hours=DEFAULT_HISTORY_RETENTION_HOURS,
        )
        history_for_window = _extract_lookback_history(history, lookback_hours)

        response_data = {
            "meta": {
                "generated_at": timestamp,
                "project_id": project_id,
                "source": "northflank-rest-api",
                "cache_ttl_seconds": DEFAULT_CACHE_TTL_SECONDS,
                "lookback_hours": lookback_hours,
            },
            "summary": {
                "services_total": parsed_services["counts"]["total"],
                "addons_total": parsed_addons["counts"]["total"],
                "running_services": running_services,
                "paused_services": paused_services,
                "running_addons": running_addons,
                "paused_addons": paused_addons,
                "uptime_ratio": round(
                    (running_services + running_addons)
                    / max(
                        parsed_services["counts"]["total"]
                        + parsed_addons["counts"]["total"],
                        1,
                    ),
                    4,
                ),
            },
            "capability": {
                "service_types": parsed_services["counts"]["types"],
                "addon_types": parsed_addons["counts"]["types"],
                "reach_regions": parsed_services["counts"]["regions"],
            },
            "compute": {
                "capacity_totals": parsed_services["capacity"],
                "services": parsed_services["items"],
            },
            "chart_data": {
                "service_status_pie": [
                    {"label": k, "value": v}
                    for k, v in parsed_services["counts"]["status"].items()
                ],
                "addon_status_pie": [
                    {"label": k, "value": v}
                    for k, v in parsed_addons["counts"]["status"].items()
                ],
                "service_types_bar": [
                    {"label": k, "value": v}
                    for k, v in parsed_services["counts"]["types"].items()
                ],
                "reach_regions_bar": [
                    {"label": k, "value": v}
                    for k, v in parsed_services["counts"]["regions"].items()
                ],
                "uptime_downtime_timeseries": history_for_window,
            },
            "warnings": warnings,
        }

        cache.set(cache_key, response_data, timeout=DEFAULT_CACHE_TTL_SECONDS)
        return _json_response(response_data)

    except Exception as exc:
        logger.exception("northflank_stats_api error")
        return _json_response(
            {"error": str(exc), "traceback": traceback.format_exc()},
            status=500,
        )
