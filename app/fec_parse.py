from __future__ import annotations

import csv
import io
import re
import hashlib
from datetime import date, datetime
from typing import Iterable, Optional, Tuple, List

import requests
import fecfile


def download_fec_text(fec_url: str) -> str:
    r = requests.get(fec_url, timeout=60)
    r.raise_for_status()
    return r.text


def parse_fec_filing(fec_text: str) -> dict:
    """Parse FEC filing text and return the parsed dict."""
    return fecfile.loads(fec_text)


def f3x_total_receipts(fec_text: str) -> Optional[float]:
    parsed = fecfile.loads(fec_text)
    val = parsed.get("filing", {}).get("col_a_total_receipts")
    if val in (None, ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def extract_committee_name(parsed: dict) -> Optional[str]:
    """
    Extract committee name from parsed FEC filing.
    Checks common field locations in fecfile parsed output.
    """
    filing = parsed.get("filing", {})

    # Try common field names for committee name
    for key in ("committee_name", "filer_committee_id_name", "filer_name"):
        val = filing.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    return None


def iter_pipe_rows(fec_text: str) -> Iterable[List[str]]:
    f = io.StringIO(fec_text)
    reader = csv.reader(f, delimiter="|")
    for row in reader:
        if row:
            yield row


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def extract_schedule_e_best_effort(fec_text: str) -> Iterable[Tuple[str, dict]]:
    """
    Yields (raw_line, extracted_fields_dict).

    IMPORTANT: Schedule E layouts vary by form/version. We store raw_line always.
    The extracted fields here are best-effort; refine with real samples later.
    """
    for row in iter_pipe_rows(fec_text):
        rec = row[0]
        if not rec.startswith("SE"):
            continue

        raw_line = "|".join(row)

        # Heuristic extraction: amount/date/support-oppose (minimal)
        amount = None
        expenditure_date = None
        support_oppose = None

        for token in row:
            if expenditure_date is None:
                d = _parse_mmddyyyy(token)
                if d:
                    expenditure_date = d
            if amount is None:
                t = token.replace(",", "").strip()
                if re.fullmatch(r"-?\d+(\.\d+)?", t):
                    try:
                        val = float(t)
                        if abs(val) >= 1.0:
                            amount = val
                    except ValueError:
                        pass

        for token in row:
            if token in ("S", "O"):
                support_oppose = token
                break

        yield raw_line, {
            "expenditure_date": expenditure_date,
            "amount": amount,
            "support_oppose": support_oppose,
            # placeholders (fill later once you map real SE columns)
            "candidate_id": None,
            "candidate_name": None,
            "candidate_office": None,
            "candidate_state": None,
            "candidate_district": None,
            "election_code": None,
            "purpose": None,
            "payee_name": None,
        }


def _parse_mmddyyyy(s: str) -> Optional[date]:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None
