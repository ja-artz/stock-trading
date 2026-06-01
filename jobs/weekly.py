"""Generate weekly trader plans for all active portfolios."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.store import get_active_session, get_portfolios, init_database
from trader_agent import TraderAgent


def main():
    parser = argparse.ArgumentParser(description="Generate weekly trader plans")
    parser.add_argument("--portfolio-id", type=int, help="Single portfolio id")
    parser.add_argument("--analysis-run-id", type=int, help="Use specific analysis run")
    parser.add_argument("--trigger", default="manual", choices=["manual", "scheduled"])
    args = parser.parse_args()

    init_database()
    session = get_active_session()
    if not session:
        print("No active session. Run: uv run python scripts/seed_household.py")
        sys.exit(1)

    portfolios = get_portfolios(session["id"], active_only=True)
    if args.portfolio_id:
        portfolios = [p for p in portfolios if p["id"] == args.portfolio_id]
        if not portfolios:
            print(f"Portfolio {args.portfolio_id} not found.")
            sys.exit(1)

    agent = TraderAgent()
    for port in portfolios:
        print(f"\nGenerating plan for portfolio {port['id']} ({port['name']})...")
        try:
            plan = agent.build_weekly_plan(
                port["id"],
                analysis_run_id=args.analysis_run_id,
                trigger_type=args.trigger,
            )
            print(f"  Plan id: {plan.get('weekly_plan_id')}")
            print(f"  Summary: {plan.get('summary', '')[:200]}")
            print(f"  Items: {len(plan.get('items') or [])}")
        except Exception as e:
            print(f"  Error: {e}")
            sys.exit(1)

    print("\nWeekly plan generation complete.")


if __name__ == "__main__":
    main()
