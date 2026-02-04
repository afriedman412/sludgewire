"""
Cloud Run Job for continuous FEC filing ingestion.

Loops until no new filings are found, then exits.
Designed to run as a Cloud Run Job triggered by Cloud Scheduler.
"""
from __future__ import annotations

import gc
import sys
import time
from datetime import datetime, timezone

from sqlmodel import Session, select

# Add parent to path for imports
sys.path.insert(0, "/app")

from app.settings import load_settings
from app.db import make_engine, init_db
from app.ingest_f3x import run_f3x
from app.ingest_ie import run_ie_schedule_e
from app.email_service import send_filing_alert
from app.repo import get_max_new_per_run, get_email_enabled
from app.schemas import FilingF3X, IEScheduleE, EmailRecipient


MAX_ITERATIONS = 50  # Safety limit to prevent infinite loops
MAX_RUNTIME_MINUTES = 55  # Leave buffer before Cloud Run's 60 min timeout
PAUSE_BETWEEN_BATCHES = 2  # Seconds to pause between batches


def log(msg: str):
    """Log with timestamp."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run_job():
    """Main job loop - process filings until caught up."""
    log("Starting FEC ingestion job")

    settings = load_settings()
    engine = make_engine(settings)
    init_db(engine)

    start_time = time.time()
    iteration = 0
    total_f3x = 0
    total_ie_filings = 0
    total_ie_events = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        elapsed_minutes = (time.time() - start_time) / 60

        # Check runtime limit
        if elapsed_minutes >= MAX_RUNTIME_MINUTES:
            log(f"Reached max runtime ({MAX_RUNTIME_MINUTES} min), stopping")
            break

        log(f"=== Iteration {iteration} (elapsed: {elapsed_minutes:.1f} min) ===")

        with Session(engine) as session:
            max_per_run = get_max_new_per_run(session)
            log(f"Max per run: {max_per_run}")

            # Run F3X ingestion
            f3x_new = 0
            try:
                f3x_new = run_f3x(
                    session,
                    feed_url=settings.f3x_feed,
                    receipts_threshold=settings.receipts_threshold,
                )
                total_f3x += f3x_new
                log(f"F3X: {f3x_new} new filings this batch")
            except Exception as e:
                log(f"F3X error: {e}")

            # Run IE ingestion
            ie_filings = 0
            ie_events = 0
            try:
                ie_filings, ie_events = run_ie_schedule_e(
                    session,
                    feed_urls=settings.ie_feeds,
                )
                total_ie_filings += ie_filings
                total_ie_events += ie_events
                log(f"IE: {ie_filings} filings, {ie_events} events this batch")
            except Exception as e:
                log(f"IE error: {e}")

            session.commit()
            gc.collect()

        # Check if we're caught up (no new filings in this batch)
        if f3x_new == 0 and ie_filings == 0:
            log("No new filings found - caught up!")
            break

        # If we got a full batch, there might be more - continue
        if f3x_new >= max_per_run or ie_filings >= max_per_run:
            log(f"Got full batch, continuing after {PAUSE_BETWEEN_BATCHES}s pause...")
            time.sleep(PAUSE_BETWEEN_BATCHES)
        else:
            # Partial batch means we're nearly done
            log("Partial batch - likely caught up")
            break

    elapsed = (time.time() - start_time) / 60
    log(f"Job complete in {elapsed:.1f} min over {iteration} iterations")
    log(f"Totals: F3X={total_f3x}, IE filings={total_ie_filings}, IE events={total_ie_events}")

    # Send email if we found new high-value filings
    if total_f3x > 0 or total_ie_events > 0:
        log("Checking for email alerts...")
        try:
            with Session(engine) as session:
                # Check if emails are enabled
                if not get_email_enabled(session):
                    log("Email alerts disabled in config, skipping")
                    return 0

                # Check if there are active recipients
                active_recipients = session.exec(
                    select(EmailRecipient).where(EmailRecipient.active == True)
                ).all()

                if not active_recipients:
                    log("No active email recipients, skipping email")
                else:
                    # Get today's high-value F3X filings
                    today_start = datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                    if total_f3x > 0:
                        stmt = (
                            select(FilingF3X)
                            .where(FilingF3X.filed_at_utc >= today_start)
                            .where(FilingF3X.total_receipts >= settings.receipts_threshold)
                            .where(FilingF3X.emailed_at == None)
                            .order_by(FilingF3X.filed_at_utc.desc())
                            .limit(50)
                        )
                        f3x_filings = session.exec(stmt).all()
                        if f3x_filings:
                            filings_data = [{
                                "committee_name": f.committee_name,
                                "committee_id": f.committee_id,
                                "form_type": f.form_type,
                                "report_type": f.report_type,
                                "coverage_from": str(f.coverage_from) if f.coverage_from else None,
                                "coverage_through": str(f.coverage_through) if f.coverage_through else None,
                                "filed_at_utc": str(f.filed_at_utc)[:16] if f.filed_at_utc else None,
                                "total_receipts": f.total_receipts,
                                "fec_url": f.fec_url,
                            } for f in f3x_filings]
                            send_filing_alert(session, "3x", filings_data)
                            # Mark as emailed
                            now = datetime.now(timezone.utc)
                            for f in f3x_filings:
                                f.emailed_at = now
                                session.add(f)
                            session.commit()
                            log(f"Sent F3X alert for {len(f3x_filings)} filings")

                    if total_ie_events > 0:
                        stmt = (
                            select(IEScheduleE)
                            .where(IEScheduleE.filed_at_utc >= today_start)
                            .where(IEScheduleE.emailed_at == None)
                            .order_by(IEScheduleE.filed_at_utc.desc())
                            .limit(50)
                        )
                        ie_events_list = session.exec(stmt).all()
                        if ie_events_list:
                            events_data = [{
                                "committee_name": e.committee_name,
                                "committee_id": e.committee_id,
                                "candidate_name": e.candidate_name,
                                "candidate_id": e.candidate_id,
                                "candidate_office": e.candidate_office,
                                "candidate_state": e.candidate_state,
                                "candidate_district": e.candidate_district,
                                "support_oppose": e.support_oppose,
                                "purpose": e.purpose,
                                "payee_name": e.payee_name,
                                "expenditure_date": str(e.expenditure_date) if e.expenditure_date else None,
                                "amount": e.amount,
                                "fec_url": e.fec_url,
                            } for e in ie_events_list]
                            send_filing_alert(session, "e", events_data)
                            # Mark as emailed
                            now = datetime.now(timezone.utc)
                            for e in ie_events_list:
                                e.emailed_at = now
                                session.add(e)
                            session.commit()
                            log(f"Sent IE alert for {len(ie_events_list)} events")

        except Exception as e:
            log(f"Email error (non-fatal): {e}")

    log("Job finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(run_job())
