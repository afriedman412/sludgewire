"""Gmail SMTP email service for sending alerts."""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from sqlmodel import Session, select

from .schemas import EmailRecipient
from .settings import load_settings


GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def get_active_recipients(session: Session) -> List[str]:
    """Get all active email recipients from the database."""
    stmt = select(EmailRecipient).where(EmailRecipient.active == True)  # noqa: E712
    recipients = session.exec(stmt).all()
    return [r.email for r in recipients]


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


def send_filing_alert(
    session: Session,
    filing_type: str,
    filings: List[dict],
) -> bool:
    """Send an alert email about new filings.

    Args:
        session: Database session
        filing_type: Type of filings ('3x' or 'e')
        filings: List of filing data dicts

    Returns:
        True if email was sent successfully
    """
    recipients = get_active_recipients(session)
    if not recipients:
        print("No active email recipients configured")
        return False

    if not filings:
        return False

    # Build email content
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
            rows_html += f"""
            <tr>
                <td>{f.get('committee_name', f.get('committee_id', 'N/A'))}</td>
                <td>{total_str}</td>
                <td><a href="{f.get('fec_url', '#')}">View</a></td>
            </tr>
            """
        table_html = f"""
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
            <tr style="background: #f6f6f6;">
                <th>Committee</th>
                <th>Total Receipts</th>
                <th>Filing</th>
            </tr>
            {rows_html}
        </table>
        """
    else:
        rows_html = ""
        for f in filings:
            amount = f.get("amount")
            amount_str = f"${amount:,.2f}" if amount else "N/A"
            rows_html += f"""
            <tr>
                <td>{f.get('committee_name', f.get('committee_id', 'N/A'))}</td>
                <td>{f.get('support_oppose', 'N/A')}</td>
                <td>{amount_str}</td>
                <td>{f.get('candidate_name', 'N/A')}</td>
            </tr>
            """
        table_html = f"""
        <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
            <tr style="background: #f6f6f6;">
                <th>Committee</th>
                <th>S/O</th>
                <th>Amount</th>
                <th>Candidate</th>
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

    return send_email(recipients, subject, body_html)
