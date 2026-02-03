#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from typing import Optional, Any, Dict

import pandas as pd
from sqlmodel import Session, SQLModel, select, text
from dotenv import load_dotenv

from app.db import make_engine
from app.settings import load_settings
from app.schemas import Committee, SeenFiling, FilingF3X, IEScheduleE

load_dotenv()


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    return s


def main():
    ap = argparse.ArgumentParser(
        description="Ingest committee identity CSV into committees table")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--create-tables", action="store_true")
    ap.add_argument("--backfill-names", action="store_true")
    args = ap.parse_args()

    df = pd.read_csv(args.csv, dtype=str)

    required = {"CMTE_ID", "CMTE_NM"}
    if not required.issubset(df.columns):
        raise SystemExit("CSV missing CMTE_ID or CMTE_NM")

    engine = make_engine(load_settings())

    if args.create_tables:
        SQLModel.metadata.create_all(engine)

    now = datetime.utcnow()

    keep_raw = [
        "CMTE_ID", "CMTE_NM", "CMTE_TP", "CMTE_DSGN",
        "CMTE_FILING_FREQ", "CMTE_CITY", "CMTE_ST",
        "TRES_NM", "CAND_ID"
    ]

    with Session(engine) as session:
        count = 0
        for _, r in df.iterrows():
            committee_id = _clean(r.get("CMTE_ID"))
            committee_name = _clean(r.get("CMTE_NM"))
            if not committee_id or not committee_name:
                continue

            raw_meta: Dict[str, Any] = {c: _clean(r.get(c)) for c in keep_raw}

            # Check if exists
            existing = session.get(Committee, committee_id)
            if existing:
                # Update
                existing.committee_name = committee_name
                existing.committee_type = _clean(r.get("CMTE_TP"))
                existing.designation = _clean(r.get("CMTE_DSGN"))
                existing.filing_freq = _clean(r.get("CMTE_FILING_FREQ"))
                existing.city = _clean(r.get("CMTE_CITY"))
                existing.state = _clean(r.get("CMTE_ST"))
                existing.treasurer_name = _clean(r.get("TRES_NM"))
                existing.candidate_id = _clean(r.get("CAND_ID"))
                existing.raw_meta = raw_meta
                existing.provisional = False
                existing.updated_at_utc = now
            else:
                # Insert
                c = Committee(
                    committee_id=committee_id,
                    committee_name=committee_name,
                    committee_type=_clean(r.get("CMTE_TP")),
                    designation=_clean(r.get("CMTE_DSGN")),
                    filing_freq=_clean(r.get("CMTE_FILING_FREQ")),
                    city=_clean(r.get("CMTE_CITY")),
                    state=_clean(r.get("CMTE_ST")),
                    treasurer_name=_clean(r.get("TRES_NM")),
                    candidate_id=_clean(r.get("CAND_ID")),
                    raw_meta=raw_meta,
                    provisional=False,
                    updated_at_utc=now,
                )
                session.add(c)

            count += 1
            if count % 1000 == 0:
                session.commit()
                print(f"  {count:,} / {len(df):,}")

        session.commit()
        print(f"Upserted {count:,} committees")

    if args.backfill_names:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE filings_f3x f
                SET committee_name = c.committee_name,
                    updated_at_utc = NOW()
                FROM committees c
                WHERE f.committee_name IS NULL
                  AND f.committee_id = c.committee_id
            """))

            conn.execute(text("""
                UPDATE ie_schedule_e ie
                SET committee_name = c.committee_name
                FROM committees c
                WHERE ie.committee_name IS NULL
                  AND ie.committee_id = c.committee_id
            """))

            print("Backfilled committee_name where missing")


if __name__ == "__main__":
    main()
