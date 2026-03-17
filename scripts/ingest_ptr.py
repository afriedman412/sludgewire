"""
Ingest House Periodic Transaction Reports (PTRs).

1. Downloads the bulk FD ZIP index from the House Clerk
2. Inserts new PTR filings into ptr_filings (status=pending)
3. For each pending filing, downloads the PDF and parses with petey
4. Inserts parsed transactions into ptr_transactions

Usage:
    python -m scripts.ingest_ptr                # ingest current year
    python -m scripts.ingest_ptr --year 2025    # ingest specific year
    python -m scripts.ingest_ptr --parse-only   # skip index, just parse pending
"""
from __future__ import annotations

import argparse
import csv
import gc
import io
import os
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from typing import Optional

import requests
from pydantic import BaseModel
from sqlmodel import Session, select, col

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.settings import load_settings
from app.db import make_engine, init_db
from app.schemas import PtrFiling, PtrTransaction

# --- Config ---

ZIP_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"

PETEY_MODEL = os.environ.get("PETEY_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

MAX_PARSE_PER_RUN = 50  # limit PDF parses per invocation


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# --- Petey schema for extraction ---

class PtrTransactionExtract(BaseModel):
    owner: Optional[str] = None
    asset: str
    ticker: Optional[str] = None
    asset_type: Optional[str] = None
    transaction_type: Optional[str] = None
    transaction_date: Optional[str] = None
    notification_date: Optional[str] = None
    amount: Optional[str] = None
    cap_gains_over_200: Optional[bool] = None
    description: Optional[str] = None
    subholding_of: Optional[str] = None
    filing_status: Optional[str] = None


class PtrExtract(BaseModel):
    transactions: list[PtrTransactionExtract]


PETEY_INSTRUCTIONS = (
    "Extract all transactions from the TRANSACTIONS table. "
    "For ticker, extract the parenthesized ticker symbol if present (e.g. 'NFLX' from 'Netflix, Inc. - Common Stock (NFLX) [ST]'). "
    "For asset_type, extract the bracketed code (e.g. 'ST' from '[ST]'). "
    "For transaction_type: P=Purchase, S=Sale, E=Exchange. "
    "For amount, keep the range string as-is (e.g. '$1,001 - $15,000'). "
    "For dates, use MM/DD/YYYY format as shown in the document. "
    "For filing_status, look for 'Filing Status:' lines (e.g. 'New'). "
    "For subholding_of, look for 'Subholding Of:' lines. "
    "For description, look for 'Description:' lines."
)


# --- Step 1: Fetch and sync the filing index ---

def fetch_filing_index(year: int) -> list[dict]:
    """Download the FD ZIP and parse the TSV into a list of dicts."""
    url = ZIP_URL.format(year=year)
    log(f"Downloading {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        txt_name = f"{year}FD.txt"
        with zf.open(txt_name) as f:
            text = f.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows = list(reader)
    log(f"Got {len(rows)} total filings from index")
    return rows


def sync_filing_index(session: Session, rows: list[dict], year: int) -> int:
    """Insert new PTR filings from the index. Returns count of new rows."""
    existing = set(
        r[0] for r in session.exec(
            select(PtrFiling.doc_id).where(PtrFiling.filing_year == year)
        ).all()
    )

    new_count = 0
    for row in rows:
        filing_type = row.get("FilingType", "")
        if filing_type != "P":
            continue

        doc_id = row.get("DocID", "").strip()
        if not doc_id or doc_id in existing:
            continue

        filing_date = None
        raw_date = row.get("FilingDate", "")
        if raw_date:
            try:
                filing_date = datetime.strptime(raw_date, "%m/%d/%Y").date()
            except ValueError:
                pass

        filing = PtrFiling(
            doc_id=doc_id,
            first_name=row.get("First", "").strip(),
            last_name=row.get("Last", "").strip(),
            prefix=row.get("Prefix", "").strip() or None,
            suffix=row.get("Suffix", "").strip() or None,
            state_district=row.get("StateDst", "").strip() or None,
            filing_year=year,
            filing_date=filing_date,
            filing_type=filing_type,
            pdf_url=PDF_URL.format(year=year, doc_id=doc_id),
        )
        session.add(filing)
        existing.add(doc_id)
        new_count += 1

    session.commit()
    log(f"Inserted {new_count} new PTR filings")
    return new_count


# --- Step 2: Parse pending filings ---

def parse_filing(pdf_path: str) -> PtrExtract:
    """Use petey to extract transactions from a PTR PDF."""
    import asyncio
    import fitz
    from petey.extract import extract_pages_async, extract_async

    n_pages = len(fitz.open(pdf_path))

    if n_pages <= 2:
        # Small filing — single call, no header split
        result = asyncio.run(extract_async(
            pdf_path,
            PtrExtract,
            model=PETEY_MODEL,
            parser="tables",
            instructions=PETEY_INSTRUCTIONS,
        ))
        return result

    # Multi-page: page 1 = header context, rest = content pages
    results = asyncio.run(extract_pages_async(
        pdf_path,
        PtrExtract,
        model=PETEY_MODEL,
        parser="tables",
        header_pages=1,
        instructions=PETEY_INSTRUCTIONS,
    ))


    # Flatten page results into a single PtrExtract
    all_txns = []
    for page_result in results:
        if "_error" in page_result:
            continue
        for txn_dict in page_result.get("transactions", []):
            all_txns.append(PtrTransactionExtract(**txn_dict))
    return PtrExtract(transactions=all_txns)


def process_pending(session: Session, year: int, max_count: int = MAX_PARSE_PER_RUN) -> int:
    """Download and parse pending PTR filings. Returns count processed."""
    pending = session.exec(
        select(PtrFiling)
        .where(PtrFiling.status == "pending")
        .where(PtrFiling.filing_year == year)
        .order_by(col(PtrFiling.filing_date).desc())
        .limit(max_count)
    ).all()

    if not pending:
        log("No pending filings to process")
        return 0

    log(f"Processing {len(pending)} pending filings")
    processed = 0

    from tqdm import tqdm
    for filing in tqdm(pending, desc="Parsing PTRs"):
        try:
            # Download PDF
            filing.status = "downloading"
            filing.updated_at = datetime.now(timezone.utc)
            session.add(filing)
            session.commit()

            pdf_url = filing.pdf_url or PDF_URL.format(
                year=year, doc_id=filing.doc_id
            )
            resp = requests.get(pdf_url, timeout=30)
            resp.raise_for_status()

            # Write to temp file for petey
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            try:
                # Parse
                filing.status = "parsing"
                filing.updated_at = datetime.now(timezone.utc)
                session.add(filing)
                session.commit()

                result = parse_filing(tmp_path)
                filer_name = " ".join(
                    p for p in [filing.prefix, filing.first_name, filing.last_name, filing.suffix]
                    if p
                )

                for txn in result.transactions:
                    txn_date = None
                    if txn.transaction_date:
                        try:
                            txn_date = datetime.strptime(
                                txn.transaction_date, "%m/%d/%Y"
                            ).date()
                        except ValueError:
                            pass

                    notif_date = None
                    if txn.notification_date:
                        try:
                            notif_date = datetime.strptime(
                                txn.notification_date, "%m/%d/%Y"
                            ).date()
                        except ValueError:
                            pass

                    ptr_txn = PtrTransaction(
                        doc_id=filing.doc_id,
                        filer_name=filer_name,
                        state_district=filing.state_district,
                        owner=txn.owner,
                        asset=txn.asset,
                        ticker=txn.ticker,
                        asset_type=txn.asset_type,
                        transaction_type=txn.transaction_type,
                        transaction_date=txn_date,
                        notification_date=notif_date,
                        amount=txn.amount,
                        cap_gains_over_200=txn.cap_gains_over_200,
                        description=txn.description,
                        subholding_of=txn.subholding_of,
                        filing_status=txn.filing_status,
                    )
                    session.add(ptr_txn)

                filing.status = "ingested"
                filing.updated_at = datetime.now(timezone.utc)
                session.add(filing)
                session.commit()
                processed += 1
                log(f"  {filing.doc_id} ({filer_name}): {len(result.transactions)} transactions")

            finally:
                os.unlink(tmp_path)

        except Exception as e:
            session.rollback()
            filing.status = "failed"
            filing.error_message = str(e)[:500]
            filing.updated_at = datetime.now(timezone.utc)
            session.add(filing)
            session.commit()
            log(f"  {filing.doc_id}: FAILED - {e}")

        gc.collect()

    log(f"Processed {processed}/{len(pending)} filings")
    return processed


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Ingest House PTR filings")
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--parse-only", action="store_true",
                        help="Skip index sync, just parse pending filings")
    parser.add_argument("--max", type=int, default=MAX_PARSE_PER_RUN,
                        help="Max filings to parse per run")
    args = parser.parse_args()

    settings = load_settings()
    engine = make_engine(settings)
    init_db(engine)

    with Session(engine) as session:
        if not args.parse_only:
            rows = fetch_filing_index(args.year)
            sync_filing_index(session, rows, args.year)

        process_pending(session, args.year, args.max)


if __name__ == "__main__":
    main()
