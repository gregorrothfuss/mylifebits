"""
Timeline Quality Fix Proposals API (Listing, Applying, Rejecting, Purging).
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
    """Returns fix proposals filtered by status with full counts facet."""
    status_filter = req.get_str("status", "PENDING").upper()
    if status_filter == "ALL":
        fixes = query_all("SELECT * FROM fix_proposals ORDER BY date DESC, confidence DESC, id DESC LIMIT 500;")
    else:
        fixes = query_all("SELECT * FROM fix_proposals WHERE status = ? ORDER BY date DESC, confidence DESC, id DESC LIMIT 500;", (status_filter,))

    counts_rows = query_all("SELECT status, count(*) as cnt FROM fix_proposals GROUP BY status;")
    counts_map = {r["status"]: r["cnt"] for r in counts_rows}
    counts = {
        "pending": counts_map.get("PENDING", 0),
        "accepted": counts_map.get("ACCEPTED", 0),
        "rejected": counts_map.get("REJECTED", 0),
        "total": sum(counts_map.values()),
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
    """Applies a batch of fix proposals."""
    data = req.json()
    action_filter = data.get("action")
    poi_filter = data.get("poi_name")
    prop_ids: List[Any] = data.get("proposal_ids", [])

    if not prop_ids:
        if action_filter:
            if action_filter == "INSERT_AIRPORT":
                rows = query_all("SELECT id FROM fix_proposals WHERE proposed_action IN ('INSERT_ORIGIN_AIRPORT', 'INSERT_DESTINATION_AIRPORT') AND status = 'PENDING';")
            else:
                rows = query_all("SELECT id FROM fix_proposals WHERE proposed_action = ? AND status = 'PENDING';", (action_filter,))
            prop_ids = [r["id"] for r in rows]
        elif poi_filter:
            rows = query_all("SELECT id, patch_data_json FROM fix_proposals WHERE status = 'PENDING';")
            for r in rows:
                pdata = json.loads(r["patch_data_json"]) if r.get("patch_data_json") else {}
                pname = pdata.get("resolved_poi_name") or pdata.get("resolved_name") or pdata.get("poi_name")
                if pname == poi_filter:
                    prop_ids.append(r["id"])

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
        "total_targeted": len(prop_ids)
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
    """Edits and applies a fix proposal, resolving unconfirmed visits or custom POI assignments."""
    data = req.json()
    prop_id = data.get("proposal_id")
    custom_place = data.get("place_name")
    custom_cat = data.get("category", "Other / POI")

    if not prop_id:
        return error_response("Missing proposal_id", status_code=400)

    fp = query_one("SELECT * FROM fix_proposals WHERE id = ?;", (prop_id,))
    if not fp:
        return error_response("Proposal not found", status_code=404)

    if fp["target_type"] == "segment":
        seg_id = fp["target_id"]
        target_name = custom_place or "Verified POI"
        target_cat = custom_cat or "Other / POI"

        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE segments
                SET place_name = ?, place_address = ?, category = ?, is_unconfirmed = 0
                WHERE id = ?;
            """, (target_name, target_name, target_cat, seg_id))

            seg = query_one("SELECT place_id FROM segments WHERE id = ?;", (seg_id,))
            if seg and seg["place_id"]:
                c.execute("UPDATE places SET name = ?, address = ?, category = ? WHERE place_id = ?;", (target_name, target_name, target_cat, seg["place_id"]))

            c.execute("UPDATE fix_proposals SET status = 'ACCEPTED', applied_at = datetime('now') WHERE id = ?;", (prop_id,))

        return json_response({"status": "SUCCESS", "segment_id": seg_id})

    # Standard apply fallback
    engine = TimelineEnrichmentEngine()
    success = engine.apply_fix_proposal(int(prop_id))
    return json_response({"status": "SUCCESS" if success else "FAILED"})


# Register both routes to fix frontend desync bug
router.route("POST", "/api/fixes/edit-and-apply")(_handle_edit_and_apply)
router.route("POST", "/api/proposals/edit-and-apply")(_handle_edit_and_apply)
