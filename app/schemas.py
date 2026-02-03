# app/schemas.py
from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Dict, Any

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Text
from sqlalchemy.dialects.postgresql import JSONB


class Committee(SQLModel, table=True):
    __tablename__ = "committees"

    committee_id: str = Field(primary_key=True, index=True)
    committee_name: str = Field(index=True)

    committee_type: Optional[str] = Field(default=None, index=True)   # CMTE_TP
    designation: Optional[str] = Field(
        default=None, index=True)      # CMTE_DSGN
    filing_freq: Optional[str] = Field(
        default=None, index=True)      # CMTE_FILING_FREQ

    # CMTE_CITY
    city: Optional[str] = None
    state: Optional[str] = Field(default=None, index=True)            # CMTE_ST

    treasurer_name: Optional[str] = None                              # TRES_NM
    candidate_id: Optional[str] = Field(default=None, index=True)     # CAND_ID

    raw_meta: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB)
    )

    # True if added from filing form (not from official FEC CSV)
    provisional: bool = Field(default=False)

    updated_at_utc: datetime = Field(
        default_factory=datetime.utcnow, index=True)


class SeenFiling(SQLModel, table=True):
    __tablename__ = "seen_filings"

    filing_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    source_feed: Optional[str] = Field(default=None)
    first_seen_utc: datetime = Field(default_factory=datetime.utcnow)


class FilingF3X(SQLModel, table=True):
    __tablename__ = "filings_f3x"

    filing_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    committee_id: str = Field(index=True)
    committee_name: Optional[str] = Field(default=None, index=True)
    form_type: Optional[str] = None
    report_type: Optional[str] = None

    coverage_from: Optional[date] = None
    coverage_through: Optional[date] = None
    filed_at_utc: Optional[datetime] = Field(default=None, index=True)

    fec_url: str = Field(sa_column=Column(Text, nullable=False))

    total_receipts: Optional[float] = None
    threshold_flag: bool = Field(default=False, index=True)

    raw_meta: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB))

    first_seen_utc: datetime = Field(default_factory=datetime.utcnow)
    updated_at_utc: datetime = Field(default_factory=datetime.utcnow)


class IEScheduleE(SQLModel, table=True):
    __tablename__ = "ie_schedule_e"

    event_id: str = Field(primary_key=True)

    filing_id: int = Field(sa_column=Column(
        BigInteger, index=True, nullable=False))
    filer_id: Optional[str] = Field(default=None, index=True)
    committee_id: Optional[str] = Field(default=None, index=True)
    committee_name: Optional[str] = Field(default=None)
    form_type: Optional[str] = None
    report_type: Optional[str] = None

    coverage_from: Optional[date] = None
    coverage_through: Optional[date] = None
    filed_at_utc: Optional[datetime] = Field(default=None, index=True)

    expenditure_date: Optional[date] = Field(default=None, index=True)
    amount: Optional[float] = Field(default=None, index=True)
    support_oppose: Optional[str] = None

    candidate_id: Optional[str] = Field(default=None, index=True)
    candidate_name: Optional[str] = None
    candidate_office: Optional[str] = None
    candidate_state: Optional[str] = None
    candidate_district: Optional[str] = None

    election_code: Optional[str] = None
    purpose: Optional[str] = None
    payee_name: Optional[str] = None

    fec_url: Optional[str] = None
    raw_line: str = Field(sa_column=Column(Text, nullable=False))

    first_seen_utc: datetime = Field(default_factory=datetime.utcnow)


class EmailRecipient(SQLModel, table=True):
    __tablename__ = "email_recipients"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BackfillJob(SQLModel, table=True):
    __tablename__ = "backfill_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    target_date: date = Field(index=True)
    filing_type: str = Field(index=True)  # "3x" or "e"
    status: str = Field(default="pending", index=True)  # pending, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    filings_found: int = Field(default=0)
    error_message: Optional[str] = None


class AppConfig(SQLModel, table=True):
    __tablename__ = "app_config"

    key: str = Field(primary_key=True)
    value: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
