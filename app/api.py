# app/api.py
from __future__ import annotations

from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Any, Dict
from pathlib import Path

from fastapi import FastAPI, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, col

from .settings import load_settings
from .db import make_engine, init_db
from .schemas import FilingF3X, IEScheduleE

# --- App + DB bootstrap ---
settings = load_settings()
engine = make_engine(settings)
init_db(engine)

app = FastAPI(title="FEC Monitor", version="0.2.0")
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

    return templates.TemplateResponse(
        "dashboard_3x.html",
        {
            "request": request,
            "rows": rows,
            "threshold": threshold,
            "day_et": start_utc.astimezone(ET).date(),
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
    start_utc, end_utc = et_today_utc_bounds()

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
            "day_et": start_utc.astimezone(ET).date(),
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
