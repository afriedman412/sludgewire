from __future__ import annotations

import csv
import io
import re
import hashlib
from datetime import date, datetime
from typing import Iterable, Optional, Tuple, List

import requests

# Lazy import fecfile - it's heavy and loads pandas/numpy
_fecfile = None

def _get_fecfile():
    global _fecfile
    if _fecfile is None:
        import fecfile
        _fecfile = fecfile
    return _fecfile


class FileTooLargeError(Exception):
    """Raised when a file exceeds the size limit."""
    def __init__(self, url: str, size_mb: float, limit_mb: float):
        self.url = url
        self.size_mb = size_mb
        self.limit_mb = limit_mb
        super().__init__(f"File {url} is {size_mb:.1f}MB, exceeds limit of {limit_mb}MB")


def check_file_size(fec_url: str, timeout: int = 10) -> Optional[float]:
    """Check file size via HEAD request. Returns size in MB, or None if unknown."""
    try:
        r = requests.head(fec_url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        content_length = r.headers.get("Content-Length")
        if content_length:
            return int(content_length) / (1024 * 1024)  # Convert to MB
    except Exception:
        pass
    return None


def download_fec_text(fec_url: str, max_size_mb: float = None) -> str:
    """Download FEC file text. Optionally check size first."""
    if max_size_mb is not None:
        size_mb = check_file_size(fec_url)
        if size_mb is not None and size_mb > max_size_mb:
            raise FileTooLargeError(fec_url, size_mb, max_size_mb)

    r = requests.get(fec_url, timeout=60)
    r.raise_for_status()
    return r.text


def parse_fec_filing(fec_text: str) -> dict:
    """Parse FEC filing text and return the parsed dict."""
    return _get_fecfile().loads(fec_text)


def parse_f3x_header_only(fec_text: str) -> dict:
    """
    Parse just the F3X header to extract summary fields.
    Much lighter than fecfile.loads() - doesn't load itemizations.

    Returns dict with 'filing' key containing header fields.
    """
    result = {"filing": {}}
    filing = result["filing"]

    # F3X files are pipe-delimited. Header is in first few lines.
    lines = fec_text.split('\n')

    for line in lines[:100]:  # Header is in first ~100 lines max
        if not line.strip():
            continue
        parts = line.split('|')
        if not parts:
            continue

        rec_type = parts[0].strip().upper()

        # F3X/F3XN/F3XA/F3XT record has committee name in position 2
        if rec_type.startswith('F3X') and len(parts) > 2:
            filing["form_type"] = parts[0].strip()
            filing["committee_name"] = parts[1].strip()
            filing["filer_committee_id_name"] = parts[1].strip()

        # Summary line (SA/SB) or look for "6a" type field which has total receipts
        # Actually, the totals are in specific summary records
        # In F3X, look for the line that starts with total receipts indicator

        # Try to find total receipts - usually in a line starting with specific codes
        # or we can try fecfile just on the first chunk
        if rec_type in ('F3X', 'F3XN', 'F3XA', 'F3XT'):
            # Try common positions for col_a_total_receipts (position varies by version)
            # In newer versions it's around position 6-7
            for pos in range(4, min(20, len(parts))):
                val_str = parts[pos].strip()
                if val_str and val_str.replace('.', '').replace('-', '').isdigit():
                    try:
                        val = float(val_str)
                        # Total receipts is usually a large positive number
                        if val >= 0 and "col_a_total_receipts" not in filing:
                            filing["col_a_total_receipts"] = val_str
                            break
                    except ValueError:
                        pass

    # Fallback: if we didn't find totals, use fecfile on truncated text
    # Only keep first 200 lines (header/summary) - skip itemizations
    if "col_a_total_receipts" not in filing:
        try:
            truncated = '\n'.join(fec_text.split('\n')[:200])
            full_parsed = _get_fecfile().loads(truncated)
            filing_data = full_parsed.get("filing", {})
            if "col_a_total_receipts" in filing_data:
                filing["col_a_total_receipts"] = filing_data["col_a_total_receipts"]
            if "committee_name" not in filing and "committee_name" in filing_data:
                filing["committee_name"] = filing_data["committee_name"]
            if "filer_committee_id_name" in filing_data:
                filing["filer_committee_id_name"] = filing_data["filer_committee_id_name"]
            del full_parsed
            del truncated
        except Exception:
            pass

    return result


def f3x_total_receipts(fec_text: str) -> Optional[float]:
    parsed = _get_fecfile().loads(fec_text)
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


def extract_schedule_e_best_effort(fec_text: str, parsed: dict = None) -> Iterable[Tuple[str, dict]]:
    """
    Yields (raw_line, extracted_fields_dict).

    Uses fecfile parsed output for structured field extraction.
    Falls back to raw line parsing if fecfile fails.

    Args:
        fec_text: Raw FEC filing text
        parsed: Optional pre-parsed dict from _get_fecfile().loads() to avoid double-parsing
    """
    # First, try to get structured data from fecfile
    try:
        if parsed is None:
            parsed = _get_fecfile().loads(fec_text)
        filing = parsed.get("filing", {})
        itemizations = parsed.get("itemizations", {})

        # fecfile uses "Schedule E" as the key
        se_items = itemizations.get(
            "Schedule E", []) or itemizations.get("SE", [])

        for item in se_items:
            # Build raw_line from item for deduplication
            raw_line = "|".join(str(v) for v in item.values() if v)

            # Extract expenditure date (dissemination_date or disbursement_date)
            expenditure_date = None
            for date_field in ("dissemination_date", "disbursement_date", "expenditure_date"):
                val = item.get(date_field)
                if val:
                    if isinstance(val, datetime):
                        expenditure_date = val.date()
                    elif isinstance(val, date):
                        expenditure_date = val
                    elif isinstance(val, str):
                        expenditure_date = _parse_date_flexible(val)
                    if expenditure_date:
                        break

            # Extract amount
            amount = None
            amount_val = item.get("expenditure_amount")
            if amount_val is not None:
                try:
                    amount = float(amount_val)
                except (TypeError, ValueError):
                    pass

            # Build candidate name
            candidate_parts = [
                item.get("candidate_first_name", ""),
                item.get("candidate_middle_name", ""),
                item.get("candidate_last_name", ""),
            ]
            candidate_name = " ".join(p.strip()
                                      for p in candidate_parts if p and p.strip())

            # Build payee name
            payee_org = item.get("payee_organization_name", "")
            if payee_org and payee_org.strip():
                payee_name = payee_org.strip()
            else:
                payee_parts = [
                    item.get("payee_first_name", ""),
                    item.get("payee_last_name", ""),
                ]
                payee_name = " ".join(p.strip()
                                      for p in payee_parts if p and p.strip())

            yield raw_line, {
                "expenditure_date": expenditure_date,
                "amount": amount,
                "support_oppose": item.get("support_oppose_code"),
                "candidate_id": item.get("candidate_id_number"),
                "candidate_name": candidate_name or None,
                "candidate_office": item.get("candidate_office"),
                "candidate_state": item.get("candidate_state"),
                "candidate_district": item.get("candidate_district"),
                "candidate_party": item.get("so_cand_pty_affiliation"),
                "election_code": item.get("election_code"),
                "purpose": item.get("expenditure_purpose_descrip"),
                "payee_name": payee_name or None,
            }

        # If we got items from fecfile, we're done
        if se_items:
            return

    except Exception:
        pass  # Fall back to raw parsing

    # Fallback: raw line parsing for SE records
    for row in iter_pipe_rows(fec_text):
        rec = row[0]
        if not rec.startswith("SE"):
            continue

        raw_line = "|".join(row)

        # Heuristic extraction
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
            "candidate_id": None,
            "candidate_name": None,
            "candidate_office": None,
            "candidate_state": None,
            "candidate_district": None,
            "candidate_party": None,
            "election_code": None,
            "purpose": None,
            "payee_name": None,
        }


def _parse_date_flexible(s: str) -> Optional[date]:
    """Parse date from various formats."""
    if not s:
        return None
    s = s.strip()
    # Try ISO format first (from fecfile datetime objects converted to string)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _parse_mmddyyyy(s: str) -> Optional[date]:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None
