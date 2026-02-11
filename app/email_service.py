"""Gmail SMTP email service for sending alerts."""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Dict

from sqlmodel import Session, select

from .schemas import EmailRecipient
from .settings import load_settings


GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def get_active_recipients(session: Session) -> List[EmailRecipient]:
    """Get all active email recipients from the database."""
    stmt = select(EmailRecipient).where(EmailRecipient.active == True)  # noqa: E712
    return session.exec(stmt).all()


def _filter_filings_for_recipient(
    filings: List[dict],
    recipient: EmailRecipient,
) -> List[dict]:
    """Filter filings based on recipient's committee_ids subscription.

    If recipient has no committee_ids (None or empty list), they get all filings.
    Otherwise, only filings matching their subscribed committee_ids are included.
    """
    if not recipient.committee_ids:
        return filings
    subscribed = set(recipient.committee_ids)
    return [f for f in filings if f.get("committee_id") in subscribed]


def send_email(
    to_addresses: List[str],
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
) -> bool:
    """Send an email via Gmail SMTP.

    Args:
        to_addresses: List of recipient email addresses
        subject: Email subject
        body_html: HTML body content
        body_text: Plain text body (falls back to stripping HTML if not provided)

    Returns:
        True if email was sent successfully, False otherwise
    """
    settings = load_settings()

    if not settings.google_app_pw or not settings.email_from:
        print("Email not configured: missing GOOGLE_APP_PW or EMAIL_FROM")
        return False

    if not to_addresses:
        print("No recipients specified")
        return False

    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = ", ".join(to_addresses)

    # Plain text fallback
    if body_text is None:
        # Simple HTML stripping for fallback
        import re
        body_text = re.sub(r"<[^>]+>", "", body_html)
        body_text = re.sub(r"\s+", " ", body_text).strip()

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(settings.email_from, settings.google_app_pw)
            server.sendmail(settings.email_from, to_addresses, msg.as_string())
        print(f"Email sent to {len(to_addresses)} recipients")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def _build_alert_email(
    filing_type: str,
    filings: List[dict],
) -> tuple[str, str]:
    """Build subject and HTML body for a filing alert.

    Returns:
        (subject, body_html) tuple
    """
    if filing_type == "3x":
        subject = f"FEC Alert: {len(filings)} new F3X filing(s)"
        type_label = "F3X Filings"
    else:
        subject = f"FEC Alert: {len(filings)} new Schedule E event(s)"
        type_label = "Schedule E Events"

    # Build HTML table
    if filing_type == "3x":
        rows_html = ""
        for f in filings:
            total = f.get("total_receipts")
            total_str = f"${total:,.2f}" if total else "N/A"
            committee_id = f.get('committee_id', '')
            committee_name = f.get('committee_name') or committee_id or 'N/A'
            committee_link = f'<a href="https://www.fec.gov/data/committee/{committee_id}/">{committee_name}</a>' if committee_id else committee_name
            coverage = f"{f.get('coverage_from', '')} → {f.get('coverage_through', '')}" if f.get('coverage_from') else "N/A"
            rows_html += f"""
            <tr>
                <td>{f.get('filed_at_utc', 'N/A')}</td>
                <td>{committee_link}</td>
                <td>{f.get('form_type', 'N/A')}</td>
                <td>{f.get('report_type', 'N/A')}</td>
                <td>{coverage}</td>
                <td style="text-align: right;">{total_str}</td>
                <td><a href="{f.get('fec_url', '#')}">.fec</a></td>
            </tr>
            """
        table_html = f"""
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; font-size: 14px;">
            <tr style="background: #f6f6f6;">
                <th>Filed (UTC)</th>
                <th>Committee</th>
                <th>Form</th>
                <th>Report</th>
                <th>Coverage</th>
                <th>Total Receipts</th>
                <th>Raw</th>
            </tr>
            {rows_html}
        </table>
        """
    else:
        rows_html = ""
        for f in filings:
            amount = f.get("amount")
            amount_str = f"${amount:,.2f}" if amount else "N/A"
            committee_id = f.get('committee_id', '')
            committee_name = f.get('committee_name') or committee_id or 'N/A'
            committee_link = f'<a href="https://www.fec.gov/data/committee/{committee_id}/">{committee_name}</a>' if committee_id else committee_name
            candidate_id = f.get('candidate_id', '')
            candidate_name = f.get('candidate_name') or 'N/A'
            candidate_link = f'<a href="https://www.fec.gov/data/candidate/{candidate_id}/">{candidate_name}</a>' if candidate_id else candidate_name
            # Format office as "H-CA-12 (DEM)" or "S-TX (REP)" or "P"
            office = f.get('candidate_office', '')
            state = f.get('candidate_state', '')
            district = f.get('candidate_district', '')
            party = f.get('candidate_party', '')
            office_parts = [p for p in [office, state, district] if p]
            office_str = '-'.join(office_parts) if office_parts else ''
            if party:
                office_str = f"{office_str} ({party})" if office_str else party
            so = f.get('support_oppose', '')
            so_style = 'color: #28a745; font-weight: bold;' if so == 'S' else 'color: #dc3545; font-weight: bold;' if so == 'O' else ''
            rows_html += f"""
            <tr>
                <td>{committee_link}</td>
                <td>{candidate_link}</td>
                <td>{office_str or ''}</td>
                <td style="{so_style}">{so or 'N/A'}</td>
                <td>{f.get('purpose', '') or ''}</td>
                <td>{f.get('payee_name', '') or ''}</td>
                <td>{f.get('expenditure_date', '') or ''}</td>
                <td style="text-align: right;">{amount_str}</td>
                <td><a href="{f.get('fec_url', '#')}">.fec</a></td>
            </tr>
            """
        table_html = f"""
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; font-size: 14px;">
            <tr style="background: #f6f6f6;">
                <th>Spender</th>
                <th>Candidate</th>
                <th>Office</th>
                <th>S/O</th>
                <th>Purpose</th>
                <th>Payee</th>
                <th>Exp. Date</th>
                <th>Amount</th>
                <th>Raw</th>
            </tr>
            {rows_html}
        </table>
        """

    body_html = f"""
    <html>
    <body style="font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif;">
        <h2>{type_label}</h2>
        <p>Found {len(filings)} new {type_label.lower()}.</p>
        {table_html}
        <p style="margin-top: 20px; color: #666; font-size: 12px;">
            This is an automated alert from FEC Monitor.
        </p>
    </body>
    </html>
    """

    return subject, body_html


def send_filing_alert(
    session: Session,
    filing_type: str,
    filings: List[dict],
) -> Dict[str, int]:
    """Send alert emails about new filings, filtered per recipient.

    Each recipient receives only filings matching their committee_ids filter.
    Recipients with no committee_ids set receive all filings.

    Args:
        session: Database session
        filing_type: Type of filings ('3x' or 'e')
        filings: List of filing data dicts

    Returns:
        Dict mapping email address to number of filings sent, e.g.
        {"alice@example.com": 5, "bob@example.com": 2}
        Empty dict if no emails were sent.
    """
    recipients = get_active_recipients(session)
    if not recipients:
        print("No active email recipients configured")
        return {}

    if not filings:
        return {}

    sent: Dict[str, int] = {}

    for recipient in recipients:
        filtered = _filter_filings_for_recipient(filings, recipient)
        if not filtered:
            continue

        subject, body_html = _build_alert_email(filing_type, filtered)
        ok = send_email([recipient.email], subject, body_html)
        if ok:
            sent[recipient.email] = len(filtered)

    return sent
