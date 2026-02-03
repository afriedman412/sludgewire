from __future__ import annotations

from sqlmodel import Session

from .feeds import fetch_rss_items, infer_filing_id, parse_mmddyyyy
from .fec_lookup import resolve_committee_name
from .fec_parse import download_fec_text, parse_fec_filing, extract_committee_name, extract_schedule_e_best_effort, sha256_hex
from .repo import claim_filing, insert_ie_event
from .schemas import IEScheduleE


def run_ie_schedule_e(session: Session, *, feed_urls: list[str]) -> tuple[int, int]:
    new_filings = 0
    new_events = 0

    for feed_url in feed_urls:
        items = fetch_rss_items(feed_url)
        for item in items:
            filing_id = infer_filing_id(item)
            if filing_id is None:
                continue

            if not claim_filing(session, filing_id, source_feed=feed_url):
                continue

            fec_text = download_fec_text(item.link)
            parsed = parse_fec_filing(fec_text)

            meta = item.meta
            coverage_from = parse_mmddyyyy(meta.get("CoverageFrom"))
            coverage_through = parse_mmddyyyy(meta.get("CoverageThrough"))
            committee_id = meta.get("CommitteeId") or ""

            # Get committee name from DB, or insert provisional from filing
            form_name = extract_committee_name(parsed)
            committee_name = resolve_committee_name(session, committee_id, fallback_name=form_name)

            for raw_line, fields in extract_schedule_e_best_effort(fec_text):
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
                    election_code=fields["election_code"],
                    purpose=fields["purpose"],
                    payee_name=fields["payee_name"],
                    fec_url=item.link,
                    raw_line=raw_line,
                )

                if insert_ie_event(session, event):
                    new_events += 1

            new_filings += 1

    return new_filings, new_events
