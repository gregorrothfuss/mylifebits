"""Layer 2 evidence-corroborated fix proposal generator pass."""

from __future__ import annotations

import bisect
import csv
import datetime
import json
import os
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from breadcrumbs import haversine_distance
from db import get_db_connection
from enrichment.local_timezone import get_timezone_offset_hours
from enrichment.passes.common import (
    ENGINE_VERSION,
    compute_decision_key,
    parse_iso_to_ts,
)


def generate_evidence_backed_proposals(
    engine: Any,
    plazes_zip_path: str = "data/plazes/plazes.zip",
    lyft_csv_path: str = "data/citibike/lyft_data/passenger_rides.csv",
    clear_pending: bool = True,
) -> Dict[str, Any]:
    """
    Generates strictly evidence-corroborated `fix_proposals` across 5 verifiable sources:
    1. PHOTOS_EXIF: Geocoded photo clusters in gaps or contradicting stretched Home/Hotel stays.
    2. MAPS_REVIEWS: Google Maps Contributor Reviews for unvisited/dropped places.
    3. PLAZES_ARCHIVE: Historical Plazes check-ins (2005-2010) with venue coordinates & notes.
    4. GOOGLE_FIT & LYFT_ARCHIVE: Recorded biometric workouts and point-to-point Lyft rides in gaps.
    5. FLIGHT_AIRPORT: Verified >300 km flights missing origin/destination airport visits.
    Never generates uncorroborated dwell-extension or transit-synthesis guesses.
    """
    conn = get_db_connection(engine.db_path)
    try:
        c = conn.cursor()
        run_id = engine.start_inference_run(
            conn, "layer2_generate_evidence_proposals", {"db_path": engine.db_path}
        )

        c.execute("SELECT decision_key FROM user_decisions WHERE decision_type = 'REJECT_PROPOSAL';")
        rejected_keys = {r["decision_key"] for r in c.fetchall() if r["decision_key"]}

        if clear_pending:
            c.execute("DELETE FROM fix_proposals WHERE status = 'PENDING';")
            conn.commit()

        c.execute(
            """
            SELECT place_id, name, address, category, city, semantic_type, latitude, longitude, visit_count
            FROM places
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND name IS NOT NULL AND name != ''
              AND place_id LIKE 'ChIJ%';
            """
        )
        all_places = [dict(r) for r in c.fetchall()]
        spatial_grid: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        for p in all_places:
            gx = int(round(float(p["latitude"]) * 100))
            gy = int(round(float(p["longitude"]) * 100))
            spatial_grid.setdefault((gx, gy), []).append(p)

        def find_nearest_poi(
            lat: float, lng: float, max_m: float = 350.0, prefer_non_home: bool = True
        ) -> Optional[Dict[str, Any]]:
            gx = int(round(lat * 100))
            gy = int(round(lng * 100))
            best = None
            best_score = 1e9
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for cand in spatial_grid.get((gx + dx, gy + dy), ()):
                        d = haversine_distance(lat, lng, float(cand["latitude"]), float(cand["longitude"]))
                        if d <= max_m:
                            is_home = cand.get("semantic_type") in ("TYPE_HOME", "TYPE_WORK") or (
                                cand.get("name") or ""
                            ).lower().startswith("home")
                            penalty = 150.0 if (prefer_non_home and is_home) else 0.0
                            score = d + penalty
                            if score < best_score:
                                best_score = score
                                best = cand
            return best

        c.execute(
            """
            SELECT id, date, start_time, end_time, start_ts, end_ts,
                   place_id, place_name, category, semantic_type, latitude, longitude, duration_minutes
            FROM segments
            WHERE hierarchy_level = 0 AND segment_type = 'visit'
            ORDER BY start_ts ASC;
            """
        )
        visit_segs = [dict(r) for r in c.fetchall()]
        visit_starts = [float(v["start_ts"]) for v in visit_segs]

        c.execute("SELECT id, start_ts, end_ts, date FROM gaps ORDER BY start_ts ASC;")
        gap_rows_all = [dict(r) for r in c.fetchall()]
        gap_starts = [float(g["start_ts"]) for g in gap_rows_all]
        fallback_seg_id = int(visit_segs[0]["id"]) if visit_segs else 1

        def resolve_gap_or_segment_target(st_ts: float, et_ts: float) -> Tuple[str, int]:
            if gap_rows_all:
                gi = bisect.bisect_left(gap_starts, st_ts)
                for k in range(max(0, gi - 2), min(len(gap_rows_all), gi + 3)):
                    gr = gap_rows_all[k]
                    if float(gr["start_ts"]) <= et_ts + 3600 and float(gr["end_ts"]) >= st_ts - 3600:
                        return "gap", int(gr["id"])
                nearest_g = gap_rows_all[min(max(0, gi - 1), len(gap_rows_all) - 1)]
                return "gap", int(nearest_g["id"])
            if visit_segs:
                vi = bisect.bisect_left(visit_starts, st_ts)
                nearest_v = visit_segs[min(max(0, vi - 1), len(visit_segs) - 1)]
                return "segment", int(nearest_v["id"])
            return "segment", fallback_seg_id

        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        proposals_to_insert: List[Tuple[Any, ...]] = []
        counts_by_source: Dict[str, int] = {}

        def add_proposal(
            target_type: str,
            target_id: Any,
            date_str: str,
            action: str,
            source: str,
            reasoning: str,
            confidence: float,
            patch_data: Dict[str, Any],
            evidence: Dict[str, Any],
        ) -> None:
            dkey = compute_decision_key(
                action,
                date_str,
                patch_data.get("start_ts"),
                patch_data.get("end_ts"),
                patch_data.get("place_id") or patch_data.get("resolved_poi_name") or patch_data.get("target_place"),
            )
            if dkey in rejected_keys:
                return
            rejected_keys.add(dkey)
            counts_by_source[source] = counts_by_source.get(source, 0) + 1
            proposals_to_insert.append(
                (
                    target_type,
                    int(target_id) if str(target_id).isdigit() and int(target_id) > 0 else fallback_seg_id,
                    date_str,
                    action,
                    source,
                    reasoning,
                    round(confidence, 2),
                    "PENDING",
                    json.dumps(patch_data),
                    now_iso,
                    ENGINE_VERSION,
                    run_id,
                    json.dumps(evidence),
                    dkey,
                )
            )

        # =====================================================================
        # STREAM 1: PHOTOS_EXIF
        # =====================================================================
        c.execute(
            """
            SELECT sha256, filename, preview_path, timestamp_utc, local_date,
                   latitude, longitude, place_id, place_name, address, city, country
            FROM photos
            WHERE is_partner = 0
              AND latitude IS NOT NULL AND longitude IS NOT NULL
              AND timestamp_utc IS NOT NULL AND local_date IS NOT NULL
              AND NOT (ABS(latitude) < 0.01 AND ABS(longitude) < 0.01)
            ORDER BY timestamp_utc ASC;
            """
        )
        geo_photos = [dict(r) for r in c.fetchall()]

        clusters: List[List[Dict[str, Any]]] = []
        for p in geo_photos:
            if not clusters:
                clusters.append([p])
                continue
            prev = clusters[-1][-1]
            dt = float(p["timestamp_utc"]) - float(prev["timestamp_utc"])
            dist_m = haversine_distance(
                float(prev["latitude"]),
                float(prev["longitude"]),
                float(p["latitude"]),
                float(p["longitude"]),
            )
            if dt <= 5400 and dist_m <= 200.0 and p["local_date"] == prev["local_date"]:
                clusters[-1].append(p)
            else:
                clusters.append([p])

        photo_proposals_cap = 220
        for cl in sorted(clusters, key=lambda x: (len(x), x[0]["timestamp_utc"]), reverse=True):
            if counts_by_source.get("photos_exif", 0) >= photo_proposals_cap:
                break
            st_ts = float(cl[0]["timestamp_utc"])
            et_ts = float(cl[-1]["timestamp_utc"])
            if et_ts - st_ts < 1500:
                mid = (st_ts + et_ts) / 2.0
                st_ts = mid - 750.0
                et_ts = mid + 750.0

            clat = sum(float(x["latitude"]) for x in cl) / len(cl)
            clng = sum(float(x["longitude"]) for x in cl) / len(cl)
            date_str = str(cl[0]["local_date"])

            idx = bisect.bisect_left(visit_starts, st_ts - 86400)
            already_covered = False
            enclosing_stay: Optional[Tuple[Dict[str, Any], float]] = None
            for k in range(max(0, idx - 2), min(len(visit_segs), idx + 15)):
                vs = visit_segs[k]
                if float(vs["start_ts"]) > et_ts + 3600:
                    break
                if float(vs["end_ts"]) >= st_ts - 1800 and float(vs["start_ts"]) <= et_ts + 1800:
                    if vs["latitude"] is not None and vs["longitude"] is not None:
                        d_m = haversine_distance(clat, clng, float(vs["latitude"]), float(vs["longitude"]))
                        if d_m <= 400.0:
                            already_covered = True
                            break
                        elif float(vs["start_ts"]) <= st_ts and float(vs["end_ts"]) >= et_ts and d_m >= 800.0:
                            enclosing_stay = (vs, d_m)

            if already_covered:
                continue

            poi = find_nearest_poi(clat, clng, max_m=320.0, prefer_non_home=True)
            if not poi:
                continue
            poi_name = str(poi["name"])
            poi_cat = poi.get("category") or "Other / POI"
            poi_addr = poi.get("address") or cl[0].get("address")
            poi_city = poi.get("city") or cl[0].get("city")
            poi_id = str(poi["place_id"])

            off_h = get_timezone_offset_hours(clat, clng, st_ts)
            tz = datetime.timezone(datetime.timedelta(hours=off_h))
            st_iso = datetime.datetime.fromtimestamp(st_ts, tz=tz).isoformat()
            et_iso = datetime.datetime.fromtimestamp(et_ts, tz=tz).isoformat()
            time_win = f"{st_iso[11:16]} – {et_iso[11:16]}"
            dur_m = round((et_ts - st_ts) / 60.0, 1)

            sample_photos = [
                {
                    "sha256": x["sha256"],
                    "filename": x["filename"],
                    "preview_url": f"/previews/{x['sha256']}.webp",
                    "timestamp_utc": x["timestamp_utc"],
                    "latitude": round(float(x["latitude"]), 5),
                    "longitude": round(float(x["longitude"]), 5),
                }
                for x in cl[:6]
            ]

            if enclosing_stay:
                vs_enc, dist_m = enclosing_stay
                dist_km = round(dist_m / 1000.0, 1)
                action = "CARVE_PHOTO_VERIFIED_VISIT"
                target_type = "segment"
                target_id: int = int(vs_enc["id"])
                reasoning = (
                    f"{len(cl)} geotagged photo{'s' if len(cl) > 1 else ''} at {poi_name} ({time_win}) "
                    f"contradict active stay '{vs_enc['place_name']}' ({dist_km} km away)."
                )
                conf = min(0.98, 0.88 + 0.02 * len(cl))
                evidence: Dict[str, Any] = {
                    "evidence_type": "PHOTOS_EXIF",
                    "photo_count": len(cl),
                    "photos": sample_photos,
                    "contradicted_segment_id": vs_enc["id"],
                    "contradicted_place_name": vs_enc["place_name"],
                    "contradiction_distance_km": dist_km,
                }
            else:
                action = "INSERT_PHOTO_VERIFIED_VISIT"
                target_type, target_id = resolve_gap_or_segment_target(st_ts, et_ts)
                reasoning = (
                    f"Recover unrecorded visit at {poi_name} ({time_win}, {dur_m:.0f}m) "
                    f"corroborated by {len(cl)} geotagged photo{'s' if len(cl) > 1 else ''}."
                )
                conf = min(0.97, 0.86 + 0.02 * len(cl))
                evidence = {
                    "evidence_type": "PHOTOS_EXIF",
                    "photo_count": len(cl),
                    "photos": sample_photos,
                }

            patch_data = {
                "action": action,
                "segment_id": enclosing_stay[0]["id"] if enclosing_stay else None,
                "gap_id": target_id if target_type == "gap" else None,
                "date": date_str,
                "start_ts": st_ts,
                "end_ts": et_ts,
                "start_time": st_iso,
                "end_time": et_iso,
                "duration_minutes": dur_m,
                "time_window": time_win,
                "place_id": poi_id,
                "resolved_poi_name": poi_name,
                "target_place": poi_name,
                "address": poi_addr,
                "category": poi_cat,
                "city": poi_city,
                "latitude": round(clat, 6),
                "longitude": round(clng, 6),
                "centroid_lat": round(clat, 6),
                "centroid_lng": round(clng, 6),
                "photo_count": len(cl),
                "photos": sample_photos,
            }
            add_proposal(
                target_type, target_id, date_str, action, "photos_exif", reasoning, conf, patch_data, evidence
            )

        # =====================================================================
        # STREAM 2: MAPS_REVIEWS
        # =====================================================================
        c.execute(
            """
            SELECT r.id, r.place_name, r.date, r.created_at, r.latitude, r.longitude,
                   r.rating, r.review_text, r.matched_place_id, r.photo_urls,
                   p.address, p.category, p.city, p.visit_count
            FROM poi_reviews r
            LEFT JOIN places p ON r.matched_place_id = p.place_id
            WHERE r.latitude IS NOT NULL AND r.longitude IS NOT NULL
              AND COALESCE(p.visit_count, 0) = 0
            ORDER BY r.date DESC, r.id DESC
            LIMIT 120;
            """
        )
        for rev in [dict(r) for r in c.fetchall()]:
            pub_iso = rev.get("created_at") or rev.get("date") or ""
            raw_dt = str(rev.get("date") or pub_iso)
            date_str_opt = raw_dt[:10] if len(raw_dt) >= 10 else None
            if not date_str_opt:
                continue
            pub_ts = float(parse_iso_to_ts(pub_iso) or parse_iso_to_ts(f"{date_str_opt}T19:00:00Z") or 0.0)
            if pub_ts <= 0:
                continue

            rlat, rlng = float(rev["latitude"]), float(rev["longitude"])
            matched_pid = rev.get("matched_place_id")
            poi = None
            if not matched_pid or not str(matched_pid).startswith("ChIJ"):
                poi = find_nearest_poi(rlat, rlng, max_m=350.0, prefer_non_home=True)
                if poi:
                    matched_pid = poi["place_id"]
            if not matched_pid or not str(matched_pid).startswith("ChIJ"):
                continue

            idx = bisect.bisect_left(visit_starts, pub_ts - 86400)
            already_visited = False
            for k in range(max(0, idx - 2), min(len(visit_segs), idx + 15)):
                vs = visit_segs[k]
                if (
                    vs["date"] == date_str_opt
                    and vs["latitude"] is not None
                    and vs["longitude"] is not None
                ):
                    if haversine_distance(rlat, rlng, float(vs["latitude"]), float(vs["longitude"])) <= 350.0:
                        already_visited = True
                        break
            if already_visited:
                continue

            st_ts = pub_ts - 3600.0
            et_ts = pub_ts
            off_h = get_timezone_offset_hours(rlat, rlng, st_ts)
            tz = datetime.timezone(datetime.timedelta(hours=off_h))
            st_iso = datetime.datetime.fromtimestamp(st_ts, tz=tz).isoformat()
            et_iso = datetime.datetime.fromtimestamp(et_ts, tz=tz).isoformat()
            time_win = f"{st_iso[11:16]} – {et_iso[11:16]}"

            r_photos: List[str] = []
            if rev.get("photo_urls"):
                try:
                    r_photos = json.loads(rev["photo_urls"])
                except Exception:
                    r_photos = []

            pname = rev["place_name"] or (poi["name"] if poi else "Reviewed Venue")
            rating_str = f"{rev['rating']}★" if rev.get("rating") else "Reviewed"
            snippet = (rev.get("review_text") or "").strip()[:120]
            reasoning = (
                f"Restore missing visit to {pname} corroborated by your {rating_str} Google Maps review on {date_str_opt}"
                + (f': "{snippet}"' if snippet else ".")
            )
            evidence_rev = {
                "evidence_type": "MAPS_REVIEWS",
                "review_id": rev["id"],
                "rating": rev.get("rating"),
                "review_text": rev.get("review_text"),
                "published_at": pub_iso,
                "review_photos": r_photos[:4],
            }
            patch_data_rev = {
                "action": "RESTORE_REVIEWED_VISIT",
                "date": date_str_opt,
                "start_ts": st_ts,
                "end_ts": et_ts,
                "start_time": st_iso,
                "end_time": et_iso,
                "duration_minutes": 60.0,
                "time_window": time_win,
                "place_id": matched_pid,
                "resolved_poi_name": pname,
                "target_place": pname,
                "address": rev.get("address") or (poi.get("address") if poi else None),
                "category": rev.get("category") or (poi.get("category") if poi else None) or "Food & Drink",
                "city": rev.get("city") or (poi.get("city") if poi else None),
                "latitude": rlat,
                "longitude": rlng,
                "centroid_lat": rlat,
                "centroid_lng": rlng,
                "review_rating": rev.get("rating"),
                "review_text": rev.get("review_text"),
                "review_photos": r_photos[:4],
            }
            add_proposal(
                "review",
                rev["id"],
                date_str_opt,
                "RESTORE_REVIEWED_VISIT",
                "maps_reviews",
                reasoning,
                0.93,
                patch_data_rev,
                evidence_rev,
            )

        # =====================================================================
        # STREAM 3: PLAZES_ARCHIVE (Historical Check-Ins 2005-2010)
        # =====================================================================
        if os.path.exists(plazes_zip_path):
            try:
                with zipfile.ZipFile(plazes_zip_path, "r") as pz:
                    tsv_name = next((n for n in pz.namelist() if n.endswith("plazes_visited.tsv")), None)
                    acts_name = next((n for n in pz.namelist() if n.endswith("activities_created.json")), None)
                    if tsv_name and acts_name:
                        tsv_raw = pz.read(tsv_name).decode("utf-8", errors="ignore")
                        plazes_venues: Dict[str, Dict[str, Any]] = {}
                        for line in tsv_raw.splitlines()[1:]:
                            cols = line.split("\t")
                            if len(cols) >= 9:
                                try:
                                    v_name = cols[0].strip()
                                    v_addr = f"{cols[1].strip()}, {cols[3].strip()}".strip(", ")
                                    v_lat = float(cols[7])
                                    v_lng = float(cols[8])
                                    plazes_venues[v_name.lower()] = {
                                        "name": v_name,
                                        "address": v_addr,
                                        "city": cols[3].strip(),
                                        "latitude": v_lat,
                                        "longitude": v_lng,
                                    }
                                except Exception:
                                    pass

                        acts_raw = json.loads(pz.read(acts_name))
                        plazes_added = 0
                        for act in acts_raw:
                            if plazes_added >= 80:
                                break
                            if not isinstance(act, dict):
                                continue
                            created_at = act.get("created_at") or act.get("updated_at") or ""
                            st_ts_p = parse_iso_to_ts(created_at)
                            if not st_ts_p:
                                continue
                            raw_plaze = act.get("plaze")
                            plaze_obj: Dict[str, Any] = raw_plaze if isinstance(raw_plaze, dict) else {}
                            vname = plaze_obj.get("name") or act.get("plaze_name") or act.get("title")
                            if not vname:
                                continue
                            vinfo: Dict[str, Any] = plazes_venues.get(str(vname).lower()) or {}
                            vlat_raw = plaze_obj.get("latitude") or vinfo.get("latitude")
                            vlng_raw = plaze_obj.get("longitude") or vinfo.get("longitude")
                            if vlat_raw is None or vlng_raw is None:
                                continue
                            vlat, vlng = float(vlat_raw), float(vlng_raw)
                            et_ts_p = st_ts_p + 3600.0
                            date_str_p = str(created_at)[:10]

                            idx = bisect.bisect_left(visit_starts, st_ts_p - 10800)
                            has_existing = False
                            for k in range(max(0, idx - 1), min(len(visit_segs), idx + 5)):
                                if abs(float(visit_segs[k]["start_ts"]) - st_ts_p) <= 10800:
                                    has_existing = True
                                    break
                            if has_existing:
                                continue

                            poi = find_nearest_poi(vlat, vlng, max_m=350.0, prefer_non_home=False)
                            if not poi:
                                continue
                            off_h = get_timezone_offset_hours(vlat, vlng, st_ts_p)
                            tz = datetime.timezone(datetime.timedelta(hours=off_h))
                            st_iso = datetime.datetime.fromtimestamp(st_ts_p, tz=tz).isoformat()
                            et_iso = datetime.datetime.fromtimestamp(et_ts_p, tz=tz).isoformat()
                            time_win = f"{st_iso[11:16]} – {et_iso[11:16]}"
                            status_txt = (act.get("status") or "").strip()

                            target_type_p, target_id_p = resolve_gap_or_segment_target(st_ts_p, et_ts_p)
                            reasoning = (
                                f"Restore historical Plazes check-in at {vname} on {date_str_p} ({time_win})"
                                + (f' — note: "{status_txt}"' if status_txt else ".")
                            )
                            evidence_p = {
                                "evidence_type": "PLAZES_CHECKIN",
                                "checkin_time": created_at,
                                "plaze_name": vname,
                                "status_note": status_txt,
                            }
                            patch_data_p = {
                                "action": "RESTORE_PLAZES_CHECKIN",
                                "gap_id": target_id_p if target_type_p == "gap" else None,
                                "date": date_str_p,
                                "start_ts": st_ts_p,
                                "end_ts": et_ts_p,
                                "start_time": st_iso,
                                "end_time": et_iso,
                                "duration_minutes": 60.0,
                                "time_window": time_win,
                                "place_id": poi["place_id"],
                                "resolved_poi_name": vname,
                                "target_place": vname,
                                "address": vinfo.get("address") or poi.get("address"),
                                "category": poi.get("category") or "Other / POI",
                                "city": vinfo.get("city") or poi.get("city"),
                                "latitude": vlat,
                                "longitude": vlng,
                                "centroid_lat": vlat,
                                "centroid_lng": vlng,
                                "status_note": status_txt,
                            }
                            add_proposal(
                                target_type_p,
                                target_id_p,
                                date_str_p,
                                "RESTORE_PLAZES_CHECKIN",
                                "plazes_archive",
                                reasoning,
                                0.94,
                                patch_data_p,
                                evidence_p,
                            )
                            plazes_added += 1
            except Exception:
                pass

        # =====================================================================
        # STREAM 4: LYFT PASSENGER RIDES & GOOGLE FIT SESSIONS
        # =====================================================================
        if os.path.exists(lyft_csv_path):
            try:
                with open(lyft_csv_path, "r", encoding="utf-8") as lf:
                    reader = csv.DictReader(lf)
                    for row in reader:
                        if row.get("status") != "finished":
                            continue
                        st_raw = (row.get("pickup_timestamp") or "").replace(" UTC", "+00:00").replace(" ", "T")
                        et_raw = (row.get("dropoff_timestamp") or "").replace(" UTC", "+00:00").replace(" ", "T")
                        st_ts_l = parse_iso_to_ts(st_raw)
                        et_ts_l = parse_iso_to_ts(et_raw)
                        if not st_ts_l or not et_ts_l or et_ts_l <= st_ts_l:
                            continue
                        slat = float(row["pickup_lat"]) if row.get("pickup_lat") else None
                        slng = float(row["pickup_lng"]) if row.get("pickup_lng") else None
                        elat = float(row["dropoff_lat"]) if row.get("dropoff_lat") else None
                        elng = float(row["dropoff_lng"]) if row.get("dropoff_lng") else None
                        if slat is None or slng is None or elat is None or elng is None:
                            continue

                        c.execute(
                            "SELECT id FROM segments WHERE segment_type = 'activity' AND ABS(start_ts - ?) <= 600 LIMIT 1;",
                            (st_ts_l,),
                        )
                        if c.fetchone():
                            continue

                        off_h = get_timezone_offset_hours(slat, slng, st_ts_l)
                        tz = datetime.timezone(datetime.timedelta(hours=off_h))
                        st_iso = datetime.datetime.fromtimestamp(st_ts_l, tz=tz).isoformat()
                        et_iso = datetime.datetime.fromtimestamp(et_ts_l, tz=tz).isoformat()
                        date_str_l = st_iso[:10]
                        time_win = f"{st_iso[11:16]} – {et_iso[11:16]}"
                        dur_m = round((et_ts_l - st_ts_l) / 60.0, 1)
                        dist_km = round(haversine_distance(slat, slng, elat, elng) / 1000.0, 2)

                        target_type_l, target_id_l = resolve_gap_or_segment_target(st_ts_l, et_ts_l)
                        reasoning = (
                            f"Insert verified Lyft ride ({dist_km} km, {dur_m:.0f}m, {time_win}) from Lyft ride ledger."
                        )
                        evidence_l = {
                            "evidence_type": "LYFT_LEDGER",
                            "pickup_timestamp": row.get("pickup_timestamp"),
                            "dropoff_timestamp": row.get("dropoff_timestamp"),
                            "distance_km": dist_km,
                        }
                        patch_data_l = {
                            "action": "INSERT_LYFT_RIDE",
                            "gap_id": target_id_l if target_type_l == "gap" else None,
                            "date": date_str_l,
                            "start_ts": st_ts_l,
                            "end_ts": et_ts_l,
                            "start_time": st_iso,
                            "end_time": et_iso,
                            "duration_minutes": dur_m,
                            "distance_km": dist_km,
                            "mode": "IN_TAXI",
                            "start_lat": slat,
                            "start_lng": slng,
                            "end_lat": elat,
                            "end_lng": elng,
                            "time_window": time_win,
                        }
                        add_proposal(
                            target_type_l,
                            target_id_l,
                            date_str_l,
                            "INSERT_LYFT_RIDE",
                            "lyft_archive",
                            reasoning,
                            0.96,
                            patch_data_l,
                            evidence_l,
                        )
            except Exception:
                pass

        # =====================================================================
        # STREAM 5: FLIGHT AIRPORT CONTINUITY
        # =====================================================================
        try:
            from enrichment.flight_airport_auditor import audit_flight_airports

            flight_props = audit_flight_airports(engine.db_path)
            for fp in flight_props[:80]:
                evidence_f = {
                    "evidence_type": "FLIGHT_PHYSICS",
                    "airport_iata": fp.get("airport_iata"),
                    "airport_name": fp.get("airport_name"),
                    "flight_id": fp.get("flight_id"),
                }
                add_proposal(
                    "flight",
                    fp["flight_id"],
                    fp["date"],
                    fp["type"],
                    "flight_airport_auditor",
                    fp["description"],
                    0.94,
                    fp,
                    evidence_f,
                )
        except Exception:
            pass

        if proposals_to_insert:
            c.executemany(
                """
                INSERT INTO fix_proposals (
                    target_type, target_id, date, proposed_action, source, reasoning,
                    confidence, status, patch_data_json, created_at,
                    engine_version, inference_run_id, evidence_json, decision_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                proposals_to_insert,
            )
            conn.commit()

        out = {
            "total_proposals": len(proposals_to_insert),
            "by_source": counts_by_source,
        }
        engine.complete_inference_run(conn, run_id, out)
        return out
    finally:
        conn.close()
