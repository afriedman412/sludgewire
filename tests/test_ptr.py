"""Tests for House PTR ingestion and email alerts."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session

from app.schemas import (
    PtrFiling, PtrTransaction, EmailRecipient, AppConfig,
)
from app.email_service import _build_ptr_alert_email, send_ptr_alert
from app.repo import get_ptr_email_enabled
from scripts.ingest_ptr import (
    PtrExtract, PtrTransactionExtract,
    sync_filing_index,
)


# -------------------------------------------------------
# Fixtures / helpers
# -------------------------------------------------------

def _add_recipient(session, email, active=True):
    r = EmailRecipient(email=email, active=active)
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


def _add_ptr_filing(session, doc_id="20033751", **kwargs):
    defaults = dict(
        first_name="Nancy",
        last_name="Pelosi",
        prefix="Hon.",
        state_district="CA11",
        filing_year=2026,
        filing_date=date(2026, 1, 15),
        filing_type="P",
        status="ingested",
        pdf_url=f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/{doc_id}.pdf",
    )
    defaults.update(kwargs)
    f = PtrFiling(doc_id=doc_id, **defaults)
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


SAMPLE_INDEX_ROWS = [
    {
        "Prefix": "Hon.", "Last": "Pelosi", "First": "Nancy", "Suffix": "",
        "FilingType": "P", "StateDst": "CA11", "Year": "2026",
        "FilingDate": "1/15/2026", "DocID": "20033751",
    },
    {
        "Prefix": "Hon.", "Last": "Allen", "First": "Richard W.", "Suffix": "",
        "FilingType": "P", "StateDst": "GA12", "Year": "2026",
        "FilingDate": "2/17/2026", "DocID": "20033945",
    },
    {
        "Prefix": "", "Last": "Smith", "First": "John", "Suffix": "",
        "FilingType": "C", "StateDst": "TX01", "Year": "2026",
        "FilingDate": "1/10/2026", "DocID": "10000001",
    },
]

SAMPLE_PTR_FILINGS_DATA = [
    {
        "filer_name": "Hon. Nancy Pelosi",
        "state_district": "CA11",
        "filing_date": "2026-01-15",
        "transaction_count": 5,
        "tickers": "AAPL, NVDA, TSLA",
        "pdf_url": "https://example.com/1.pdf",
    },
    {
        "filer_name": "Hon. Richard W. Allen",
        "state_district": "GA12",
        "filing_date": "2026-02-17",
        "transaction_count": 2,
        "tickers": "FERG, NFLX",
        "pdf_url": "https://example.com/2.pdf",
    },
]


# -------------------------------------------------------
# sync_filing_index
# -------------------------------------------------------

class TestSyncFilingIndex:
    def test_inserts_ptr_filings_only(self, session):
        count = sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        assert count == 2  # skips FilingType=C

    def test_skips_duplicates(self, session):
        sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        count = sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        assert count == 0

    def test_parses_filing_date(self, session):
        sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        f = session.get(PtrFiling, "20033751")
        assert f.filing_date == date(2026, 1, 15)

    def test_stores_filer_info(self, session):
        sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        f = session.get(PtrFiling, "20033751")
        assert f.first_name == "Nancy"
        assert f.last_name == "Pelosi"
        assert f.prefix == "Hon."
        assert f.state_district == "CA11"

    def test_sets_pdf_url(self, session):
        sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        f = session.get(PtrFiling, "20033751")
        assert "20033751.pdf" in f.pdf_url

    def test_status_defaults_to_pending(self, session):
        sync_filing_index(session, SAMPLE_INDEX_ROWS, 2026)
        f = session.get(PtrFiling, "20033751")
        assert f.status == "pending"


# -------------------------------------------------------
# get_ptr_email_enabled
# -------------------------------------------------------

class TestGetPtrEmailEnabled:
    def test_default_is_false(self, session):
        assert get_ptr_email_enabled(session) is False

    def test_returns_true_when_set(self, session):
        session.add(AppConfig(key="ptr_email_enabled", value="true"))
        session.commit()
        assert get_ptr_email_enabled(session) is True

    def test_returns_false_when_disabled(self, session):
        session.add(AppConfig(key="ptr_email_enabled", value="false"))
        session.commit()
        assert get_ptr_email_enabled(session) is False


# -------------------------------------------------------
# _build_ptr_alert_email
# -------------------------------------------------------

class TestBuildPtrAlertEmail:
    def test_subject_includes_count(self):
        subject, _ = _build_ptr_alert_email(SAMPLE_PTR_FILINGS_DATA)
        assert "2" in subject
        assert "PTR" in subject

    def test_body_includes_filer_names(self):
        _, body = _build_ptr_alert_email(SAMPLE_PTR_FILINGS_DATA)
        assert "Pelosi" in body
        assert "Allen" in body

    def test_body_includes_tickers(self):
        _, body = _build_ptr_alert_email(SAMPLE_PTR_FILINGS_DATA)
        assert "NVDA" in body
        assert "FERG" in body

    def test_body_includes_transaction_count(self):
        _, body = _build_ptr_alert_email(SAMPLE_PTR_FILINGS_DATA)
        assert ">5<" in body  # in a <td>

    def test_empty_filings(self):
        subject, body = _build_ptr_alert_email([])
        assert "0" in subject


# -------------------------------------------------------
# send_ptr_alert
# -------------------------------------------------------

class TestSendPtrAlert:
    @patch("app.email_service.send_email", return_value=True)
    def test_sends_to_all_recipients(self, mock_send, session):
        _add_recipient(session, "a@test.com")
        _add_recipient(session, "b@test.com")

        result = send_ptr_alert(session, SAMPLE_PTR_FILINGS_DATA)

        assert mock_send.call_count == 2
        assert result["a@test.com"] == 2
        assert result["b@test.com"] == 2

    @patch("app.email_service.send_email", return_value=True)
    def test_inactive_excluded(self, mock_send, session):
        _add_recipient(session, "active@test.com", active=True)
        _add_recipient(session, "inactive@test.com", active=False)

        result = send_ptr_alert(session, SAMPLE_PTR_FILINGS_DATA)

        assert mock_send.call_count == 1
        assert "active@test.com" in result
        assert "inactive@test.com" not in result

    def test_no_recipients_returns_empty(self, session):
        result = send_ptr_alert(session, SAMPLE_PTR_FILINGS_DATA)
        assert result == {}

    def test_empty_filings_returns_empty(self, session):
        _add_recipient(session, "a@test.com")
        result = send_ptr_alert(session, [])
        assert result == {}

    @patch("app.email_service.send_email", return_value=False)
    def test_smtp_failure_excluded(self, mock_send, session):
        _add_recipient(session, "a@test.com")
        result = send_ptr_alert(session, SAMPLE_PTR_FILINGS_DATA)
        assert result == {}


# -------------------------------------------------------
# PtrExtract / PtrTransactionExtract models
# -------------------------------------------------------

class TestPtrExtractModels:
    def test_transaction_extract_minimal(self):
        t = PtrTransactionExtract(asset="AAPL Stock")
        assert t.asset == "AAPL Stock"
        assert t.ticker is None
        assert t.transaction_type is None

    def test_extract_with_transactions(self):
        e = PtrExtract(transactions=[
            PtrTransactionExtract(
                owner="SP", asset="Apple Inc (AAPL) [ST]",
                ticker="AAPL", transaction_type="P",
                amount="$1,001 - $15,000",
            ),
        ])
        assert len(e.transactions) == 1
        assert e.transactions[0].ticker == "AAPL"
