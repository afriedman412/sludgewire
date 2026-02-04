from __future__ import annotations

import gc
from sqlmodel import Session

from .feeds import fetch_rss_items, infer_filing_id, parse_mmddyyyy
from .fec_lookup import resolve_committee_name
from .fec_parse import download_fec_text, parse_fec_filing, extract_committee_name
from .repo import claim_filing, upsert_f3x


def _log_mem(label: str):
    """Quick memory log."""
    try:
        import resource
        import platform
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if platform.system() == "Darwin":
            mb = usage / (1024 * 1024)
        else:
            mb = usage / 1024
        print(f"[F3X-MEM] {label}: {mb:.1f} MB")
    except Exception:
        pass


def run_f3x(session: Session, *, feed_url: str, receipts_threshold: float) -> int:
    items = fetch_rss_items(feed_url)
    print(f"[F3X] RSS feed has {len(items)} items")
    _log_mem("after_fetch_rss")
    new_count = 0
    skipped = 0

    for i, item in enumerate(items):
        filing_id = infer_filing_id(item)
        if filing_id is None:
            continue

        if not claim_filing(session, filing_id, source_feed="F3X"):
            skipped += 1
            continue

        print(f"[F3X] Processing new filing {filing_id} ({new_count + 1})")
        _log_mem(f"before_download_{filing_id}")

        fec_text = download_fec_text(item.link)
        _log_mem(f"after_download_{filing_id}")

        parsed = parse_fec_filing(fec_text)
        _log_mem(f"after_parse_{filing_id}")
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
        _log_mem(f"after_gc_{filing_id}")

        new_count += 1

    print(f"[F3X] Done: {new_count} new, {skipped} skipped")
    _log_mem("end")
    return new_count
