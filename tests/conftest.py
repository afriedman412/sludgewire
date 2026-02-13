"""Shared fixtures for FEC Monitor tests.

Uses testcontainers to spin up a real Postgres instance so tests run
against the same DB engine as production (JSONB, savepoints, etc.).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import SQLModel, Session, create_engine
from testcontainers.postgres import PostgresContainer

from app.schemas import (
    IngestionTask, FilingF3X, IEScheduleE, EmailRecipient, AppConfig,
)
from app.feeds import RSSItem


# Session-scoped: one Postgres container for the entire test run
@pytest.fixture(scope="session")
def pg_container():
    """Start a Postgres container once for the whole test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_engine(pg_container):
    """Create engine connected to the test Postgres container."""
    url = pg_container.get_connection_url()
    eng = create_engine(url, echo=False)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def engine(pg_engine):
    """Per-test engine. Truncates all tables before each test for isolation."""
    # Clean all tables before each test
    with Session(pg_engine) as s:
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.execute(table.delete())
        s.commit()
    return pg_engine


@pytest.fixture
def session(engine):
    """Fresh database session per test."""
    with Session(engine) as s:
        yield s


def make_rss_item(
    filing_id: int = 12345,
    committee_id: str = "C00000001",
    form_type: str = "F3XN",
    pub_date: datetime | None = None,
    link: str | None = None,
) -> RSSItem:
    """Helper to build a fake RSS item."""
    if pub_date is None:
        pub_date = datetime.now(timezone.utc)
    if link is None:
        link = f"https://docquery.fec.gov/dcdev/posted/{filing_id}.fec"
    return RSSItem(
        title=f"Filing {filing_id}",
        link=link,
        description=f"*****CommitteeId: {committee_id} | FilingId: {filing_id} | FormType: {form_type}*****",
        pub_date_utc=pub_date,
        meta={
            "CommitteeId": committee_id,
            "FilingId": str(filing_id),
            "FormType": form_type,
        },
    )
