"""Backfill Schedule A data for all target PAC F3X filings.

Runs run_sa() in a loop until no more unprocessed filings remain.
Designed to be run locally once to catch up on historical data.
"""
from __future__ import annotations

import time

from sqlmodel import Session

from app.db import make_engine, init_db
from app.settings import load_settings
from app.ingest_sa import run_sa


def main():
    settings = load_settings()
    engine = make_engine(settings)
    init_db(engine)

    total_filings = 0
    total_events = 0
    iteration = 0

    while True:
        iteration += 1
        print(f"\n=== SA Backfill iteration {iteration} ===")

        with Session(engine) as session:
            result = run_sa(session)
            session.commit()

        total_filings += result.filings_processed
        total_events += result.events_inserted

        print(f"  This batch: {result.filings_processed} filings, "
              f"{result.events_inserted} events")
        print(f"  Running total: {total_filings} filings, {total_events} events")

        if result.filings_processed == 0:
            print("\nAll caught up — no more unprocessed filings.")
            break

        # Brief pause between batches
        time.sleep(1)

    print(f"\nDone: {total_filings} filings processed, "
          f"{total_events} SA events inserted across {iteration} iterations")


if __name__ == "__main__":
    main()
