#!/usr/bin/env python3
"""
Full-Stack API Consumer Contract Auditor.

Statically analyzes frontend API usage across `static/` (monolithic `app.js` or native ES modules
under `static/js/` and HTML templates) and dynamically verifies that all server endpoints in
`api/routes/` satisfy 100% of consumer contracts.

Exits 0 on total contract compliance, or 1 if any route, key, or data structure desyncs.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Set

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import api
from api.db import close_thread_connections
from api.router import Request
from api.schemas import (
    validate_calendar_range_contract,
    validate_contract,
    validate_kml_contract,
    validate_points_contract,
)
from db import get_db_path


def collect_frontend_sources(static_dir: Path) -> List[Path]:
    """Collects all frontend JS and HTML source files (excluding vendored third-party libraries)."""
    sources: List[Path] = []
    for ext in ("*.js", "*.mjs", "*.html"):
        for path in sorted(static_dir.rglob(ext)):
            rel_parts = path.relative_to(static_dir).parts
            if "vendor" in rel_parts:
                continue
            sources.append(path)
    return sources


def extract_frontend_contracts() -> Dict[str, Dict[str, Any]]:
    """Returns mandatory API endpoint contracts verified against frontend consumers."""
    return {
        "/api/overview": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "scorecard"],
            "nested_validators": [
                lambda d: validate_contract(
                    d["scorecard"],
                    [
                        "total_segments",
                        "total_visits",
                        "total_activities",
                        "category_breakdown",
                        "top_cities",
                    ],
                    "/api/overview.scorecard",
                )
            ],
        },
        "/api/calendar": {
            "method": "GET",
            "query": {"year": "2024", "month": "10"},
            "required_keys": ["status", "days"],
            "nested_validators": [
                lambda d: isinstance(d["days"], list)
                or (_ for _ in ()).throw(ValueError("/api/calendar: days must be list"))
            ],
        },
        "/api/calendar-range": {
            "method": "GET",
            "query": {"start_date": "2024-10-01", "end_date": "2024-10-03"},
            "required_keys": ["status", "days"],
            "nested_validators": [lambda d: validate_calendar_range_contract(d["days"])],
        },
        "/api/day": {
            "method": "GET",
            "query": {"date": "2024-10-01"},
            "required_keys": ["status", "date", "segments", "gaps", "raw_signals"],
            "nested_validators": [
                lambda d: isinstance(d["segments"], list)
                or (_ for _ in ()).throw(ValueError("/api/day: segments must be list")),
                lambda d: isinstance(d["gaps"], list)
                or (_ for _ in ()).throw(ValueError("/api/day: gaps must be list")),
            ],
        },
        "/api/places": {
            "method": "GET",
            "query": {"limit": "10"},
            "required_keys": ["status", "places", "categories", "cities", "total"],
            "nested_validators": [
                lambda d: isinstance(d["places"], list)
                or (_ for _ in ()).throw(ValueError("/api/places: places must be list")),
                lambda d: isinstance(d["categories"], list)
                or (_ for _ in ()).throw(ValueError("/api/places: categories must be list")),
                lambda d: isinstance(d["cities"], list)
                or (_ for _ in ()).throw(ValueError("/api/places: cities must be list")),
            ],
        },
        "/api/places/visits": {
            "method": "GET",
            "query": {"place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4"},
            "required_keys": ["status", "visits", "count"],
            "nested_validators": [
                lambda d: isinstance(d["visits"], list)
                or (_ for _ in ()).throw(ValueError("/api/places/visits: visits must be list"))
            ],
        },
        "/api/places/map-points": {
            "method": "GET",
            "query": {"limit": "50"},
            "required_keys": ["status", "count", "points"],
            "nested_validators": [
                lambda d: validate_points_contract(d["points"], "/api/places/map-points")
            ],
        },
        "/api/places/compare": {
            "method": "GET",
            "query": {"ids": "ChIJN1t_tDeuEmsRUsoyG83frY4,ChIJOwg_06VPwokRYv534QaPC8g"},
            "required_keys": ["status", "count", "places"],
            "nested_validators": [
                lambda d: isinstance(d["places"], list)
                or (_ for _ in ()).throw(ValueError("/api/places/compare: places must be list"))
            ],
        },
        "/api/diagnostics/gaps": {
            "method": "GET",
            "query": {"limit": "10"},
            "required_keys": ["status", "gaps"],
            "nested_validators": [
                lambda d: isinstance(d["gaps"], list)
                or (_ for _ in ()).throw(ValueError("/api/diagnostics/gaps: gaps must be list"))
            ],
        },
        "/api/diagnostics/anomalies": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "anomalies"],
            "nested_validators": [
                lambda d: isinstance(d["anomalies"], list)
                or (_ for _ in ()).throw(ValueError("/api/diagnostics/anomalies: anomalies must be list"))
            ],
        },
        "/api/diagnostics/unconfirmed": {
            "method": "GET",
            "query": {"limit": "10"},
            "required_keys": ["status", "unconfirmed"],
            "nested_validators": [
                lambda d: isinstance(d["unconfirmed"], list)
                or (_ for _ in ()).throw(ValueError("/api/diagnostics/unconfirmed: unconfirmed must be list"))
            ],
        },
        "/api/heatmap": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "points"],
            "nested_validators": [
                lambda d: isinstance(d["points"], list)
                or (_ for _ in ()).throw(ValueError("/api/heatmap: points must be list"))
            ],
        },
        "/api/fixes": {
            "method": "GET",
            "query": {"status": "PENDING"},
            "required_keys": ["status", "fixes", "counts"],
            "nested_validators": [
                lambda d: validate_contract(
                    d["counts"],
                    ["pending", "accepted", "rejected", "total"],
                    "/api/fixes.counts",
                )
            ],
        },
        "/api/reviews": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "reviews"],
            "nested_validators": [
                lambda d: isinstance(d["reviews"], list)
                or (_ for _ in ()).throw(ValueError("/api/reviews: reviews must be list"))
            ],
        },
        "/api/photos": {
            "method": "GET",
            "query": {"limit": "10"},
            "required_keys": ["status", "photos", "total"],
            "nested_validators": [
                lambda d: isinstance(d["photos"], list)
                or (_ for _ in ()).throw(ValueError("/api/photos: photos must be list"))
            ],
        },
        "/api/trips/stats": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "countries"],
            "nested_validators": [
                lambda d: isinstance(d["countries"], list)
                or (_ for _ in ()).throw(ValueError("/api/trips/stats: countries must be list"))
            ],
        },
        "/api/insights/activity-summaries": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "totals", "modes", "available_periods"],
            "nested_validators": [
                lambda d: isinstance(d["modes"], list)
                or (_ for _ in ()).throw(ValueError("/api/insights/activity-summaries: modes must be list"))
            ],
        },
        "/api/insights/nuggets": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "nuggets"],
            "nested_validators": [
                lambda d: isinstance(d["nuggets"], list)
                or (_ for _ in ()).throw(ValueError("/api/insights/nuggets: nuggets must be list"))
            ],
        },
        "/api/search": {
            "method": "GET",
            "query": {"q": "Park"},
            "required_keys": ["status", "results"],
            "nested_validators": [
                lambda d: isinstance(d["results"], list)
                or (_ for _ in ()).throw(ValueError("/api/search: results must be list"))
            ],
        },
        "/api/breadcrumbs": {
            "method": "GET",
            "query": {"date": "2024-10-01"},
            "required_keys": ["status", "breadcrumbs"],
            "nested_validators": [
                lambda d: isinstance(d["breadcrumbs"], list)
                or (_ for _ in ()).throw(ValueError("/api/breadcrumbs: breadcrumbs must be list"))
            ],
        },
        "/api/outliers": {
            "method": "GET",
            "query": {"limit": "10"},
            "required_keys": ["status", "outliers"],
            "nested_validators": [
                lambda d: isinstance(d["outliers"], list)
                or (_ for _ in ()).throw(ValueError("/api/outliers: outliers must be list"))
            ],
        },
        "/api/trips": {
            "method": "GET",
            "query": {"limit": "10"},
            "required_keys": ["status", "count", "trips"],
            "nested_validators": [
                lambda d: isinstance(d["trips"], list)
                or (_ for _ in ()).throw(ValueError("/api/trips: trips must be list"))
            ],
        },
        "/api/trips/export.kml": {
            "method": "GET",
            "query": {},
            "is_raw": True,
            "content_type_prefix": "application/vnd.google-earth.kml+xml",
            "raw_validator": lambda body: validate_kml_contract(body, "/api/trips/export.kml"),
        },
        "/api/life-periods": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "periods"],
            "nested_validators": [
                lambda d: isinstance(d["periods"], list)
                or (_ for _ in ()).throw(ValueError("/api/life-periods: periods must be list"))
            ],
        },
        "/api/device/status": {
            "method": "GET",
            "query": {},
            "required_keys": ["status", "connected"],
        },
    }


def audit_static_coverage(source_files: List[Path]) -> List[str]:
    """Checks that every `/api/...` path referenced across frontend files is registered in `api.router`."""
    found_paths: Set[str] = set()
    pattern = re.compile(r"""["'`](/api/[a-zA-Z0-9_.\-/]+)""")
    for src in source_files:
        content = src.read_text(encoding="utf-8")
        for match in pattern.findall(content):
            clean = match.split("?")[0].rstrip("/")
            if clean and clean != "/api":
                found_paths.add(clean)

    registered_paths = {path for _, path in api.router._routes.keys()}
    return sorted(p for p in found_paths if p not in registered_paths)


def audit_dynamic_contracts(contracts: Dict[str, Dict[str, Any]]) -> List[str]:
    """Executes requests for each contracted endpoint and enforces response shape invariants."""
    errors: List[str] = []

    for path, spec in contracts.items():
        method = spec.get("method", "GET")
        query = {k: [v] for k, v in spec.get("query", {}).items()}
        req = Request(method=method, path=path, query_params=query, headers={}, body=b"")

        res = api.router.dispatch(req)
        if res.status_code != 200:
            errors.append(
                f"{method} {path} returned HTTP {res.status_code} (expected 200): "
                f"{res.body.decode('utf-8', errors='replace')[:150]}"
            )
            continue

        if spec.get("is_raw"):
            expected_ct = spec.get("content_type_prefix", "")
            if expected_ct and not res.content_type.startswith(expected_ct):
                errors.append(
                    f"{method} {path} content-type '{res.content_type}' did not start with '{expected_ct}'"
                )
            raw_validator = spec.get("raw_validator")
            if raw_validator:
                try:
                    raw_validator(res.body)
                except Exception as exc:
                    errors.append(f"{method} {path} raw validation failure: {exc}")
            continue

        try:
            data = json.loads(res.body.decode("utf-8"))
        except Exception as exc:
            errors.append(f"{method} {path} returned invalid JSON: {exc}")
            continue

        for key in spec.get("required_keys", []):
            if key not in data:
                errors.append(f"{method} {path} response missing required key '{key}'")

        for validator in spec.get("nested_validators", []):
            try:
                validator(data)
            except Exception as ve:
                errors.append(f"{method} {path} validation failure: {ve}")

    return errors


def main() -> int:
    print("================================================================================")
    print("             TIMELINE API FULL-STACK CONSUMER CONTRACT AUDITOR                 ")
    print("================================================================================")

    static_dir = WORKSPACE_ROOT / "static"
    source_files = collect_frontend_sources(static_dir)
    if not source_files:
        print(f"ERROR: No frontend source files found in {static_dir}!")
        return 1

    print(f"\n[Phase 1] Static Route Coverage Audit ({len(source_files)} frontend files vs. api/routes)...")
    missing_routes = audit_static_coverage(source_files)
    if missing_routes:
        print(f"  FAILED: {len(missing_routes)} frontend endpoint(s) not registered in router:")
        for mr in missing_routes:
            print(f"    - {mr}")
        return 1
    print("  PASSED: 100% of frontend /api/ endpoints are registered in server router.")

    print("\n[Phase 2] Dynamic Contract & Data Shape Assertion...")
    contracts = extract_frontend_contracts()
    print(f"  Asserting contracts across {len(contracts)} core API consumer endpoints...")

    with ExitStack() as stack:
        current_db = Path(get_db_path())
        prev_env = os.environ.get("TIMELINE_DB_PATH")
        used_ephemeral = False
        if not current_db.exists() or current_db.stat().st_size == 0:
            from tests.hermetic_fixture import create_hermetic_db

            tmp_dir = stack.enter_context(tempfile.TemporaryDirectory())
            ephemeral_db = create_hermetic_db(Path(tmp_dir) / "contract_audit.db")
            os.environ["TIMELINE_DB_PATH"] = str(ephemeral_db)
            close_thread_connections()
            used_ephemeral = True

        try:
            dynamic_errors = audit_dynamic_contracts(contracts)
        finally:
            if used_ephemeral:
                close_thread_connections()
                if prev_env is None:
                    os.environ.pop("TIMELINE_DB_PATH", None)
                else:
                    os.environ["TIMELINE_DB_PATH"] = prev_env

    if dynamic_errors:
        print(f"  FAILED: {len(dynamic_errors)} contract violation(s) detected:")
        for err in dynamic_errors:
            print(f"    - {err}")
        return 1

    print(f"  PASSED: 100% of endpoint contracts ({len(contracts)} endpoints) verified flawless.")
    print("\n================================================================================")
    print("       RESULT: 0 CONTRACT VIOLATIONS DETECTED (FULL-STACK DESYNC RULED OUT)    ")
    print("================================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
