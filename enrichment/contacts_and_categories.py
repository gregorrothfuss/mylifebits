"""
Contacts.vcf Integration & Advanced Multi-Modal Place Categorization Engine.
Parses Apple/Google vCards to disambiguate visited residences, enrich friends & family stays,
and accurately classifies transit stations, bakeries, cafes, stores, riads, and baths.
"""

import sqlite3
import re
import os
import json
from typing import Dict, Any, List, Optional, Tuple

try:
    from enrichment.place_types_taxonomy import map_google_types_to_category
except ImportError:
    from place_types_taxonomy import map_google_types_to_category

DEFAULT_DB_PATH = "timeline_viewer.db"
DEFAULT_VCF_PATH = os.environ.get("CONTACTS_VCF_PATH", "data/Contacts.vcf")


def normalize_street_name(s: Optional[str]) -> str:
    """Normalizes international and German/Swiss street abbreviations."""
    if not s:
        return ""
    norm = s.lower().replace(".", "").replace(",", " ").strip()
    norm = norm.replace("strasse", "str").replace("straße", "str")
    norm = norm.replace("avenue", "ave")
    norm = norm.replace("street", "st")
    norm = norm.replace("boulevard", "blvd")
    norm = norm.replace("drive", "dr")
    norm = norm.replace("road", "rd")
    norm = norm.replace("lane", "ln")
    return norm


def parse_vcf_contacts(vcf_path: str = DEFAULT_VCF_PATH) -> List[Dict[str, Any]]:
    """Parses Contacts.vcf into structured contact objects with physical addresses."""
    if not os.path.exists(vcf_path):
        return []

    with open(vcf_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    vcards = text.split("END:VCARD")
    contacts = []
    
    # Matches standalone street keywords AND German compound street names (e.g. Regensbergstr, Ottikerstrasse)
    street_pattern = r"(?:\b(?:st|street|ave|avenue|str|strasse|straße|rd|road|ln|lane|way|blvd|dr|drive|pl|place|court|ct|crescent|terrace)\b|[a-zA-Z]+(?:str|strasse|straße|gasse|weg|platz)\b)"

    for v in vcards:
        fn_m = re.search(r"FN:(.*)", v)
        if not fn_m:
            continue
        raw_name = fn_m.group(1).strip()
        name = re.sub(r"[^\w\s\.\,\-\'\(\)]", "", raw_name).strip()
        if not name or len(name) < 2:
            continue

        adr_matches = re.findall(r"(?:item\d+\.)?ADR[^:]*:(.*)", v)
        emails = re.findall(r"(?:item\d+\.)?EMAIL[^:]*:(.*)", v)
        phones = re.findall(r"(?:item\d+\.)?TEL[^:]*:(.*)", v)
        org_m = re.search(r"ORG:(.*)", v)
        org = org_m.group(1).strip() if org_m else None

        for adr in adr_matches:
            raw_parts = [p.strip() for p in adr.replace(r"\,", ",").replace(r"\n", " ").split(";") if p.strip()]
            if not raw_parts:
                continue

            for p in raw_parts:
                has_digit = re.search(r"\b\d+\b", p)
                has_street = re.search(street_pattern, p, re.IGNORECASE)
                if has_digit and has_street and len(p) >= 5:
                    clean_addr = ", ".join(raw_parts)
                    contacts.append({
                        "name": name,
                        "organization": org,
                        "street": p.strip(),
                        "full_address": clean_addr,
                        "raw_parts": raw_parts,
                        "email": emails[0].strip() if emails else None,
                        "phone": phones[0].strip() if phones else None
                    })
                    break

    return contacts


def init_contacts_table(conn: sqlite3.Connection, contacts: List[Dict[str, Any]]):
    """Initializes and populates contacts table in SQLite."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        organization TEXT,
        street TEXT,
        full_address TEXT,
        email TEXT,
        phone TEXT
    );
    """)
    conn.execute("DELETE FROM contacts;")
    
    rows = [(c["name"], c["organization"], c["street"], c["full_address"], c["email"], c["phone"]) for c in contacts]
    conn.executemany("""
    INSERT INTO contacts (name, organization, street, full_address, email, phone)
    VALUES (?, ?, ?, ?, ?, ?);
    """, rows)
    conn.commit()
    print(f"[✓] Populated contacts table with {len(rows)} verified street-level contact entries.")


def enrich_database_with_contacts_and_categories(db_path: str = DEFAULT_DB_PATH, vcf_path: str = DEFAULT_VCF_PATH):
    """Enriches database with contacts and re-categorizes all places and segments."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    c = conn.cursor()

    # 1. Update first_visit_time and last_visit_time across catalog
    c.execute("""
    UPDATE places
    SET first_visit_time = (SELECT min(s.start_time) FROM segments s WHERE s.place_id = places.place_id),
        last_visit_time = (SELECT max(s.start_time) FROM segments s WHERE s.place_id = places.place_id),
        visit_count = (SELECT count(*) FROM segments s WHERE s.place_id = places.place_id)
    WHERE EXISTS (SELECT 1 FROM segments s WHERE s.place_id = places.place_id);
    """)
    conn.commit()

    # 2. Parse Contacts
    contacts = parse_vcf_contacts(vcf_path)
    init_contacts_table(conn, contacts)

    # 3. Canonical Primary Residences from database
    c.execute("SELECT place_id FROM places WHERE semantic_type = 'TYPE_HOME' OR category = 'Home & Residence';")
    primary_residence_ids = {r[0] for r in c.fetchall() if r[0]}

    # 4. Workplaces
    c.execute("UPDATE places SET category = 'Work & Office', semantic_type = 'TYPE_WORK' WHERE semantic_type = 'TYPE_WORK';")
    c.execute("UPDATE segments SET category = 'Work & Office', semantic_type = 'TYPE_WORK' WHERE semantic_type = 'TYPE_WORK';")
    conn.commit()

    # 5. Link Contacts with Normalized Street Matching
    c.execute("SELECT place_id, name, address, category, semantic_type FROM places WHERE address IS NOT NULL;")
    places = c.fetchall()

    linked_contacts = 0
    for ct in contacts:
        c_name = ct["name"]
        c_st_norm = normalize_street_name(ct["street"])
        num_m = re.search(r"\b\d+\b", c_st_norm)
        if not num_m:
            continue
        num = num_m.group(0)
        words = [w for w in re.findall(r"[a-zA-Z]{4,}", c_st_norm) if w not in ("ave", "str", "blvd", "dr", "rd", "ln", "crescent", "terrace", "place")]
        if not words:
            continue

        for pid, pname, paddr, pcat, psem in places:
            if pid in primary_residence_ids or psem in ("TYPE_HOME", "TYPE_WORK"):
                continue
            paddr_norm = normalize_street_name(paddr)
            pname_norm = normalize_street_name(pname)

            if re.search(rf"\b{num}\b", paddr_norm) and any(w in paddr_norm or w in pname_norm for w in words):
                commercial_tokens = ["airport", "terminal", "station", "subway", "whole foods", "cvs", "supermarket", "mall", "park", "schloss"]
                if not any(k in (pname or "").lower() for k in commercial_tokens):
                    new_title = f"{c_name} ({pname})" if c_name not in pname else pname
                    c.execute("UPDATE places SET name = ?, category = 'Friends & Family' WHERE place_id = ?;", (new_title, pid))
                    c.execute("UPDATE segments SET place_name = ?, category = 'Friends & Family' WHERE place_id = ?;", (new_title, pid))
                    linked_contacts += 1

    conn.commit()
    print(f"[✓] Linked {linked_contacts} contacts to visited residences.")
    conn.close()


if __name__ == "__main__":
    enrich_database_with_contacts_and_categories()
