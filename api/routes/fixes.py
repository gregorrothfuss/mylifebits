"""
Timeline Quality Fix Proposals API (Listing, Filtering, Evidence Facets, Applying, Rejecting, Batching).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from api.db import get_db, query_all, query_one
from api.response import Response, error_response, json_response
from api.router import Request, router
from enrichment.engine import TimelineEnrichmentEngine


@router.get("/api/fixes")
def get_fixes(req: Request) -> Response:
    """Returns fix proposals filtered by status, source, action, confidence, and search query with full facet counts."""
    status_filter = req.get_str("status", "PENDING").upper()
    source_filter = req.get_str("source", "ALL").strip()
    action_filter = req.get_str("action", "ALL").strip()
    search_q = req.get_str("q", "").strip().lower()
    min_conf = req.get_float("min_confidence", 0.0)
    limit = min(max(req.get_int("limit", 500), 1), 2000)

    where_clauses: List[str] = []
    params: List[Any] = []

    if status_filter != "ALL":
        where_clauses.append("status = ?")
        params.append(status_filter)

    if source_filter and source_filter.upper() != "ALL":
        where_clauses.append("source = ?")
        params.append(source_filter)

    if action_filter and action_filter.upper() != "ALL":
        where_clauses.append("proposed_action = ?")
        params.append(action_filter)

    if min_conf > 0.0:
        where_clauses.append("confidence >= ?")
        params.append(min_conf)

    if search_q:
        where_clauses.append(
            "(LOWER(COALESCE(reasoning, '')) LIKE ? OR LOWER(COALESCE(date, '')) LIKE ? "
            "OR LOWER(COALESCE(patch_data_json, '')) LIKE ? OR LOWER(COALESCE(source, '')) LIKE ?)"
        )
        like_pat = f"%{search_q}%"
        params.extend([like_pat, like_pat, like_pat, like_pat])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        SELECT *
        FROM fix_proposals
        {where_sql}
        ORDER BY confidence DESC, date DESC, id DESC
        LIMIT ?;
    """
    params.append(limit)
    fixes = query_all(sql, tuple(params))

    # Hydrate parsed JSON convenience fields while preserving raw JSON strings
    for f in fixes:
        raw_patch = f.get("patch_data_json")
        if isinstance(raw_patch, str) and raw_patch:
            try:
                f["patch_data"] = json.loads(raw_patch)
            except Exception:
                f["patch_data"] = {}
        else:
            f["patch_data"] = raw_patch if isinstance(raw_patch, dict) else {}

        raw_ev = f.get("evidence_json")
        if isinstance(raw_ev, str) and raw_ev:
            try:
                f["evidence"] = json.loads(raw_ev)
            except Exception:
                f["evidence"] = {}
        else:
            f["evidence"] = raw_ev if isinstance(raw_ev, dict) else {}

    counts_rows = query_all("SELECT status, count(*) as cnt FROM fix_proposals GROUP BY status;")
    counts_map = {r["status"]: r["cnt"] for r in counts_rows}

    # Compute source & action facets for the active status tab (or PENDING if ALL)
    facet_status = status_filter if status_filter != "ALL" else "PENDING"
    source_rows = query_all(
        "SELECT COALESCE(source, 'unknown') as src, COUNT(*) as cnt FROM fix_proposals WHERE status = ? GROUP BY src ORDER BY cnt DESC;",
        (facet_status,),
    )
    by_source = {r["src"]: r["cnt"] for r in source_rows}

    action_rows = query_all(
        "SELECT COALESCE(proposed_action, 'UNKNOWN') as act, COUNT(*) as cnt FROM fix_proposals WHERE status = ? GROUP BY act ORDER BY cnt DESC;",
        (facet_status,),
    )
    by_action = {r["act"]: r["cnt"] for r in action_rows}

    counts = {
        "pending": counts_map.get("PENDING", 0),
        "accepted": counts_map.get("ACCEPTED", 0),
        "rejected": counts_map.get("REJECTED", 0),
        "total": sum(counts_map.values()),
        "by_source": by_source,
        "by_action": by_action,
    }

    return json_response({
        "status": "SUCCESS",
        "fixes": fixes,
        "proposals": fixes,
        "counts": counts,
    })


@router.post("/api/fixes/apply")
def apply_fix(req: Request) -> Response:
    """Applies a fix proposal by ID."""
    data = req.json()
    prop_id = data.get("proposal_id")
    if not prop_id:
        return error_response("Missing proposal_id", status_code=400)

    try:
        engine = TimelineEnrichmentEngine()
        success = engine.apply_fix_proposal(int(prop_id))
        return json_response({"status": "SUCCESS" if success else "FAILED"})
    except Exception as e:
        return error_response(f"Error applying fix proposal {prop_id}: {e}", status_code=500)


@router.post("/api/fixes/reject")
def reject_fix(req: Request) -> Response:
    """Rejects a fix proposal by ID."""
    data = req.json()
    prop_id = data.get("proposal_id")
    if not prop_id:
        return error_response("Missing proposal_id", status_code=400)

    try:
        engine = TimelineEnrichmentEngine()
        success = engine.reject_fix_proposal(int(prop_id))
        return json_response({"status": "SUCCESS" if success else "FAILED"})
    except Exception as e:
        return error_response(f"Error rejecting fix proposal {prop_id}: {e}", status_code=500)


@router.post("/api/fixes/batch-apply")
def batch_apply_fixes(req: Request) -> Response:
    """Applies a batch of fix proposals by IDs, source, action, or minimum confidence."""
    data = req.json()
    action_filter = data.get("action")
    source_filter = data.get("source")
    poi_filter = data.get("poi_name")
    min_conf = float(data.get("min_confidence") or 0.0)
    prop_ids: List[Any] = data.get("proposal_ids", [])

    if not prop_ids:
        if source_filter and source_filter != "ALL":
            rows = query_all(
                "SELECT id FROM fix_proposals WHERE source = ? AND confidence >= ? AND status = 'PENDING' ORDER BY date ASC, id ASC LIMIT 250;",
                (source_filter, min_conf),
            )
            prop_ids = [r["id"] for r in rows]
        elif action_filter and action_filter != "ALL":
            if action_filter == "INSERT_AIRPORT":
                rows = query_all(
                    "SELECT id FROM fix_proposals WHERE proposed_action IN ('INSERT_ORIGIN_AIRPORT', 'INSERT_DESTINATION_AIRPORT') AND confidence >= ? AND status = 'PENDING';",
                    (min_conf,),
                )
            else:
                rows = query_all(
                    "SELECT id FROM fix_proposals WHERE proposed_action = ? AND confidence >= ? AND status = 'PENDING';",
                    (action_filter, min_conf),
                )
            prop_ids = [r["id"] for r in rows]
        elif poi_filter:
            rows = query_all("SELECT id, patch_data_json FROM fix_proposals WHERE status = 'PENDING';")
            for r in rows:
                pdata = json.loads(r["patch_data_json"]) if r.get("patch_data_json") else {}
                pname = pdata.get("resolved_poi_name") or pdata.get("resolved_name") or pdata.get("poi_name")
                if pname == poi_filter:
                    prop_ids.append(r["id"])
        elif min_conf > 0.0:
            rows = query_all(
                "SELECT id FROM fix_proposals WHERE confidence >= ? AND status = 'PENDING' ORDER BY confidence DESC, date ASC LIMIT 250;",
                (min_conf,),
            )
            prop_ids = [r["id"] for r in rows]

    engine = TimelineEnrichmentEngine()
    applied_count = 0
    for pid in prop_ids:
        try:
            if engine.apply_fix_proposal(int(pid)):
                applied_count += 1
        except Exception:
            pass

    return json_response({
        "status": "SUCCESS",
        "applied_count": applied_count,
        "total_targeted": len(prop_ids),
    })


@router.post("/api/fixes/purge")
def purge_fixes(req: Request) -> Response:
    """Purges resolved, accepted, or rejected proposals from the database."""
    data = req.json()
    purge_type = data.get("type", "RESOLVED").upper()

    with get_db() as conn:
        c = conn.cursor()
        if purge_type == "REJECTED":
            c.execute("DELETE FROM fix_proposals WHERE status = 'REJECTED';")
        elif purge_type == "ACCEPTED":
            c.execute("DELETE FROM fix_proposals WHERE status = 'ACCEPTED';")
        else:
            c.execute("DELETE FROM fix_proposals WHERE status IN ('ACCEPTED', 'REJECTED');")
        deleted = c.rowcount

    return json_response({"status": "SUCCESS", "deleted_count": deleted})


def _handle_edit_and_apply(req: Request) -> Response:
    """Edits and applies a fix proposal, supporting custom POI name, category, and time window overrides."""
    data = req.json()
    prop_id = data.get("proposal_id")
    custom_place = (data.get("place_name") or "").strip()
    custom_cat = (data.get("category") or "Other / POI").strip()

    if not prop_id:
        return error_response("Missing proposal_id", status_code=400)

    fp = query_one("SELECT * FROM fix_proposals WHERE id = ?;", (prop_id,))
    if not fp:
        return error_response("Proposal not found", status_code=404)

    # Update patch_data_json with customized place_name / category before applying
    try:
        pdata = json.loads(fp["patch_data_json"]) if fp.get("patch_data_json") else {}
    except Exception:
        pdata = {}

    if custom_place:
        pdata["resolved_poi_name"] = custom_place
        pdata["target_place"] = custom_place
    if custom_cat:
        pdata["category"] = custom_cat

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE fix_proposals SET patch_data_json = ? WHERE id = ?;",
            (json.dumps(pdata), int(prop_id)),
        )

    if fp["target_type"] == "segment" and fp["proposed_action"] == "RESOLVE_UNCONFIRMED_VISIT":
        seg_id = fp["target_id"]
        target_name = custom_place or pdata.get("target_place") or "Verified POI"
        target_cat = custom_cat or pdata.get("category") or "Other / POI"

        with get_db() as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE segments
                SET place_name = ?, place_address = COALESCE(place_address, ?), category = ?, is_unconfirmed = 0
                WHERE id = ?;
                """,
                (target_name, target_name, target_cat, seg_id),
            )
            seg = query_one("SELECT place_id FROM segments WHERE id = ?;", (seg_id,))
            if seg and seg["place_id"]:
                c.execute(
                    "UPDATE places SET name = ?, category = ? WHERE place_id = ?;",
                    (target_name, target_cat, seg["place_id"]),
                )
            c.execute(
                "UPDATE fix_proposals SET status = 'ACCEPTED', applied_at = datetime('now') WHERE id = ?;",
                (prop_id,),
            )

        return json_response({"status": "SUCCESS", "segment_id": seg_id})

    engine = TimelineEnrichmentEngine()
    success = engine.apply_fix_proposal(int(prop_id))
    return json_response({"status": "SUCCESS" if success else "FAILED"})


# Register both routes to maintain full backward compatibility
router.route("POST", "/api/fixes/edit-and-apply")(_handle_edit_and_apply)
router.route("POST", "/api/proposals/edit-and-apply")(_handle_edit_and_apply)
