from __future__ import annotations

import gc
from sqlmodel import Session

from .feeds import fetch_rss_items, infer_filing_id, parse_mmddyyyy
from .fec_lookup import resolve_committee_name
from .fec_parse import download_fec_text, parse_fec_filing, extract_committee_name
from .repo import claim_filing, upsert_f3x


def run_f3x(session: Session, *, feed_url: str, receipts_threshold: float) -> int:
    items = fetch_rss_items(feed_url)
    new_count = 0

    for item in items:
        filing_id = infer_filing_id(item)
        if filing_id is None:
            continue

        if not claim_filing(session, filing_id, source_feed="F3X"):
            continue

        fec_text = download_fec_text(item.link)
        parsed = parse_fec_filing(fec_text)
        total = parsed.get("filing", {}).get("col_a_total_receipts")
        if total not in (None, ""):
            try:
                total = float(total)
            except (TypeError, ValueError):
                total = None
        else:
            total = None
        threshold_flag = (total is not None and total >= receipts_threshold)

        meta = item.meta
        committee_id = meta.get("CommitteeId") or ""

        # Get committee name from DB, or insert provisional from filing
        form_name = extract_committee_name(parsed)
        committee_name = resolve_committee_name(session, committee_id, fallback_name=form_name)
        upsert_f3x(
            session,
            filing_id=filing_id,
            committee_id=committee_id,
            committee_name=committee_name,
            form_type=meta.get("FormType"),
            report_type=meta.get("ReportType"),
            coverage_from=parse_mmddyyyy(meta.get("CoverageFrom")),
            coverage_through=parse_mmddyyyy(meta.get("CoverageThrough")),
            filed_at_utc=item.pub_date_utc,
            fec_url=item.link,
            total_receipts=total,
            threshold_flag=threshold_flag,
            raw_meta=meta,
        )

        # Explicit cleanup to free memory
        del fec_text
        del parsed
        gc.collect()

        new_count += 1

    return new_count
