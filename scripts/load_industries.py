"""
Load OpenSecrets industry lookup tables into Postgres.

Usage:
    python -m scripts.load_industries \
        --donors-csv ~/Documents/code/issue_map/data/donors_by_industry.csv \
        --orgs-csv ~/Documents/code/issue_map/data/orgs_by_industry.csv \
        --create-tables --seed-pac-groups
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

import pandas as pd
from sqlmodel import Session, SQLModel, text
from dotenv import load_dotenv

sys.path.insert(0, "/app")

from app.db import make_engine
from app.settings import load_settings
from app.schemas import DonorIndustry, OrgIndustry, AppConfig

load_dotenv()

DEFAULT_PAC_GROUPS = [
    {
        "name": "Pro-Israel",
        "pacs": [
            {"name": "United Democracy Project", "committee_id": "C00799031"},
            {"name": "DMFI PAC", "committee_id": "C00710848"},
        ],
    },
    {
        "name": "Pro-Trump",
        "pacs": [
            {"name": "MAGA Inc.", "committee_id": "C00825851"},
            {"name": "AmericaPAC", "committee_id": "C00879510"},
            {"name": "Preserve America", "committee_id": "C00878801"},
            {"name": "American Crossroads", "committee_id": "C00487363"},
            {"name": "Right for America", "committee_id": "C00867036"},
            {"name": "Restoration PAC", "committee_id": "C00571588"},
        ],
    },
    {
        "name": "Crypto",
        "pacs": [
            {"name": "Fairshake", "committee_id": "C00835959"},
            {"name": "Protect Progress", "committee_id": "C00848440"},
            {"name": "Defend American Jobs", "committee_id": "C00836221"},
            {"name": "Digital Freedom Fund", "committee_id": "C00911610"},
        ],
    },
    {
        "name": "AI",
        "pacs": [
            {"name": "Leading the Future", "committee_id": "C00916114"},
            {"name": "Think Big", "committee_id": "C00923417"},
            {"name": "American Mission", "committee_id": "C00916692"},
            {"name": "Public First", "committee_id": "C00930503"},
            {"name": "Defending our Values", "committee_id": "C00928390"},
            {"name": "Jobs and Democracy", "committee_id": "C00928374"},
        ],
    },
]


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    return s


def load_donors(session: Session, csv_path: str):
    print(f"Loading donors from {csv_path}...")
    df = pd.read_csv(csv_path, dtype=str)
    count = 0
    for _, r in df.iterrows():
        contrib_id = _clean(r.get("ContribID"))
        contrib_name = _clean(r.get("Contrib"))
        if not contrib_id or not contrib_name:
            continue

        session.add(DonorIndustry(
            contrib_id=contrib_id,
            contrib_name=contrib_name,
            name_upper=contrib_name.upper(),
            org_name=_clean(r.get("Orgname")),
            real_code=_clean(r.get("RealCode")),
            cat_name=_clean(r.get("Catname")),
            industry=_clean(r.get("Industry")),
            sector=_clean(r.get("Sector")),
        ))
        count += 1
        if count % 1000 == 0:
            session.commit()
            print(f"  donors: {count:,} / {len(df):,}")

    session.commit()
    print(f"Loaded {count:,} donor industry records")


def load_orgs(session: Session, csv_path: str):
    print(f"Loading orgs from {csv_path}...")
    df = pd.read_csv(csv_path, dtype=str)
    count = 0
    for _, r in df.iterrows():
        org_name = _clean(r.get("Org"))
        if not org_name:
            continue

        session.add(OrgIndustry(
            org_name=org_name,
            org_upper=org_name.upper(),
            cmte_id=_clean(r.get("CmteID")),
            pac_short=_clean(r.get("PACShort")),
            prim_code=_clean(r.get("PrimCode")),
            cat_name=_clean(r.get("Catname")),
            industry=_clean(r.get("Industry")),
            sector=_clean(r.get("Sector")),
        ))
        count += 1
        if count % 1000 == 0:
            session.commit()
            print(f"  orgs: {count:,} / {len(df):,}")

    session.commit()
    print(f"Loaded {count:,} org industry records")


def seed_pac_groups(session: Session):
    from datetime import datetime, timezone

    existing = session.get(AppConfig, "pac_groups")
    if existing and existing.value:
        print("PAC groups already configured, skipping seed")
        return

    config = AppConfig(
        key="pac_groups",
        value=json.dumps(DEFAULT_PAC_GROUPS),
        updated_at=datetime.now(timezone.utc),
    )
    session.merge(config)
    session.commit()
    print(f"Seeded {len(DEFAULT_PAC_GROUPS)} PAC groups")


def main():
    ap = argparse.ArgumentParser(description="Load industry lookup tables")
    ap.add_argument("--donors-csv", required=True)
    ap.add_argument("--orgs-csv", required=True)
    ap.add_argument("--create-tables", action="store_true")
    ap.add_argument("--truncate-first", action="store_true",
                    help="TRUNCATE tables before loading")
    ap.add_argument("--seed-pac-groups", action="store_true",
                    help="Seed default PAC groups config")
    args = ap.parse_args()

    engine = make_engine(load_settings())

    if args.create_tables:
        SQLModel.metadata.create_all(engine)
        print("Tables created")

    with Session(engine) as session:
        if args.truncate_first:
            session.execute(text("TRUNCATE donor_industries"))
            session.execute(text("TRUNCATE org_industries"))
            session.commit()
            print("Tables truncated")

        load_donors(session, args.donors_csv)
        load_orgs(session, args.orgs_csv)

        if args.seed_pac_groups:
            seed_pac_groups(session)

    print("Done!")


if __name__ == "__main__":
    main()
