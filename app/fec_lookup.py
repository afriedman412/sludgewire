from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from .schemas import Committee


def resolve_committee_name(
    session: Session,
    committee_id: str,
    fallback_name: Optional[str] = None,
) -> Optional[str]:
    """
    Look up committee name from local DB. If not found and fallback_name
    is provided, insert a provisional record.

    Args:
        session: DB session
        committee_id: FEC committee ID (e.g. C00123456)
        fallback_name: Name from the filing form to use if not in DB

    Returns:
        Committee name or None
    """
    if not committee_id:
        return None

    # Check local DB first
    stmt = select(Committee).where(Committee.committee_id == committee_id)
    row = session.exec(stmt).first()

    if row:
        return row.committee_name

    # Not in DB - insert provisional if we have a fallback name
    if fallback_name:
        new_comm = Committee(
            committee_id=committee_id,
            committee_name=fallback_name,
            provisional=True,
            updated_at_utc=datetime.utcnow(),
        )
        session.add(new_comm)
        session.flush()  # Make it available for later queries in same transaction
        return fallback_name

    return None
