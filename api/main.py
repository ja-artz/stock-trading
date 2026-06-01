"""FastAPI application."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
from api.auth import require_api_key
from api.staleness import plan_staleness_fields
from core import store
from core.ledger import log_trade
from core.portfolio import compute_nav
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


def _default_portfolio_id() -> int:
    session = store.get_active_session()
    if not session:
        raise HTTPException(503, "No active session")
    ports = store.get_portfolios(session["id"])
    if not ports:
        raise HTTPException(503, "No portfolios")
    return int(ports[0]["id"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/dashboard")
def dashboard(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    nav = compute_nav(pid)
    snap = get_latest_snapshot(pid)
    run = store.get_latest_analysis_run()
    plan = store.get_current_weekly_plan(pid)
    pending = 0
    if plan:
        pending = sum(1 for i in plan.get("items", []) if i.get("status") == "pending")
    session = store.get_active_session()
    return {
        "portfolio_id": pid,
        "nav": nav,
        "latest_snapshot": snap,
        "last_analysis_run_at": run["run_at"] if run else None,
        "last_analysis_run_id": run["id"] if run else None,
        "pending_decisions": pending,
        "session_started_at": session["started_at"] if session else None,
        "has_weekly_plan": plan is not None,
    }


@app.post("/runs/daily", dependencies=[Depends(require_api_key)])
async def trigger_daily():
    result = await run_daily_analysis(persist=True, export=True, run_type="manual")
    return {
        "analysis_run_id": result.analysis_run_id,
        "story_count": result.story_count,
        "export_path": result.export_path,
    }


@app.post("/runs/weekly", dependencies=[Depends(require_api_key)])
def trigger_weekly(portfolio_id: Optional[int] = None, analysis_run_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    agent = TraderAgent()
    plan = agent.build_weekly_plan(pid, analysis_run_id=analysis_run_id, trigger_type="manual")
    stale = plan_staleness_fields(plan["based_on_analysis_at"])
    return {**plan, **stale}


@app.get("/stories")
def get_stories(run_id: Optional[int] = None):
    run = store.get_analysis_run(run_id) if run_id else store.get_latest_analysis_run()
    if not run:
        return {"stories": [], "run_at": None}
    return {"run_id": run["id"], "run_at": run["run_at"], "stories": run.get("payload", [])}


@app.get("/plans/current")
def get_current_plan(portfolio_id: Optional[int] = None):
    pid = portfolio_id or _default_portfolio_id()
    plan = store.get_current_weekly_plan(pid)
    if not plan:
        return {"plan": None}
    stale = plan_staleness_fields(plan["based_on_analysis_at"])
    return {"plan": plan, **stale}


@app.patch("/plans/items/{item_id}/decision", dependencies=[Depends(require_api_key)])
def decide_item(item_id: int, body: DecisionRequest):
    if body.decision not in ("accepted", "rejected", "deferred"):
        raise HTTPException(400, detail="decision must be accepted, rejected, or deferred")
    store.record_decision(item_id, body.member_id, body.decision, body.note)
    return {"ok": True, "plan_item_id": item_id, "decision": body.decision}


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
    return {"portfolio": port, "state": compute_nav(pid)}


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
