"""
Non-Destructive Multi-Layer Timeline Reconstruction & Inference Engine.

Architecture:
- Layer 0 (`raw_source_segments`): Immutable ledger of all authentic upstream observations
  (On-Device JSON, Cloud Takeout ZIP, Citi Bike telemetry, Plazes check-ins).
  Never mutated or deleted by downstream inference passes.
- Layer 1 (`segments` & `inference_runs`): Derived canonical timeline assembled strictly from
  authentic Layer 0 observations + versioned deterministic inference passes, with zero
  uncorroborated gap-plugging guesses (`SYNTHETIC_LIFE` / `SYNTHETIC_GAP_HEAL`).
- Layer 2 (`user_decisions` & `fix_proposals`): Immutable ledger of human review decisions
  (accepted proposals, rejected proposals, manual edits) and evidence-backed candidate
  proposals. Future engine versions can re-run inference passes from Layer 0 while
  automatically respecting all prior human decisions.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from typing import Any, Dict, Optional

from db import get_db_path, init_db
from enrichment.passes import (
    ENGINE_VERSION,
    SYNTHETIC_GUESS_SOURCES,
    compute_decision_key,
    compute_source_key,
    generate_evidence_backed_proposals,
    ingest_pixel10_export_to_layer0,
    ingest_takeout_2024_to_layer0,
    parse_iso_to_ts,
    parse_latlng_str,
    purge_heuristic_gap_guesses,
    restore_missing_and_swallowed_authentic_visits,
    sanitize_photos_and_reviews_metadata,
    sanitize_physics_and_polylines,
    snapshot_existing_authentic_segments_to_layer0,
    synchronize_places_and_metadata,
)

__all__ = [
    "ENGINE_VERSION",
    "LayeredTimelineEngine",
    "SYNTHETIC_GUESS_SOURCES",
    "compute_decision_key",
    "compute_source_key",
    "parse_iso_to_ts",
    "parse_latlng_str",
]


class LayeredTimelineEngine:
    """
    Coordinates Layer 0 immutable ingestion, Layer 1 non-guessing baseline assembly,
    and Layer 2 evidence-backed proposal generation & human decision persistence.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = get_db_path(db_path)
        init_db(self.db_path)

    def start_inference_run(
        self, conn: sqlite3.Connection, pass_name: str, input_summary: Dict[str, Any]
    ) -> int:
        c = conn.cursor()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        c.execute(
            """
            INSERT INTO inference_runs (engine_version, pass_name, started_at, input_summary_json, status)
            VALUES (?, ?, ?, ?, 'IN_PROGRESS');
            """,
            (ENGINE_VERSION, pass_name, now_iso, json.dumps(input_summary)),
        )
        conn.commit()
        return int(c.lastrowid or 0)

    def complete_inference_run(
        self, conn: sqlite3.Connection, run_id: int, output_summary: Dict[str, Any]
    ) -> None:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE inference_runs
            SET completed_at = ?, output_summary_json = ?, status = 'COMPLETED'
            WHERE run_id = ?;
            """,
            (now_iso, json.dumps(output_summary), run_id),
        )
        conn.commit()

    def record_user_decision(
        self,
        conn: sqlite3.Connection,
        decision_type: str,
        action: str,
        date_str: str,
        start_ts: Optional[float],
        end_ts: Optional[float],
        target_place_id: Optional[str],
        target_place_name: Optional[str],
        source_stream: Optional[str],
        patch_data: Dict[str, Any],
        decision_key: Optional[str] = None,
    ) -> str:
        """Persists an immutable user decision so future engine runs respect it."""
        dkey = decision_key or compute_decision_key(
            action, date_str, start_ts, end_ts, target_place_id or target_place_name
        )
        conn.execute(
            """
            INSERT INTO user_decisions (
                decision_key, decision_type, date, start_ts, end_ts,
                target_place_id, target_place_name, source_stream, proposal_action, patch_data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_key) DO UPDATE SET
                decision_type = excluded.decision_type,
                target_place_id = excluded.target_place_id,
                target_place_name = excluded.target_place_name,
                patch_data_json = excluded.patch_data_json,
                created_at = CURRENT_TIMESTAMP;
            """,
            (
                dkey,
                decision_type,
                date_str,
                start_ts,
                end_ts,
                target_place_id,
                target_place_name,
                source_stream,
                action,
                json.dumps(patch_data),
            ),
        )
        return dkey

    def snapshot_existing_authentic_segments_to_layer0(self) -> Dict[str, int]:
        return snapshot_existing_authentic_segments_to_layer0(self)

    def ingest_pixel10_export_to_layer0(self, json_path: str) -> Dict[str, int]:
        return ingest_pixel10_export_to_layer0(self, json_path)

    def ingest_takeout_2024_to_layer0(self, zip_path: str) -> Dict[str, int]:
        return ingest_takeout_2024_to_layer0(self, zip_path)

    def purge_heuristic_gap_guesses(self) -> Dict[str, int]:
        return purge_heuristic_gap_guesses(self)

    def restore_missing_and_swallowed_authentic_visits(self) -> Dict[str, int]:
        return restore_missing_and_swallowed_authentic_visits(self)

    def sanitize_physics_and_polylines(self) -> Dict[str, int]:
        return sanitize_physics_and_polylines(self)

    def synchronize_places_and_metadata(self) -> Dict[str, int]:
        return synchronize_places_and_metadata(self)

    def sanitize_photos_and_reviews_metadata(self) -> Dict[str, int]:
        return sanitize_photos_and_reviews_metadata(self)

    def generate_evidence_backed_proposals(
        self,
        plazes_zip_path: str = "data/plazes/plazes.zip",
        lyft_csv_path: str = "data/citibike/lyft_data/passenger_rides.csv",
        clear_pending: bool = True,
    ) -> Dict[str, Any]:
        return generate_evidence_backed_proposals(
            self,
            plazes_zip_path=plazes_zip_path,
            lyft_csv_path=lyft_csv_path,
            clear_pending=clear_pending,
        )

    def run_full_layered_pipeline(
        self,
        pixel10_json: Optional[str] = None,
        takeout_zip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes the complete non-destructive Layer 0 -> Layer 1 -> Layer 2 pipeline."""
        on_device_path = pixel10_json or os.environ.get(
            "TIMELINE_ON_DEVICE_JSON", "pixel10_export/Timeline-latest.json"
        )
        takeout_path = takeout_zip or os.environ.get(
            "TIMELINE_TAKEOUT_ZIP", "data/takeout/Takeout.zip"
        )

        print("[*] Step 1/7: Snapshotting existing authentic segments into Layer 0 (raw_source_segments)...")
        s0 = self.snapshot_existing_authentic_segments_to_layer0()
        print(f"    -> {s0}")

        print("[*] Step 2/7: Ingesting on-device export (ON_DEVICE_2026) into Layer 0...")
        s1 = self.ingest_pixel10_export_to_layer0(on_device_path)
        print(f"    -> {s1}")

        print("[*] Step 3/7: Ingesting Takeout archive (TAKEOUT_2024) into Layer 0...")
        s2 = self.ingest_takeout_2024_to_layer0(takeout_path)
        print(f"    -> {s2}")

        print("[*] Step 4/7: Purging heuristic gap-plugging guesses from active segments...")
        s3 = self.purge_heuristic_gap_guesses()
        print(f"    -> {s3}")

        print("[*] Step 5/7: Restoring missing and swallowed authentic baseline visits...")
        s4 = self.restore_missing_and_swallowed_authentic_visits()
        print(f"    -> {s4}")

        print("[*] Step 6/7: Sanitizing modal physics, polylines, and Place/Segment metadata...")
        s5 = self.sanitize_physics_and_polylines()
        s6 = self.synchronize_places_and_metadata()
        print(f"    -> physics: {s5}")
        print(f"    -> metadata: {s6}")

        print("[*] Step 7/7: Running diagnostics & generating strictly evidence-backed Fix Proposals...")
        from diagnostics import TimelineDiagnosticsEngine

        diag = TimelineDiagnosticsEngine(self.db_path)
        d_report = diag.run_full_diagnostics()

        return {
            "layer0_snapshot": s0,
            "layer0_pixel10": s1,
            "layer0_takeout2024": s2,
            "purged_guesses": s3,
            "restored_baseline": s4,
            "physics_sanitization": s5,
            "metadata_sync": s6,
            "diagnostics": d_report.get("scorecard"),
            "proposals": d_report.get("proposals"),
        }


if __name__ == "__main__":
    engine = LayeredTimelineEngine()
    summary = engine.run_full_layered_pipeline()
    print("\n=== Layered Engine Execution Summary ===")
    print(json.dumps(summary, indent=2))
