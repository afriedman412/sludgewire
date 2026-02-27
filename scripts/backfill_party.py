"""Backfill candidate_party from FEC API for IE records with null party."""
from __future__ import annotations

import time

import requests
from sqlalchemy import text
from sqlmodel import Session

from app.db import make_engine
from app.settings import load_settings

FEC_API_BASE = "https://api.open.fec.gov/v1"


def fetch_candidate_party(candidate_id: str, api_key: str) -> str | None:
    """Look up a candidate's party from the FEC API."""
    url = f"{FEC_API_BASE}/candidate/{candidate_id}/"
    resp = requests.get(url, params={"api_key": api_key}, timeout=10)
    if resp.status_code != 200:
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    return results[0].get("party")


def main():
    settings = load_settings()
    engine = make_engine(settings)
    api_key = settings.gov_api_key
    if not api_key:
        print("GOV_API_KEY not set")
        return

    with Session(engine) as session:
        # Get distinct candidate_ids with null party
        rows = session.execute(text("""
            SELECT DISTINCT candidate_id
            FROM ie_schedule_e
            WHERE candidate_id IS NOT NULL
              AND (candidate_party IS NULL OR candidate_party = '')
        """)).all()

        candidate_ids = [r[0] for r in rows]
        print(f"Found {len(candidate_ids)} candidate IDs with null party")

        updated = 0
        failed = 0
        for i, cid in enumerate(candidate_ids):
            party = fetch_candidate_party(cid, api_key)
            if party:
                result = session.execute(
                    text("""
                        UPDATE ie_schedule_e
                        SET candidate_party = :party
                        WHERE candidate_id = :cid
                          AND (candidate_party IS NULL OR candidate_party = '')
                    """),
                    {"party": party, "cid": cid},
                )
                updated += result.rowcount
                print(f"  [{i+1}/{len(candidate_ids)}] {cid} -> {party} ({result.rowcount} rows)")
            else:
                failed += 1
                print(f"  [{i+1}/{len(candidate_ids)}] {cid} -> not found")

            # Rate limit: FEC API allows 1000/hour, be conservative
            time.sleep(0.2)

        session.commit()
        print(f"\nDone: {updated} rows updated, {failed} candidates not found")


if __name__ == "__main__":
    main()
