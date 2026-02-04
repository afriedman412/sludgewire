# app/api.py
from __future__ import annotations

from datetime import datetime, date, time, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Any, Dict
from pathlib import Path
import threading

from fastapi import FastAPI, Depends, Query, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, col

from .settings import load_settings
from .db import make_engine, init_db
from .schemas import FilingF3X, IEScheduleE, EmailRecipient, BackfillJob, AppConfig
import json
from .auth import verify_admin

# --- App + DB bootstrap ---
settings = load_settings()
engine = make_engine(settings)
init_db(engine)

app = FastAPI(title="FEC Monitor", version="0.2.0")

# Rate-limiting for current-day ingestion (in-memory, resets on deploy)
_last_ingestion_time: Optional[datetime] = None
_ingestion_lock = threading.Lock()
INGESTION_COOLDOWN_MINUTES = 5
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ET = ZoneInfo("America/New_York")


def get_session():
    with Session(engine) as session:
        yield session


def format_currency(value):
    if value is None:
        return ""
    return f"${value:,.2f}"


templates.env.filters["format_currency"] = format_currency


def et_today_utc_bounds(now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Return [start_utc, end_utc) for "today" in America/New_York.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    today_et = now_utc.astimezone(ET).date()
    start_et = datetime.combine(today_et, time(0, 0, 0), tzinfo=ET)
    tomorrow_et = date.fromordinal(today_et.toordinal() + 1)
    end_et = datetime.combine(tomorrow_et, time(0, 0, 0), tzinfo=ET)

    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _model_dump(obj: Any) -> Dict[str, Any]:
    """
    SQLModel uses Pydantic under the hood. model_dump exists on newer pydantic.
    Fall back to dict() if needed.
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj.dict()  # type: ignore[attr-defined]


@app.get("/healthz")
def healthz():
    return {"ok": True}


# -------------------------
# Dashboards (HTML)
# -------------------------

@app.get("/dashboard/3x", response_class=HTMLResponse)
def dashboard_3x(
    request: Request,
    session: Session = Depends(get_session),
    threshold: float = Query(default=50_000, ge=0),
    limit: int = Query(default=200, ge=1, le=2000),
):
    # Trigger rate-limited ingestion on page load
    _maybe_run_ingestion()

    start_utc, end_utc = et_today_utc_bounds()
    today = start_utc.astimezone(ET).date()

    stmt = (
        select(FilingF3X)
        .where(FilingF3X.filed_at_utc >= start_utc)
        .where(FilingF3X.filed_at_utc < end_utc)
        .where(FilingF3X.total_receipts != None)  # noqa: E711
        .where(FilingF3X.total_receipts >= threshold)
        .order_by(FilingF3X.filed_at_utc.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return templates.TemplateResponse(
        "dashboard_3x.html",
        {
            "request": request,
            "rows": rows,
            "threshold": threshold,
            "day_et": today,
            "prev_date": today - timedelta(days=1),
            "next_date": today + timedelta(days=1),
            "today": today,
            "api_url": f"/api/3x/today?threshold={threshold}&limit={limit}",
        },
    )


@app.get("/dashboard/e", response_class=HTMLResponse)
def dashboard_e(
    request: Request,
    session: Session = Depends(get_session),
    limit: int = Query(default=200, ge=1, le=2000),
):
    """
    Shows Schedule E EVENTS filed today (ET).
    If you want "filings" instead, we can switch this to a DISTINCT filing_id query.
    """
    # Trigger rate-limited ingestion on page load
    _maybe_run_ingestion()

    start_utc, end_utc = et_today_utc_bounds()
    today = start_utc.astimezone(ET).date()

    stmt = (
        select(IEScheduleE)
        .where(IEScheduleE.filed_at_utc >= start_utc)
        .where(IEScheduleE.filed_at_utc < end_utc)
        .order_by(IEScheduleE.filed_at_utc.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return templates.TemplateResponse(
        "dashboard_e.html",
        {
            "request": request,
            "rows": rows,
            "day_et": today,
            "prev_date": today - timedelta(days=1),
            "next_date": today + timedelta(days=1),
            "today": today,
            "api_url": f"/api/e/today?limit={limit}",
        },
    )


# -------------------------
# JSON API (Today)
# -------------------------

@app.get("/api/3x/today")
def api_3x_today(
    session: Session = Depends(get_session),
    threshold: float = Query(default=50_000, ge=0),
    limit: int = Query(default=200, ge=1, le=5000),
):
    start_utc, end_utc = et_today_utc_bounds()

    stmt = (
        select(FilingF3X)
        .where(FilingF3X.filed_at_utc >= start_utc)
        .where(FilingF3X.filed_at_utc < end_utc)
        .where(FilingF3X.total_receipts != None)  # noqa: E711
        .where(FilingF3X.total_receipts >= threshold)
        .order_by(FilingF3X.filed_at_utc.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return {
        "day_et": start_utc.astimezone(ET).date().isoformat(),
        "threshold": threshold,
        "count": len(rows),
        "results": [_model_dump(r) for r in rows],
    }


@app.get("/api/e/today")
def api_e_today(
    session: Session = Depends(get_session),
    limit: int = Query(default=500, ge=1, le=5000),
):
    start_utc, end_utc = et_today_utc_bounds()

    stmt = (
        select(IEScheduleE)
        .where(IEScheduleE.filed_at_utc >= start_utc)
        .where(IEScheduleE.filed_at_utc < end_utc)
        .order_by(IEScheduleE.filed_at_utc.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return {
        "day_et": start_utc.astimezone(ET).date().isoformat(),
        "count": len(rows),
        "results": [_model_dump(r) for r in rows],
    }


# -------------------------
# JSON API (General query)
# -------------------------

@app.get("/api/3x")
def api_3x_query(
    session: Session = Depends(get_session),
    committee_id: Optional[str] = None,
    min_receipts: Optional[float] = Query(default=None, ge=0),
    filed_after_utc: Optional[datetime] = None,
    filed_before_utc: Optional[datetime] = None,
    limit: int = Query(default=200, ge=1, le=5000),
):
    stmt = select(FilingF3X)

    if committee_id:
        stmt = stmt.where(FilingF3X.committee_id == committee_id)
    if min_receipts is not None:
        stmt = stmt.where(FilingF3X.total_receipts != None)  # noqa: E711
        stmt = stmt.where(FilingF3X.total_receipts >= min_receipts)
    if filed_after_utc:
        stmt = stmt.where(FilingF3X.filed_at_utc >= filed_after_utc)
    if filed_before_utc:
        stmt = stmt.where(FilingF3X.filed_at_utc < filed_before_utc)

    stmt = stmt.order_by(FilingF3X.filed_at_utc.desc()).limit(limit)
    rows = session.exec(stmt).all()
    return {"count": len(rows), "results": [_model_dump(r) for r in rows]}


@app.get("/api/e")
def api_e_query(
    session: Session = Depends(get_session),
    filer_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
    min_amount: Optional[float] = Query(default=None, ge=0),
    filed_after_utc: Optional[datetime] = None,
    filed_before_utc: Optional[datetime] = None,
    limit: int = Query(default=500, ge=1, le=5000),
):
    stmt = select(IEScheduleE)

    if filer_id:
        stmt = stmt.where(col(IEScheduleE.filer_id) == filer_id)
    if candidate_id:
        stmt = stmt.where(col(IEScheduleE.candidate_id) == candidate_id)
    if min_amount is not None:
        stmt = stmt.where(IEScheduleE.amount != None)  # noqa: E711
        stmt = stmt.where(IEScheduleE.amount >= min_amount)
    if filed_after_utc:
        stmt = stmt.where(IEScheduleE.filed_at_utc >= filed_after_utc)
    if filed_before_utc:
        stmt = stmt.where(IEScheduleE.filed_at_utc < filed_before_utc)

    stmt = stmt.order_by(IEScheduleE.filed_at_utc.desc()).limit(limit)
    rows = session.exec(stmt).all()
    return {"count": len(rows), "results": [_model_dump(r) for r in rows]}


# -------------------------
# Config Endpoints (Protected)
# -------------------------

def _get_memory_usage_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import resource
        # Returns bytes on Linux, need to convert
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On macOS it's bytes, on Linux it's KB
        import platform
        if platform.system() == "Darwin":
            return usage / (1024 * 1024)
        else:
            return usage / 1024
    except Exception:
        return 0.0


@app.get("/config", response_class=HTMLResponse)
def config_page(
    request: Request,
    session: Session = Depends(get_session),
    _: str = Depends(verify_admin),
    message: Optional[str] = Query(default=None),
    message_type: Optional[str] = Query(default=None),
):
    """Password-protected config page for managing email recipients."""
    recipients = session.exec(
        select(EmailRecipient).order_by(EmailRecipient.created_at.desc())
    ).all()

    # Get pending/running backfill jobs
    backfill_jobs = session.exec(
        select(BackfillJob)
        .where(BackfillJob.status.in_(["pending", "running"]))
        .order_by(BackfillJob.started_at.desc())
    ).all()

    # Get memory usage
    memory_mb = _get_memory_usage_mb()

    # Get last cron run status
    last_cron_run = None
    cron_config = session.get(AppConfig, "last_cron_run")
    if cron_config and cron_config.value:
        try:
            last_cron_run = json.loads(cron_config.value)
        except json.JSONDecodeError:
            pass

    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "recipients": recipients,
            "backfill_jobs": backfill_jobs,
            "memory_mb": memory_mb,
            "last_cron_run": last_cron_run,
            "message": message,
            "message_type": message_type,
        },
    )


@app.post("/config/recipients")
def add_recipient(
    session: Session = Depends(get_session),
    _: str = Depends(verify_admin),
    email: str = Form(...),
):
    """Add a new email recipient."""
    existing = session.exec(
        select(EmailRecipient).where(EmailRecipient.email == email)
    ).first()

    if existing:
        return RedirectResponse(
            url="/config?message=Email already exists&message_type=error",
            status_code=303,
        )

    recipient = EmailRecipient(email=email, active=True)
    session.add(recipient)
    session.commit()

    return RedirectResponse(
        url="/config?message=Recipient added&message_type=success",
        status_code=303,
    )


@app.post("/config/recipients/{recipient_id}/delete")
def delete_recipient(
    recipient_id: int,
    session: Session = Depends(get_session),
    _: str = Depends(verify_admin),
):
    """Remove an email recipient."""
    recipient = session.get(EmailRecipient, recipient_id)

    if recipient:
        session.delete(recipient)
        session.commit()
        return RedirectResponse(
            url="/config?message=Recipient removed&message_type=success",
            status_code=303,
        )

    return RedirectResponse(
        url="/config?message=Recipient not found&message_type=error",
        status_code=303,
    )


@app.post("/config/backfill/{job_id}/delete")
def delete_backfill_job(
    job_id: int,
    session: Session = Depends(get_session),
    _: str = Depends(verify_admin),
):
    """Delete a backfill job. Admin-only."""
    job = session.get(BackfillJob, job_id)

    if job:
        session.delete(job)
        session.commit()
        return RedirectResponse(
            url="/config?message=Backfill job deleted&message_type=success",
            status_code=303,
        )

    return RedirectResponse(
        url="/config?message=Job not found&message_type=error",
        status_code=303,
    )


@app.post("/config/backfill/{year:int}/{month:int}/{day:int}/{filing_type}")
def trigger_backfill(
    year: int,
    month: int,
    day: int,
    filing_type: str,
    session: Session = Depends(get_session),
    _: str = Depends(verify_admin),
):
    """Manually trigger backfill for a specific date. Admin-only."""
    from .backfill import get_backfill_status, get_or_create_backfill_job

    if filing_type not in ("3x", "e"):
        return {"error": "Invalid filing_type. Must be '3x' or 'e'"}, 400

    try:
        target_date = date(year, month, day)
    except ValueError:
        return {"error": "Invalid date"}, 400

    today = datetime.now(timezone.utc).astimezone(ET).date()
    if target_date >= today:
        return {"error": "Cannot backfill current or future dates"}, 400

    # Check if already running or completed
    job = get_backfill_status(session, target_date, filing_type)
    if job and job.status == "running":
        return {"status": "already_running", "job_id": job.id}
    if job and job.status == "completed":
        return {"status": "already_completed", "filings_found": job.filings_found}

    # Create/reset job and trigger backfill
    job = get_or_create_backfill_job(session, target_date, filing_type)
    _trigger_backfill_async(target_date, filing_type)

    return {
        "status": "started",
        "date": target_date.isoformat(),
        "filing_type": filing_type,
        "check_status_at": f"/api/backfill/status/{year}/{month}/{day}/{filing_type}",
    }


# -------------------------
# Date-based Dashboards with Backfill
# -------------------------

def _date_utc_bounds(target_date: date) -> tuple[datetime, datetime]:
    """Return [start_utc, end_utc) for a specific date in ET."""
    start_et = datetime.combine(target_date, time(0, 0, 0), tzinfo=ET)
    end_et = datetime.combine(
        target_date + timedelta(days=1), time(0, 0, 0), tzinfo=ET)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _trigger_backfill_async(target_date: date, filing_type: str):
    """Trigger backfill in background thread."""
    from .backfill import backfill_date_f3x, backfill_date_e

    def run():
        with Session(engine) as session:
            if filing_type == "3x":
                backfill_date_f3x(session, target_date)
            else:
                backfill_date_e(session, target_date)

    thread = threading.Thread(target=run, daemon=False)
    thread.start()


def _maybe_run_ingestion() -> bool:
    """Run ingestion if cooldown has passed. Returns True if ingestion ran."""
    global _last_ingestion_time

    now = datetime.now(timezone.utc)

    with _ingestion_lock:
        if _last_ingestion_time is not None:
            elapsed = (now - _last_ingestion_time).total_seconds() / 60
            if elapsed < INGESTION_COOLDOWN_MINUTES:
                return False
        _last_ingestion_time = now

    # Run ingestion in background thread to not block page load
    def run():
        from .ingest_f3x import run_f3x
        from .ingest_ie import run_ie_schedule_e

        with Session(engine) as bg_session:
            try:
                run_f3x(
                    bg_session,
                    feed_url=settings.f3x_feed,
                    receipts_threshold=settings.receipts_threshold,
                )
            except Exception:
                pass
            try:
                run_ie_schedule_e(bg_session, feed_urls=settings.ie_feeds)
            except Exception:
                pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return True


@app.get("/{year:int}/{month:int}/{day:int}/3x", response_class=HTMLResponse)
def dashboard_date_3x(
    request: Request,
    year: int,
    month: int,
    day: int,
    session: Session = Depends(get_session),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Date-based F3X dashboard. Backfill must be triggered manually via /config."""
    from .backfill import get_backfill_status

    try:
        target_date = date(year, month, day)
    except ValueError:
        return HTMLResponse("Invalid date", status_code=400)

    today = datetime.now(timezone.utc).astimezone(ET).date()

    # For current day, trigger rate-limited ingestion
    if target_date == today:
        _maybe_run_ingestion()

    # Check backfill status (but don't auto-trigger)
    backfill_job = get_backfill_status(session, target_date, "3x")

    # Query filings for this date - always filter by receipts threshold
    threshold = settings.receipts_threshold
    start_utc, end_utc = _date_utc_bounds(target_date)
    stmt = (
        select(FilingF3X)
        .where(FilingF3X.filed_at_utc >= start_utc)
        .where(FilingF3X.filed_at_utc < end_utc)
        .where(FilingF3X.total_receipts != None)  # noqa: E711
        .where(FilingF3X.total_receipts >= threshold)
        .order_by(FilingF3X.filed_at_utc.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return templates.TemplateResponse(
        "dashboard_date.html",
        {
            "request": request,
            "rows": rows,
            "target_date": target_date,
            "prev_date": target_date - timedelta(days=1),
            "next_date": target_date + timedelta(days=1),
            "today": today,
            "filing_type": "3x",
            "filing_type_label": f"F3X Filings (≥${threshold:,.0f})",
            "backfill_job": backfill_job,
        },
    )


@app.get("/{year:int}/{month:int}/{day:int}/e", response_class=HTMLResponse)
def dashboard_date_e(
    request: Request,
    year: int,
    month: int,
    day: int,
    session: Session = Depends(get_session),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Date-based Schedule E dashboard. Backfill must be triggered manually via /config."""
    from .backfill import get_backfill_status

    try:
        target_date = date(year, month, day)
    except ValueError:
        return HTMLResponse("Invalid date", status_code=400)

    today = datetime.now(timezone.utc).astimezone(ET).date()

    # For current day, trigger rate-limited ingestion
    if target_date == today:
        _maybe_run_ingestion()

    # Check backfill status (but don't auto-trigger)
    backfill_job = get_backfill_status(session, target_date, "e")

    # Query events for this date
    start_utc, end_utc = _date_utc_bounds(target_date)
    stmt = (
        select(IEScheduleE)
        .where(IEScheduleE.filed_at_utc >= start_utc)
        .where(IEScheduleE.filed_at_utc < end_utc)
        .order_by(IEScheduleE.filed_at_utc.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return templates.TemplateResponse(
        "dashboard_date.html",
        {
            "request": request,
            "rows": rows,
            "target_date": target_date,
            "prev_date": target_date - timedelta(days=1),
            "next_date": target_date + timedelta(days=1),
            "today": today,
            "filing_type": "e",
            "filing_type_label": "Schedule E Events",
            "backfill_job": backfill_job,
        },
    )


@app.get("/api/backfill/status/{year:int}/{month:int}/{day:int}/{filing_type}")
def api_backfill_status(
    year: int,
    month: int,
    day: int,
    filing_type: str,
    session: Session = Depends(get_session),
):
    """Get backfill status for polling."""
    from .backfill import get_backfill_status

    if filing_type not in ("3x", "e"):
        return {"error": "Invalid filing_type"}, 400

    try:
        target_date = date(year, month, day)
    except ValueError:
        return {"error": "Invalid date"}, 400

    job = get_backfill_status(session, target_date, filing_type)
    if job is None:
        return {"status": "not_started"}

    return {
        "status": job.status,
        "filings_found": job.filings_found,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
    }


# -------------------------
# Cron Endpoint
# -------------------------

def _save_cron_status(session: Session, results: dict):
    """Save cron run results to AppConfig."""
    config_entry = session.get(AppConfig, "last_cron_run")
    if config_entry:
        config_entry.value = json.dumps(results)
        config_entry.updated_at = datetime.now(timezone.utc)
    else:
        config_entry = AppConfig(key="last_cron_run", value=json.dumps(results))
    session.add(config_entry)
    session.commit()


def _log_memory(label: str, results: dict):
    """Log memory usage at a checkpoint."""
    mb = _get_memory_usage_mb()
    if "memory_log" not in results:
        results["memory_log"] = []
    results["memory_log"].append({"step": label, "memory_mb": round(mb, 1)})
    print(f"[MEMORY] {label}: {mb:.1f} MB")


@app.get("/api/cron/check-new")
def cron_check_new(session: Session = Depends(get_session)):
    """Cron endpoint to check for new filings and send email alerts.

    This endpoint is designed to be called by a scheduled task (e.g., Cloud Scheduler).
    It runs the ingestion process and sends email alerts if new filings are found.
    """
    import gc
    from fastapi.responses import JSONResponse
    from .ingest_f3x import run_f3x
    from .ingest_ie import run_ie_schedule_e
    from .email_service import send_filing_alert

    started_at = datetime.now(timezone.utc)

    results = {
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "http_status": 200,
        "status": "running",
        "f3x_new": 0,
        "ie_filings_new": 0,
        "ie_events_new": 0,
        "email_sent": False,
        "emails_sent_to": [],
    }

    _log_memory("start", results)

    # Save "running" status immediately so we can see if it crashes mid-run
    _save_cron_status(session, results)

    try:
        # Run F3X ingestion
        _log_memory("before_f3x_ingestion", results)
        try:
            f3x_count = run_f3x(
                session,
                feed_url=settings.f3x_feed,
                receipts_threshold=settings.receipts_threshold,
            )
            results["f3x_new"] = f3x_count
        except Exception as e:
            results["f3x_error"] = str(e)
        _log_memory("after_f3x_ingestion", results)
        gc.collect()
        _log_memory("after_f3x_gc", results)

        # Run IE Schedule E ingestion
        _log_memory("before_ie_ingestion", results)
        try:
            ie_filings, ie_events = run_ie_schedule_e(
                session,
                feed_urls=settings.ie_feeds,
            )
            results["ie_filings_new"] = ie_filings
            results["ie_events_new"] = ie_events
        except Exception as e:
            results["ie_error"] = str(e)
        _log_memory("after_ie_ingestion", results)
        gc.collect()
        _log_memory("after_ie_gc", results)

        # Get active email recipients for logging
        active_recipients = session.exec(
            select(EmailRecipient).where(EmailRecipient.active == True)
        ).all()
        recipient_emails = [r.email for r in active_recipients]

        _log_memory("before_email_check", results)

        # Send email alerts if new filings were found
        if results["f3x_new"] > 0 or results["ie_events_new"] > 0:
            start_utc, end_utc = et_today_utc_bounds()

            if results["f3x_new"] > 0:
                stmt = (
                    select(FilingF3X)
                    .where(FilingF3X.filed_at_utc >= start_utc)
                    .where(FilingF3X.filed_at_utc < end_utc)
                    .where(FilingF3X.total_receipts >= settings.receipts_threshold)
                    .order_by(FilingF3X.filed_at_utc.desc())
                    .limit(50)
                )
                f3x_filings = session.exec(stmt).all()
                if f3x_filings:
                    # Only include fields needed for email (avoid large raw_meta)
                    filings_data = [{
                        "committee_name": f.committee_name,
                        "committee_id": f.committee_id,
                        "total_receipts": f.total_receipts,
                        "fec_url": f.fec_url,
                    } for f in f3x_filings]
                    send_filing_alert(session, "3x", filings_data)
                    results["email_sent"] = True
                    results["emails_sent_to"] = recipient_emails

            if results["ie_events_new"] > 0:
                stmt = (
                    select(IEScheduleE)
                    .where(IEScheduleE.filed_at_utc >= start_utc)
                    .where(IEScheduleE.filed_at_utc < end_utc)
                    .order_by(IEScheduleE.filed_at_utc.desc())
                    .limit(50)
                )
                ie_events = session.exec(stmt).all()
                if ie_events:
                    # Only include fields needed for email (avoid large raw_line)
                    events_data = [{
                        "committee_name": e.committee_name,
                        "committee_id": e.committee_id,
                        "support_oppose": e.support_oppose,
                        "amount": e.amount,
                        "candidate_name": e.candidate_name,
                    } for e in ie_events]
                    send_filing_alert(session, "e", events_data)
                    results["email_sent"] = True
                    results["emails_sent_to"] = recipient_emails

        # Determine final status
        has_errors = "f3x_error" in results or "ie_error" in results
        results["status"] = "completed_with_errors" if has_errors else "success"
        results["http_status"] = 200  # We still return 200 for partial errors
        results["completed_at"] = datetime.now(timezone.utc).isoformat()

        gc.collect()
        _log_memory("final", results)

        _save_cron_status(session, results)
        return results

    except Exception as e:
        # Unexpected crash - save error state
        results["status"] = "crashed"
        results["http_status"] = 500
        results["crash_error"] = str(e)
        results["completed_at"] = datetime.now(timezone.utc).isoformat()

        _save_cron_status(session, results)
        return JSONResponse(status_code=500, content=results)


# -------------------------
# Root Redirect
# -------------------------

@app.get("/")
def root_redirect():
    """Redirect root to the main dashboard."""
    return RedirectResponse(url="/dashboard/3x", status_code=302)
