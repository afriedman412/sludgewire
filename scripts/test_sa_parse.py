"""
Smoke test for Schedule A parsing.

Downloads a real FEC filing from a target PAC and runs the parser.
No database needed — just tests the download + parse pipeline.

Usage:
    python scripts/test_sa_parse.py [filing_id]

If no filing_id is provided, fetches a recent one from Fairshake (C00835959).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.fec_parse import (
    download_fec_text,
    parse_fec_filing,
    extract_schedule_a_best_effort,
    check_file_size,
)


def find_recent_filing(committee_id: str) -> int:
    """Find a recent F3X filing ID for a committee via the FEC API."""
    import requests
    from dotenv import dotenv_values
    env = dotenv_values()
    api_key = env.get("GOV_API_KEY", "DEMO_KEY")
    url = (
        f"https://api.open.fec.gov/v1/efile/filings/"
        f"?committee_id={committee_id}"
        f"&form_type=F3X"
        f"&sort=-receipt_date"
        f"&per_page=1"
        f"&api_key={api_key}"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        print(f"No F3X filings found for {committee_id}")
        sys.exit(1)
    filing = results[0]
    print(f"Found filing {filing['file_number']} "
          f"from {filing.get('receipt_date', '?')} "
          f"({filing.get('committee_name', '?')})")
    return int(filing["file_number"])


def main():
    if len(sys.argv) > 1:
        filing_id = int(sys.argv[1])
    else:
        print("No filing ID provided, looking up a recent Fairshake F3X...")
        filing_id = find_recent_filing("C00835959")

    fec_url = f"https://docquery.fec.gov/dcdev/posted/{filing_id}.fec"
    print(f"\n--- Filing {filing_id} ---")
    print(f"URL: {fec_url}")

    # Check file size first
    size_mb = check_file_size(fec_url)
    if size_mb:
        print(f"File size: {size_mb:.1f} MB")
        if size_mb > 50:
            print("WARNING: File exceeds 50MB limit, skipping download")
            return
    else:
        print("File size: unknown (HEAD request failed)")

    # Download
    print("\nDownloading...")
    fec_text = download_fec_text(fec_url, max_size_mb=50)
    print(f"Downloaded {len(fec_text):,} chars")

    # Parse with fecfile
    print("\nParsing with fecfile...")
    parsed = parse_fec_filing(fec_text)

    filing_info = parsed.get("filing", {})
    itemizations = parsed.get("itemizations", {})
    print(f"Filing form_type: {filing_info.get('form_type')}")
    print(f"Committee: {filing_info.get('committee_name')}")
    print(f"Itemization keys: {list(itemizations.keys())}")
    for key, items in itemizations.items():
        print(f"  {key}: {len(items)} items")

    # Extract Schedule A
    print("\nExtracting Schedule A items...")
    sa_items = list(extract_schedule_a_best_effort(fec_text, parsed=parsed))
    print(f"Found {len(sa_items)} Schedule A items")

    if not sa_items:
        print("\nNo Schedule A items found in this filing.")
        print("This might be normal — not all F3X filings have itemized receipts.")
        return

    # Show first 5 items
    print(f"\nFirst {min(5, len(sa_items))} items:")
    print("-" * 80)
    for i, (raw_line, fields) in enumerate(sa_items[:5]):
        print(f"\n[{i+1}]")
        print(f"  Name:       {fields['contributor_name']}")
        print(f"  Employer:   {fields['contributor_employer']}")
        print(f"  Occupation: {fields['contributor_occupation']}")
        print(f"  Amount:     ${fields['contribution_amount']:,.2f}"
              if fields['contribution_amount'] else "  Amount:     None")
        print(f"  Date:       {fields['contribution_date']}")
        print(f"  Type:       {fields['contributor_type']}")
        print(f"  Memo:       {fields['memo_text']}")
        print(f"  Receipt:    {fields['receipt_description']}")
        print(f"  Raw (trunc): {raw_line[:120]}...")

    # Summary stats
    amounts = [f["contribution_amount"] for _, f in sa_items
               if f["contribution_amount"] is not None]
    if amounts:
        print(f"\n--- Summary ---")
        print(f"Total items:  {len(sa_items)}")
        print(f"With amounts: {len(amounts)}")
        print(f"Total:        ${sum(amounts):,.2f}")
        print(f"Min:          ${min(amounts):,.2f}")
        print(f"Max:          ${max(amounts):,.2f}")
        print(f"Avg:          ${sum(amounts)/len(amounts):,.2f}")

    # Count by type
    types = {}
    for _, f in sa_items:
        t = f["contributor_type"] or "unknown"
        types[t] = types.get(t, 0) + 1
    print(f"\nBy contributor type:")
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

    print("\nParse test PASSED")


if __name__ == "__main__":
    main()
