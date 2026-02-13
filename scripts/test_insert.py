#!/usr/bin/env python3
"""Test inserting a single committee row to debug the f405 error."""
from datetime import datetime
import json

import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from app.db import make_engine
from app.settings import load_settings
from app.schemas import Committee, FilingF3X, IEScheduleE

CSV_PATH = "app/data/committee_summary_2026.csv"

engine = make_engine(load_settings())

# Read first row
df = pd.read_csv(CSV_PATH, dtype=str, nrows=1)
r = df.iloc[0]

def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    return s

keep_raw = ["CMTE_ID", "CMTE_NM", "CMTE_TP", "CMTE_DSGN",
            "CMTE_FILING_FREQ", "CMTE_CITY", "CMTE_ST", "TRES_NM", "CAND_ID"]

raw_meta = {c: clean(r.get(c)) for c in keep_raw}

row = dict(
    committee_id=clean(r.get("CMTE_ID")),
    committee_name=clean(r.get("CMTE_NM")),
    committee_type=clean(r.get("CMTE_TP")),
    designation=clean(r.get("CMTE_DSGN")),
    filing_freq=clean(r.get("CMTE_FILING_FREQ")),
    city=clean(r.get("CMTE_CITY")),
    state=clean(r.get("CMTE_ST")),
    treasurer_name=clean(r.get("TRES_NM")),
    candidate_id=clean(r.get("CAND_ID")),
    raw_meta=raw_meta,
    provisional=False,
    updated_at_utc=datetime.utcnow(),
)

print("Row to insert:")
for k, v in row.items():
    print(f"  {k}: {v!r} ({type(v).__name__})")

print("\nTrying ORM insert...")
try:
    with Session(engine) as session:
        c = Committee(**row)
        session.add(c)
        session.commit()
        print("ORM insert: SUCCESS")
except Exception as e:
    print(f"ORM insert: FAILED - {e}")

print("\nTrying Core insert...")
try:
    with engine.begin() as conn:
        stmt = insert(Committee).values([row])
        conn.execute(stmt)
        print("Core insert: SUCCESS")
except Exception as e:
    print(f"Core insert: FAILED - {e}")
