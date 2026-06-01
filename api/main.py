"""FastAPI application."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config
from api.auth import require_api_key
from api.staleness import plan_staleness_fields
from core.plan_recency import enrich_plan_context_row, format_minutes_ago, minutes_since
from core import store
from core.ledger import log_trade
from core.position_close import close_position
from core.portfolio_setup import clear_weekly_recommendations, fresh_start, reset_portfolio_to_cash
from core.portfolio import compute_nav
from core.ticker_names import enrich_nav_state, resolve_company_names
from core.rules import DEFAULT_RULES, parse_rules
from core.snapshots import get_latest_snapshot
from performance_agent import PerformanceAgent
from pipeline.daily_analysis import run_daily_analysis
from trader_agent import TraderAgent

app = FastAPI(title="Stock Trading Platform", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    from core.seed import ensure_seeded

    store.init_database()
    ensure_seeded()


class TradeRequest(BaseModel):
    portfolio_id: int = 1
    side: str
    ticker: str
    instrument_type: str = "stock"
    quantity: float
    price: float
    fees: float = 0
    strike: Optional[float] = None
    expiry: Optional[str] = None
    plan_item_id: Optional[int] = None
    member_id: Optional[int] = None
    note: Optional[str] = None
    weekly_plan_id: Optional[int] = None


class DecisionRequest(BaseModel):
    member_id: int = 1
    decision: str
    note: Optional[str] = None


class PortfolioCreate(BaseModel):
    name: str
    initial_cash: float = 1000.0


class PortfolioResetRequest(BaseModel):
    portfolio_id: int = 1
    cash_usd: float = 1000.0


class PositionImportRow(BaseModel):
    ticker: str
    quantity: float
    avg_cost: float
    instrument_type: str = "stock"


class PortfolioImportRequest(BaseModel):
    portfolio_id: int = 1
    cash_usd: float = 1000.0
    positions: list[PositionImportRow] = []


class PortfolioImportCsvRequest(BaseModel):
    portfolio_id: int = 1
    cash_usd: float = 1000.0
    csv_text: str


class ClosePositionRequest(BaseModel):
    portfolio_id: int = 1
    ticker: str
    instrument_type: str = "stock"
    resolution: str = Field(
        description="sell = sell stock or sell-to-close option; expire_worthless = option expires at $0"
    )
    quantity: Optional[float] = None
    price: Optional[float] = Field(
        default=None,
        description="Fill price per share, or premium per share for options. Omit to use last mark.",
    )
    note: Optional[str] = None
    member_id: int = 1


class FreshStartRequest(BaseModel):
    portfolio_id: int = 1
    cash_usd: float = 1000.0


class ClearRecommendationsRequest(BaseModel):
    portfolio_id: int = 1


def _default_portfolio_id() -> int:
    session = store.get_active_session()
    if not session:
        raise HTTPException(503, "No active session")
    ports = store.get_portfolios(session["id"])
    if not ports:
        raise HTTPException(503, "No portfolios")
    return int(ports[0]["id"])


def _trading_plan_run_payload(plan: dict) -> dict:
    stale = plan_staleness_fields(plan["based_on_analysis_at"])
    items = plan.get("items") or []
    no_changes = bool(plan.get("no_changes") or plan.get("no_trade_week"))
    return {
        **plan,
        **stale,
        "weekly_plan_id": plan.get("weekly_plan_id"),
        "trading_plan_id": plan.get("weekly_plan_id"),
        "item_count": len(items),
        "no_changes": no_changes,
        "no_trade_week": no_changes,
        "summary": plan.get("summary"),
        "generated_at": plan.get("generated_at"),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/dashboard")
def dashboard(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    nav = enrich_nav_state(compute_nav(pid))
    snap = get_latest_snapshot(pid)
    run = store.get_latest_analysis_run()
    plan = store.get_current_weekly_plan(pid)
    pending = 0
    if plan:
        pending = sum(1 for i in plan.get("items", []) if i.get("status") == "pending")
    session = store.get_active_session()
    from core.db import db_session

    port_row = None
    trade_count = 0
    with db_session() as conn:
        port_row = conn.execute("SELECT initial_cash FROM portfolios WHERE id = ?", (pid,)).fetchone()
        trade_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM ledger_events WHERE portfolio_id = ?", (pid,)
            ).fetchone()["c"]
            or 0
        )
    positions = nav.get("positions") or []
    return {
        "portfolio_id": pid,
        "nav": nav,
        "latest_snapshot": snap,
        "initial_cash": float(port_row["initial_cash"]) if port_row else None,
        "trade_count": trade_count,
        "is_cash_only": trade_count == 0 and len(positions) == 0,
        "last_analysis_run_at": run["run_at"] if run else None,
        "last_analysis_run_id": run["id"] if run else None,
        "pending_decisions": pending,
        "session_started_at": session["started_at"] if session else None,
        "has_weekly_plan": plan is not None,
        "has_trading_plan": plan is not None,
        "last_trading_plan_at": plan.get("plan_at") if plan else None,
        "last_trading_plan_ago": format_minutes_ago(minutes_since(plan["plan_at"]))
        if plan and minutes_since(plan["plan_at"]) is not None
        else None,
    }


def _progress_sse(worker):
    """Stream progress from an async worker(on_progress) -> done payload dict."""

    async def event_generator():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue()

        def on_progress(event: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def run_worker() -> None:
            try:
                payload = await worker(on_progress)
                await queue.put({"type": "done", **payload})
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})

        task = asyncio.create_task(run_worker())
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _daily_run_sse():
    async def worker(on_progress):
        result = await run_daily_analysis(
            persist=True,
            export=True,
            run_type="manual",
            on_progress=on_progress,
        )
        return {
            "analysis_run_id": result.analysis_run_id,
            "story_count": result.story_count,
            "article_count": result.article_count,
            "export_path": result.export_path,
        }

    return _progress_sse(worker)


def _weekly_run_sse(portfolio_id: int, analysis_run_id: Optional[int]):
    async def worker(on_progress):
        agent = TraderAgent()
        plan = await asyncio.to_thread(
            agent.build_weekly_plan,
            portfolio_id,
            analysis_run_id=analysis_run_id,
            trigger_type="manual",
            on_progress=on_progress,
        )
        return _trading_plan_run_payload(plan)

    return _progress_sse(worker)


@app.post("/runs/daily", dependencies=[Depends(require_api_key)])
async def trigger_daily(stream: bool = Query(False, description="Stream progress as SSE")):
    if stream:
        return _daily_run_sse()
    result = await run_daily_analysis(persist=True, export=True, run_type="manual")
    return {
        "analysis_run_id": result.analysis_run_id,
        "story_count": result.story_count,
        "article_count": result.article_count,
        "export_path": result.export_path,
    }


@app.post("/runs/weekly", dependencies=[Depends(require_api_key)])
async def trigger_weekly(
    portfolio_id: Optional[int] = None,
    analysis_run_id: Optional[int] = None,
    stream: bool = Query(False, description="Stream progress as SSE"),
):
    pid = portfolio_id or _default_portfolio_id()
    if stream:
        return _weekly_run_sse(pid, analysis_run_id)
    agent = TraderAgent()
    plan = await asyncio.to_thread(
        agent.build_weekly_plan,
        pid,
        analysis_run_id=analysis_run_id,
        trigger_type="manual",
    )
    return _trading_plan_run_payload(plan)


@app.post("/runs/trading-plan", dependencies=[Depends(require_api_key)])
async def trigger_trading_plan(
    portfolio_id: Optional[int] = None,
    analysis_run_id: Optional[int] = None,
    stream: bool = Query(False, description="Stream progress as SSE"),
):
    return await trigger_weekly(
        portfolio_id=portfolio_id,
        analysis_run_id=analysis_run_id,
        stream=stream,
    )


@app.get("/stories")
def get_stories(run_id: Optional[int] = None):
    run = store.get_analysis_run(run_id) if run_id else store.get_latest_analysis_run()
    if not run:
        return {"stories": [], "run_at": None}
    return {"run_id": run["id"], "run_at": run["run_at"], "stories": run.get("payload", [])}


@app.post("/plans/clear", dependencies=[Depends(require_api_key)])
def clear_recommendations(body: ClearRecommendationsRequest):
    """Delete all trading plans and decisions; portfolio ledger is unchanged."""
    cleared = clear_weekly_recommendations(body.portfolio_id)
    return {"ok": True, "portfolio_id": body.portfolio_id, "weekly_plans_cleared": cleared}


@app.get("/plans/current")
def get_current_plan(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    plan = store.get_current_weekly_plan(pid)
    if not plan:
        return {"plan": None}
    enriched = enrich_plan_context_row(plan)
    stale = plan_staleness_fields(plan["based_on_analysis_at"])
    payload = plan.get("payload") or {}
    no_changes = bool(
        enriched.get("no_changes")
        or payload.get("no_changes")
        or payload.get("no_trade_week")
    )
    mins = minutes_since(plan.get("plan_at") or "")
    return {
        "plan": enriched,
        **stale,
        "no_changes": no_changes,
        "plan_at": plan.get("plan_at"),
        "plan_ago_label": format_minutes_ago(mins) if mins is not None else None,
    }


@app.patch("/plans/items/{item_id}/decision", dependencies=[Depends(require_api_key)])
def decide_item(item_id: int, body: DecisionRequest):
    if body.decision not in ("accepted", "rejected", "deferred"):
        raise HTTPException(400, detail="decision must be accepted, rejected, or deferred")

    store.record_decision(item_id, body.member_id, body.decision, body.note)
    return {
        "ok": True,
        "plan_item_id": item_id,
        "decision": body.decision,
    }


@app.get("/tickers/names")
def ticker_names(symbols: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT")):
    parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return {"names": resolve_company_names(parts)}


@app.post("/trades", dependencies=[Depends(require_api_key)])
def post_trade(body: TradeRequest):
    result = log_trade(
        body.portfolio_id,
        side=body.side,
        ticker=body.ticker,
        instrument_type=body.instrument_type,
        quantity=body.quantity,
        price=body.price,
        fees=body.fees,
        strike=body.strike,
        expiry=body.expiry,
        plan_item_id=body.plan_item_id,
        member_id=body.member_id,
        note=body.note,
        weekly_plan_id=body.weekly_plan_id,
    )
    if not result.get("ok"):
        raise HTTPException(400, detail=result)
    return result


@app.get("/portfolio")
def get_portfolio(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    port = None
    session = store.get_active_session()
    for p in store.get_portfolios(session["id"], active_only=False):
        if p["id"] == pid:
            port = p
    from core.db import db_session

    trade_count = 0
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM ledger_events WHERE portfolio_id = ?",
            (pid,),
        ).fetchone()
        trade_count = int(row["c"] or 0)
    state = enrich_nav_state(compute_nav(pid))
    return {
        "portfolio": port,
        "state": state,
        "initial_cash": float(port["initial_cash"]) if port else None,
        "trade_count": trade_count,
        "is_cash_only": trade_count == 0 and len(state.get("positions", [])) == 0,
    }


@app.post("/portfolio/reset", dependencies=[Depends(require_api_key)])
def reset_portfolio(body: PortfolioResetRequest):
    try:
        return reset_portfolio_to_cash(body.portfolio_id, body.cash_usd)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e


@app.post("/portfolio/fresh-start", dependencies=[Depends(require_api_key)])
def portfolio_fresh_start(body: FreshStartRequest):
    try:
        return fresh_start(body.portfolio_id, body.cash_usd)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e


@app.post("/portfolio/positions/close", dependencies=[Depends(require_api_key)])
def close_portfolio_position(body: ClosePositionRequest):
    result = close_position(
        body.portfolio_id,
        ticker=body.ticker,
        instrument_type=body.instrument_type,
        resolution=body.resolution,
        quantity=body.quantity,
        price=body.price,
        member_id=body.member_id,
        note=body.note,
    )
    if not result.get("ok"):
        raise HTTPException(400, detail=result)
    return result


@app.post("/portfolio/import", dependencies=[Depends(require_api_key)])
def import_portfolio(body: PortfolioImportRequest):
    from core.portfolio_setup import import_starting_state

    positions = [p.model_dump() for p in body.positions]
    try:
        return import_starting_state(body.portfolio_id, body.cash_usd, positions)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e


@app.post("/portfolio/import-csv", dependencies=[Depends(require_api_key)])
def import_portfolio_csv(body: PortfolioImportCsvRequest):
    from core.portfolio_setup import import_starting_state, parse_positions_csv

    positions = parse_positions_csv(body.csv_text)
    try:
        return import_starting_state(body.portfolio_id, body.cash_usd, positions)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e


@app.get("/history")
def history(limit: int = 50):
    return {"events": store.get_timeline(1, limit=limit)}


@app.get("/settings/rules")
def get_rules(portfolio_id: Optional[int] = None):
    session = store.get_active_session()
    if not session:
        return {"rules": DEFAULT_RULES}
    pid = portfolio_id or _default_portfolio_id()
    return {
        "rules": store.get_portfolio_rules(pid, session["rules_json"]),
        "session": {"name": session["name"], "started_at": session["started_at"], "status": session["status"]},
    }


@app.post("/portfolios", dependencies=[Depends(require_api_key)])
def create_portfolio(body: PortfolioCreate):
    session = store.get_active_session()
    if not session:
        raise HTTPException(503, "No active session")
    pid = store.add_portfolio(session["id"], body.name, body.initial_cash)
    from core.snapshots import save_snapshot
    save_snapshot(pid)
    return {"portfolio_id": pid, "name": body.name, "initial_cash": body.initial_cash}


@app.get("/members")
def list_members():
    return {"members": store.get_members()}


@app.post("/insights/generate", dependencies=[Depends(require_api_key)])
def generate_insights(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    agent = PerformanceAgent()
    report = agent.generate_lessons_report(pid)
    return report


@app.get("/insights/latest")
def latest_insights(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    report = store.get_latest_insight(1, pid)
    return {"report": report}
