import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { RunProgressPanel } from "@/components/RunProgressPanel";
import { useDailyRun } from "@/hooks/useDailyRun";
import { useTradingPlanRun } from "@/hooks/useTradingPlanRun";
import { Play, Calendar, Newspaper, Briefcase, AlertCircle } from "lucide-react";

export function HomePage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const dailyRun = useDailyRun();
  const planRun = useTradingPlanRun();

  const load = useCallback(() => {
    api.get<Dashboard>("/dashboard").then(setData).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runDaily = () => dailyRun.run(load);

  const runTradingPlan = () => planRun.run(load);

  if (error && !data) {
    return (
      <Alert className="border-red-200 bg-red-50">
        <AlertCircle className="h-4 w-4 text-red-600" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!data) return <p className="text-muted-foreground">Loading…</p>;

  const nav = data.nav;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Portfolio</h1>
          <p className="text-gray-600 mt-1">
            Household book · paper tracking (Sofi execution)
            {data.is_cash_only ? " · $1000 cash ready" : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={runDaily} disabled={!!busy || dailyRun.busy}>
            <Play className="w-4 h-4 mr-2" />
            {dailyRun.busy ? "Running…" : "Run daily analysis"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={runTradingPlan}
            disabled={!!busy || dailyRun.busy || planRun.busy}
          >
            <Calendar className="w-4 h-4 mr-2" />
            {planRun.busy ? "Generating…" : "Generate trading plan"}
          </Button>
        </div>
      </div>

      {!data.is_cash_only && (
        <Alert className="border-amber-200 bg-amber-50">
          <AlertCircle className="h-4 w-4 text-amber-600" />
          <AlertDescription className="text-amber-900">
            Book includes {data.trade_count ?? 0} logged trade(s)
            {nav.positions.length ? ` and ${nav.positions.length} open position(s)` : ""}. NAV uses live prices
            (yfinance), not mock data.{" "}
            <Link to="/settings" className="underline font-medium">
              Reset to $1,000 cash
            </Link>{" "}
            in Settings if you want a clean start.
          </AlertDescription>
        </Alert>
      )}

      <RunProgressPanel
        open={dailyRun.busy || dailyRun.logs.length > 0}
        busy={dailyRun.busy}
        stageLabel={dailyRun.stageLabel}
        logs={dailyRun.logs}
        error={dailyRun.error}
        titles={{
          running: "Daily analysis in progress",
          failed: "Analysis failed",
          done: "Analysis complete",
        }}
        hint="This can take several minutes — news fetch, story selection, and three analyst personas per story."
      />

      <RunProgressPanel
        open={planRun.busy || planRun.logs.length > 0}
        busy={planRun.busy}
        stageLabel={planRun.stageLabel}
        logs={planRun.logs}
        error={planRun.error}
        titles={{
          running: "Trading plan in progress",
          failed: "Plan generation failed",
          done: "Trading plan complete",
        }}
        hint="On-demand plan from latest analysis and holdings. May recommend no changes if a recent plan still applies."
      />

      {(data.pending_decisions > 0 || !data.last_analysis_run_at) && (
        <Alert className="border-blue-200 bg-blue-50">
          <AlertCircle className="h-4 w-4 text-blue-600" />
          <AlertDescription className="text-blue-900">
            {data.pending_decisions > 0 && `${data.pending_decisions} recommendation(s) pending review. `}
            {data.last_analysis_run_at
              ? `Last analysis: ${new Date(data.last_analysis_run_at).toLocaleString()}`
              : "No analysis run yet — run daily analysis to populate stories."}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">NAV</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${nav.nav_usd.toFixed(2)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Cash</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${nav.cash_usd.toFixed(2)}</div>
            <p className="text-xs text-gray-500 mt-1">{nav.cash_pct.toFixed(1)}% of portfolio</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Invested</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${nav.invested_usd.toFixed(2)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Positions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{nav.positions.length}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Link to="/stories">
          <Card className="hover:border-blue-300 transition-colors cursor-pointer h-full">
            <CardContent className="pt-6 flex items-center gap-3">
              <div className="p-2 bg-blue-100 rounded-lg">
                <Newspaper className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <p className="font-medium">Stories</p>
                <p className="text-sm text-gray-500">Latest analyst views</p>
              </div>
            </CardContent>
          </Card>
        </Link>
        <Link to="/recommendations">
          <Card className="hover:border-blue-300 transition-colors cursor-pointer h-full">
            <CardContent className="pt-6 flex items-center gap-3">
              <div className="p-2 bg-amber-100 rounded-lg">
                <Calendar className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <p className="font-medium">Trading plan</p>
                <p className="text-sm text-gray-500">
                  {data.pending_decisions
                    ? `${data.pending_decisions} pending`
                    : data.has_trading_plan
                      ? data.last_trading_plan_ago
                        ? `Updated ${data.last_trading_plan_ago}`
                        : "Review plan"
                      : "Not generated"}
                </p>
              </div>
            </CardContent>
          </Card>
        </Link>
        <Link to="/portfolio">
          <Card className="hover:border-blue-300 transition-colors cursor-pointer h-full">
            <CardContent className="pt-6 flex items-center gap-3">
              <div className="p-2 bg-green-100 rounded-lg">
                <Briefcase className="w-5 h-5 text-green-600" />
              </div>
              <div>
                <p className="font-medium">Holdings</p>
                <p className="text-sm text-gray-500">Log Sofi trades</p>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>
    </div>
  );
}
