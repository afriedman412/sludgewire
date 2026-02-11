from __future__ import annotations

import gc
from datetime import datetime, timezone
from sqlmodel import Session

from .feeds import fetch_rss_items, infer_filing_id, parse_mmddyyyy
from .fec_lookup import resolve_committee_name
from .fec_parse import download_fec_text, parse_fec_filing, extract_committee_name, extract_schedule_e_best_effort, sha256_hex, FileTooLargeError
from .repo import claim_filing, update_filing_status, insert_ie_event, get_max_new_per_run, record_skipped_filing
from .schemas import IEScheduleE

MAX_FILE_SIZE_MB = 50  # Skip files larger than this


def run_ie_schedule_e(session: Session, *, feed_urls: list[str]) -> tuple[int, int]:
    max_per_run = get_max_new_per_run(session)
    new_filings = 0
    new_events = 0
    today = datetime.now(timezone.utc).date()

    for feed_url in feed_urls:
        items = fetch_rss_items(feed_url)
        print(f"[IE] RSS feed {feed_url} has {len(items)} items (max {max_per_run} per run)")
        for item in items:
            # Stop when we hit filings from before today (feed is newest-first)
            if item.pub_date_utc and item.pub_date_utc.date() < today:
                print(f"[IE] Reached filings from {item.pub_date_utc.date()}, stopping")
                break

            # Stop if we've processed enough new filings this run
            if new_filings >= max_per_run:
                print(
                    f"[IE] Reached limit of {max_per_run} new filings, stopping")
                break
            filing_id = infer_filing_id(item)
            if filing_id is None:
                continue

            if not claim_filing(session, filing_id, source_feed=feed_url):
                continue

            try:
                fec_text = download_fec_text(item.link, max_size_mb=MAX_FILE_SIZE_MB)
            except FileTooLargeError as e:
                print(f"[IE] Skipping {filing_id}: {e.size_mb:.1f}MB exceeds limit")
                record_skipped_filing(
                    session, filing_id, "too_large",
                    file_size_mb=e.size_mb, fec_url=item.link
                )
                update_filing_status(
                    session, filing_id, feed_url, "skipped")
                continue

            try:
                parsed = parse_fec_filing(fec_text)

                meta = item.meta
                coverage_from = parse_mmddyyyy(meta.get("CoverageFrom"))
                coverage_through = parse_mmddyyyy(meta.get("CoverageThrough"))
                committee_id = meta.get("CommitteeId") or ""

                # Get committee name from DB, or insert provisional from filing
                form_name = extract_committee_name(parsed)
                committee_name = resolve_committee_name(
                    session, committee_id, fallback_name=form_name)

                # Pass pre-parsed dict to avoid double-parsing
                for raw_line, fields in extract_schedule_e_best_effort(fec_text, parsed=parsed):
                    # Stable event id within a filing based on raw line
                    event_id = sha256_hex(f"{filing_id}|{raw_line}")

                    event = IEScheduleE(
                        event_id=event_id,
                        filing_id=filing_id,
                        filer_id=committee_id,
                        committee_id=committee_id,
                        committee_name=committee_name,
                        form_type=meta.get("FormType"),
                        report_type=meta.get("ReportType"),
                        coverage_from=coverage_from,
                        coverage_through=coverage_through,
                        filed_at_utc=item.pub_date_utc,
                        expenditure_date=fields["expenditure_date"],
                        amount=fields["amount"],
                        support_oppose=fields["support_oppose"],
                        candidate_id=fields["candidate_id"],
                        candidate_name=fields["candidate_name"],
                        candidate_office=fields["candidate_office"],
                        candidate_state=fields["candidate_state"],
                        candidate_district=fields["candidate_district"],
                        candidate_party=fields["candidate_party"],
                        election_code=fields["election_code"],
                        purpose=fields["purpose"],
                        payee_name=fields["payee_name"],
                        fec_url=item.link,
                        raw_line=raw_line[:200],  # Truncate to save memory
                    )

                    if insert_ie_event(session, event):
                        new_events += 1

                update_filing_status(
                    session, filing_id, feed_url, "ingested")
            except Exception as e:
                print(f"[IE] Failed to process {filing_id}: {e}")
                update_filing_status(
                    session, filing_id, feed_url, "failed")
                continue

            # Explicit cleanup to free memory
            del fec_text
            del parsed
            gc.collect()

            new_filings += 1

        # Break outer loop too if limit reached
        if new_filings >= max_per_run:
            break

    return new_filings, new_events
