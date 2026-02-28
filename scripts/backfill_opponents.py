"""Backfill race_candidates table: for every race with IE spending, fetch all
active FEC candidates so the frontend can show opponents even with $0 spending."""
from __future__ import annotations

import time

import requests
from sqlalchemy import text
from sqlmodel import Session

from app.db import make_engine, init_db
from app.settings import load_settings
from app.schemas import RaceCandidate

FEC_API_BASE = "https://api.open.fec.gov/v1"


def fetch_fec_candidates(state: str, office: str, district: str | None,
                         api_key: str) -> list[dict]:
    """Fetch active 2026 candidates from FEC for a given race."""
    params = {
        "state": state,
        "office": office,
        "election_year": 2026,
        "has_raised_funds": "true",
        "is_active_candidate": "true",
        "api_key": api_key,
        "per_page": 100,
        "sort": "-receipts",
    }
    if office == "H" and district:
        params["district"] = district.lstrip("0") or "0"

    for attempt in range(3):
        try:
            resp = requests.get(f"{FEC_API_BASE}/candidates/", params=params, timeout=30)
            if resp.status_code != 200:
                return []
            return resp.json().get("results", [])
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < 2:
                time.sleep(2 ** attempt)
            continue
    return []


def main():
    settings = load_settings()
    engine = make_engine(settings)
    init_db(engine)  # creates race_candidates table if not exists
    api_key = settings.gov_api_key
    if not api_key:
        print("GOV_API_KEY not set")
        return

    with Session(engine) as session:
        # Get all distinct races from IE data
        races = session.execute(text("""
            SELECT DISTINCT
                candidate_state AS state,
                candidate_office AS office,
                candidate_district AS district
            FROM ie_schedule_e
            WHERE candidate_state IS NOT NULL
              AND candidate_office IS NOT NULL
              AND amount > 0
        """)).all()

        print(f"Found {len(races)} distinct races with IE spending")

        # Get existing candidate_ids with IE spending
        ie_cand_ids = set(r[0] for r in session.execute(text("""
            SELECT DISTINCT candidate_id FROM ie_schedule_e
            WHERE candidate_id IS NOT NULL AND amount > 0
        """)).all())

        total_added = 0
        total_races = 0

        for race in races:
            state, office, district = race.state, race.office, race.district
            if not state or not office:
                continue

            race_label = f"{state}-{'SEN' if office == 'S' else district or '??'}"
            fec_cands = fetch_fec_candidates(state, office, district, api_key)

            # Filter to major party candidates (DEM, REP) + top independents
            major = [c for c in fec_cands if c.get("party") in ("DEM", "REP")]
            # Take top 2 per party (by receipts, already sorted)
            dems = [c for c in major if c["party"] == "DEM"][:2]
            reps = [c for c in major if c["party"] == "REP"][:2]
            candidates = dems + reps

            added = 0
            for fc in candidates:
                cid = fc["candidate_id"]
                existing = session.get(RaceCandidate, cid)
                if existing:
                    continue

                session.add(RaceCandidate(
                    candidate_id=cid,
                    candidate_name=fc["name"],
                    party=fc.get("party"),
                    state=state,
                    office=office,
                    district=district or "",
                    has_ie_spending=cid in ie_cand_ids,
                ))
                added += 1

            if added > 0:
                total_added += added
                total_races += 1
                print(f"  {race_label}: +{added} candidates (from {len(fec_cands)} FEC results)")

            time.sleep(0.2)  # rate limit

        # Also mark candidates already in IE data
        for cid in ie_cand_ids:
            existing = session.get(RaceCandidate, cid)
            if existing:
                if not existing.has_ie_spending:
                    existing.has_ie_spending = True
                    session.add(existing)
            else:
                # Get their info from ie_schedule_e
                row = session.execute(text("""
                    SELECT candidate_id, MAX(candidate_name) AS name,
                           MAX(candidate_party) AS party,
                           MAX(candidate_state) AS state,
                           MAX(candidate_office) AS office,
                           MAX(candidate_district) AS district
                    FROM ie_schedule_e
                    WHERE candidate_id = :cid
                    GROUP BY candidate_id
                """), {"cid": cid}).first()
                if row:
                    session.add(RaceCandidate(
                        candidate_id=row.candidate_id,
                        candidate_name=row.name,
                        party=row.party,
                        state=row.state,
                        office=row.office,
                        district=row.district or "",
                        has_ie_spending=True,
                    ))
                    total_added += 1

        session.commit()
        print(f"\nDone: {total_added} candidates added across {total_races} races")


if __name__ == "__main__":
    main()
