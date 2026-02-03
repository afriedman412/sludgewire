import argparse
import random
from datetime import datetime, timedelta, timezone, date

from sqlmodel import Session, select
from sqlalchemy import text
from app.db import make_engine, init_db
from app.settings import load_settings
from app.schemas import FilingF3X, IEScheduleE, SeenFiling, Committee


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truncate", action="store_true",
                    help="Truncate filing tables before seeding")
    args = ap.parse_args()

    settings = load_settings()
    engine = make_engine(settings)
    init_db(engine)

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=10)

    with Session(engine) as session:
        if args.truncate:
            session.exec(
                text(
                    "TRUNCATE TABLE ie_schedule_e, filings_f3x, seen_filings RESTART IDENTITY CASCADE")
            )
            session.commit()
            print("Truncated filing tables")

        # Get some real committee IDs from the DB
        stmt = select(Committee.committee_id,
                      Committee.committee_name).limit(100)
        committees = session.exec(stmt).all()
        if not committees:
            print("No committees in DB - run ingest_comms.py first")
            return

        # Seed 3X filings (some above threshold)
        for i in range(12):
            filing_id = 7000000000 + i
            filed_at = start + timedelta(minutes=40 * i)
            total = random.choice([12000, 32000, 51000, 78000, 150000])

            comm_id, comm_name = random.choice(committees)

            session.add(SeenFiling(filing_id=filing_id, source_feed="seed"))
            session.add(
                FilingF3X(
                    filing_id=filing_id,
                    committee_id=comm_id,
                    committee_name=comm_name,
                    form_type="F3XN",
                    report_type="QUARTERLY YEAR-END",
                    coverage_from=date(2025, 7, 1),
                    coverage_through=date(2025, 12, 31),
                    filed_at_utc=filed_at,
                    fec_url=f"https://docquery.fec.gov/dcdev/posted/{filing_id}.fec",
                    total_receipts=float(total),
                    threshold_flag=(total >= 50000),
                    raw_meta={"seed": True},
                )
            )

        # Seed Schedule E events "today"
        for i in range(50):
            filing_id = 9100000000 + (i // 8)
            filed_at = now - timedelta(minutes=random.randint(0, 600))
            amount = random.choice([250, 1200, 5000, 25000, 100000])

            comm_id, comm_name = random.choice(committees)
            raw_line = f"SE|{amount}|{filed_at.date().strftime('%m/%d/%Y')}|S|CANDIDATE X|..."

            session.add(
                IEScheduleE(
                    event_id=f"seed-{i}",
                    filing_id=filing_id,
                    filer_id=comm_id,
                    committee_id=comm_id,
                    committee_name=comm_name,
                    form_type="F5_24",
                    report_type="24 HOUR NOTICE",
                    coverage_from=None,
                    coverage_through=None,
                    filed_at_utc=filed_at,
                    expenditure_date=filed_at.date(),
                    amount=float(amount),
                    support_oppose=random.choice(["S", "O"]),
                    candidate_id=None,
                    candidate_name=random.choice(
                        ["DOE, JANE", "SMITH, JOHN", "LEE, KAI"]),
                    election_code=None,
                    purpose="DIGITAL ADS",
                    payee_name=random.choice(
                        ["ACME MEDIA LLC", "TARGETED MAIL INC", "AD PLATFORM CO"]),
                    fec_url=f"https://docquery.fec.gov/dcdev/posted/{filing_id}.fec",
                    raw_line=raw_line,
                )
            )

        session.commit()
        print("Seeded test data.")


if __name__ == "__main__":
    main()
