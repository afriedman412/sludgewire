from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import select
from sqlmodel import Session

from .schemas import SeenFiling, FilingF3X, IEScheduleE, AppConfig, SkippedFiling


# Default values for configurable settings
DEFAULT_MAX_NEW_PER_RUN = 50


def get_config_int(session: Session, key: str, default: int) -> int:
    """Get an integer config value from AppConfig table."""
    config = session.get(AppConfig, key)
    if config and config.value:
        try:
            return int(config.value)
        except (ValueError, TypeError):
            pass
    return default


def get_max_new_per_run(session: Session) -> int:
    """Get the max filings to process per run from config."""
    return get_config_int(session, "max_new_per_run", DEFAULT_MAX_NEW_PER_RUN)


def get_email_enabled(session: Session) -> bool:
    """Check if email alerts are enabled."""
    config = session.get(AppConfig, "email_enabled")
    if config and config.value:
        return config.value.lower() in ("true", "1", "yes")
    return True  # Default to enabled


def record_skipped_filing(
    session: Session,
    filing_id: int,
    reason: str,
    file_size_mb: float = None,
    fec_url: str = None,
) -> None:
    """Record a filing that was skipped due to size or other issues."""
    existing = session.get(SkippedFiling, filing_id)
    if existing:
        return  # Already recorded

    skipped = SkippedFiling(
        filing_id=filing_id,
        reason=reason,
        file_size_mb=file_size_mb,
        fec_url=fec_url,
    )
    session.add(skipped)
    session.flush()


def claim_filing(session: Session, filing_id: int, source_feed: str) -> bool:
    """
    Returns True if we successfully claimed this filing_id (first time seen).
    """
    existing = session.get(SeenFiling, filing_id)
    if existing:
        return False

    session.add(SeenFiling(filing_id=filing_id, source_feed=source_feed))
    # flush to surface unique/PK issues immediately
    session.flush()
    return True


def upsert_f3x(
    session: Session,
    *,
    filing_id: int,
    committee_id: str,
    committee_name: Optional[str] = None,
    form_type: Optional[str],
    report_type: Optional[str],
    coverage_from,
    coverage_through,
    filed_at_utc,
    fec_url: str,
    total_receipts: Optional[float],
    threshold_flag: bool,
    raw_meta: Optional[Dict[str, Any]],
) -> None:
    row = session.get(FilingF3X, filing_id)
    now = datetime.now(timezone.utc)

    if row is None:
        session.add(
            FilingF3X(
                filing_id=filing_id,
                committee_id=committee_id,
                committee_name=committee_name,
                form_type=form_type,
                report_type=report_type,
                coverage_from=coverage_from,
                coverage_through=coverage_through,
                filed_at_utc=filed_at_utc,
                fec_url=fec_url,
                total_receipts=total_receipts,
                threshold_flag=threshold_flag,
                raw_meta=raw_meta,
                updated_at_utc=now,
            )
        )
    else:
        row.committee_id = committee_id
        row.committee_name = committee_name
        row.form_type = form_type
        row.report_type = report_type
        row.coverage_from = coverage_from
        row.coverage_through = coverage_through
        row.filed_at_utc = filed_at_utc
        row.fec_url = fec_url
        row.total_receipts = total_receipts
        row.threshold_flag = threshold_flag
        if raw_meta is not None:
            row.raw_meta = raw_meta
        row.updated_at_utc = now
        session.add(row)

    session.flush()


def insert_ie_event(session: Session, event: IEScheduleE) -> bool:
    """
    Insert-only dedupe by primary key event_id.
    Returns True if inserted, False if already existed.
    """
    existing = session.get(IEScheduleE, event.event_id)
    if existing:
        return False
    session.add(event)
    session.flush()
    return True
