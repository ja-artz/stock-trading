import { useCallback, useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { TrendingUp, TrendingDown, FileText, Flame, Target, Shield, Info } from "lucide-react";
import type {
  InsightsPerformance,
  InsightsPersonas,
  InsightsPeriod,
} from "@/api/client";

const PERIOD_OPTIONS: { value: InsightsPeriod; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "ytd", label: "Year to date" },
  { value: "all", label: "All time" },
];

const PERSONA_KEYS = ["aggressive", "moderate", "minimal_risk"] as const;
const PERSONA_ICONS = {
  aggressive: Flame,
  moderate: Target,
  minimal_risk: Shield,
} as const;

function PersonaConsensusIcons({
  consensus,
  matched,
}: {
  consensus?: Record<string, boolean> | null;
  matched?: string[];
}) {
  return (
    <div className="flex gap-1">
      {PERSONA_KEYS.map((key) => {
        const Icon = PERSONA_ICONS[key];
        const agreed = Boolean(consensus?.[key]) || (matched?.includes(key) ?? false);
        return (
          <div
            key={key}
            title={agreed ? `${key} agreed` : `${key} did not agree`}
            className={`w-6 h-6 rounded-md flex items-center justify-center ${
              agreed ? "bg-blue-100 text-blue-700 ring-1 ring-blue-200" : "bg-gray-100 text-gray-400"
            }`}
          >
            <Icon className="w-3 h-3" />
          </div>
        );
      })}
    </div>
  );
}

function personaBadgeVariant(persona: string): "default" | "secondary" | "outline" {
  if (persona === "aggressive") return "default";
  if (persona === "moderate") return "secondary";
  return "outline";
}

export function InsightsPage() {
  const [period, setPeriod] = useState<InsightsPeriod>("30d");
  const [performance, setPerformance] = useState<InsightsPerformance | null>(null);
  const [personas, setPersonas] = useState<InsightsPersonas | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadAnalytics = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const q = `?period=${period}`;
      const [perf, pers, latest] = await Promise.all([
        api.get<InsightsPerformance>(`/insights/performance${q}`),
        api.get<InsightsPersonas>(`/insights/personas${q}`),
        api.get<{ report: Record<string, unknown> | null }>("/insights/latest"),
      ]);
      setPerformance(perf);
      setPersonas(pers);
      const r = latest.report;
      if (r?.payload) setReport(r.payload as Record<string, unknown>);
      else if (r) setReport(r as Record<string, unknown>);
      else setReport(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  const generate = async () => {
    setBusy(true);
    try {
      const r = await api.post<Record<string, unknown>>("/insights/generate");
      setReport(r);
    } finally {
      setBusy(false);
    }
  };

  const summary = String(report?.summary || "");
  const worked = (report?.what_worked as string[]) || [];
  const failed = (report?.what_failed as string[]) || [];
  const improvements = (report?.process_improvements as string[]) || [];
  const risk = (report?.risk_observations as string[]) || [];

  const perfSummary = performance?.summary;
  const benchmarkLabel = performance?.benchmark_symbol || "SPY";
  const periodLabel = PERIOD_OPTIONS.find((o) => o.value === period)?.label ?? period;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Insights</h1>
          <p className="text-gray-600 mt-1">
            Cumulative return vs {benchmarkLabel} from period start (0% baseline) · daily marks
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Select value={period} onValueChange={(v) => setPeriod(v as InsightsPeriod)}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PERIOD_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <Tabs defaultValue="performance" className="w-full">
        <TabsList>
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="personas">Personas</TabsTrigger>
          <TabsTrigger value="lessons">Lessons</TabsTrigger>
        </TabsList>

        <TabsContent value="performance" className="space-y-6 mt-6">
          {loading && !performance ? (
            <p className="text-muted-foreground text-sm">Loading performance…</p>
          ) : performance ? (
            <>
              {performance.chart_mode === "since_first_nav" && (
                <Alert className="border-blue-200 bg-blue-50">
                  <Info className="h-4 w-4 text-blue-600" />
                  <AlertDescription className="text-blue-900">
                    Startup period: chart and returns are measured from your first NAV day (
                    {performance.first_nav_date || performance.chart_baseline_date}), not the full{" "}
                    {periodLabel} window. After {performance.days_until_period_chart ?? 0} more day
                    {(performance.days_until_period_chart ?? 0) === 1 ? "" : "s"} of history, the
                    selector will match calendar ranges (7d, 30d, etc.).
                  </AlertDescription>
                </Alert>
              )}
              <Card>
                <CardHeader>
                  <CardTitle>
                    Performance vs {benchmarkLabel}
                    {!performance.benchmarks_available && (
                      <span className="text-sm font-normal text-gray-500 ml-2">
                        (benchmark data populates after daily snapshots)
                      </span>
                    )}
                  </CardTitle>
                  <p className="text-sm text-gray-600 mt-1">
                    Cumulative % since{" "}
                    {performance.chart_baseline_date || "period start"} (0% baseline).
                    {performance.chart_mode === "period"
                      ? ` Selected range starts ${performance.chart_effective_start || "—"}.`
                      : performance.first_nav_date
                        ? ` Comparing from first book NAV (${performance.first_nav_date}).`
                        : null}
                  </p>
                  {perfSummary?.spy_since_prev_close_pct != null && (
                    <p className="text-sm text-gray-500 mt-1">
                      {benchmarkLabel} since prior close:{" "}
                      <span
                        className={
                          perfSummary.spy_since_prev_close_pct >= 0
                            ? "text-green-600 font-medium"
                            : "text-red-600 font-medium"
                        }
                      >
                        {perfSummary.spy_since_prev_close_pct >= 0 ? "+" : ""}
                        {perfSummary.spy_since_prev_close_pct}%
                      </span>
                      {perfSummary.spy_last_2_sessions_pct != null && (
                        <>
                          {" "}
                          · last 2 sessions:{" "}
                          <span
                            className={
                              perfSummary.spy_last_2_sessions_pct >= 0
                                ? "text-green-600 font-medium"
                                : "text-red-600 font-medium"
                            }
                          >
                            {perfSummary.spy_last_2_sessions_pct >= 0 ? "+" : ""}
                            {perfSummary.spy_last_2_sessions_pct}%
                          </span>
                        </>
                      )}
                      {perfSummary.spy_period_return_pct != null && (
                        <>
                          {" "}
                          · {periodLabel} total:{" "}
                          {perfSummary.spy_period_return_pct >= 0 ? "+" : ""}
                          {perfSummary.spy_period_return_pct}%
                        </>
                      )}
                    </p>
                  )}
                </CardHeader>
                <CardContent>
                  {performance.chart.length === 0 ? (
                    <p className="text-sm text-gray-600 py-8 text-center">
                      No NAV or benchmark data for this period yet. Log a trade (creates a snapshot) or
                      wait for benchmark backfill.
                    </p>
                  ) : (
                    <div style={{ width: "100%", height: 320 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={performance.chart}>
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                          <YAxis
                            tick={{ fontSize: 11 }}
                            tickFormatter={(v: number) => `${v}%`}
                            domain={["auto", "auto"]}
                          />
                          <ReferenceLine y={0} stroke="#9ca3af" strokeWidth={1} />
                          <Tooltip
                            formatter={(value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`}
                          />
                          <Legend />
                          <Line
                            type="linear"
                            dataKey="portfolio"
                            stroke="#ea580c"
                            strokeWidth={2}
                            name="Portfolio"
                            dot={false}
                          />
                          {performance.benchmarks_available && (
                            <Line
                              type="linear"
                              dataKey="spy"
                              stroke="#2563eb"
                              strokeWidth={2}
                              name={benchmarkLabel}
                              dot={false}
                            />
                          )}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-gray-600">Total return</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {perfSummary?.total_return_pct != null ? (
                      <>
                        <div
                          className={`text-2xl font-bold ${
                            perfSummary.total_return_pct >= 0 ? "text-green-600" : "text-red-600"
                          }`}
                        >
                          {perfSummary.total_return_pct >= 0 ? "+" : ""}
                          {perfSummary.total_return_pct}%
                        </div>
                        {perfSummary.total_return_usd != null && (
                          <p className="text-xs text-gray-500 mt-1">
                            {perfSummary.total_return_usd >= 0 ? "+" : ""}$
                            {perfSummary.total_return_usd.toFixed(2)} NAV change
                          </p>
                        )}
                      </>
                    ) : (
                      <p className="text-sm text-gray-500">—</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-gray-600">
                      {benchmarkLabel} (period)
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {perfSummary?.spy_period_return_pct != null ? (
                      <>
                        <div
                          className={`text-2xl font-bold ${
                            perfSummary.spy_period_return_pct >= 0
                              ? "text-green-600"
                              : "text-red-600"
                          }`}
                        >
                          {perfSummary.spy_period_return_pct >= 0 ? "+" : ""}
                          {perfSummary.spy_period_return_pct}%
                        </div>
                        {perfSummary.vs_spy_pct != null && (
                          <p className="text-xs text-gray-500 mt-1">
                            Alpha vs you: {perfSummary.vs_spy_pct >= 0 ? "+" : ""}
                            {perfSummary.vs_spy_pct}%
                          </p>
                        )}
                      </>
                    ) : (
                      <p className="text-sm text-gray-500">—</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-gray-600">Win rate</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {perfSummary?.win_rate_pct != null ? (
                      <>
                        <div className="text-2xl font-bold">{perfSummary.win_rate_pct}%</div>
                        <p className="text-xs text-gray-500 mt-1">
                          {perfSummary.wins}W / {perfSummary.losses}L closed
                        </p>
                      </>
                    ) : (
                      <p className="text-sm text-gray-500">No closed trades</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-gray-600">Avg hold</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {perfSummary?.avg_hold_days != null ? (
                      <div className="text-2xl font-bold">{perfSummary.avg_hold_days} days</div>
                    ) : (
                      <p className="text-sm text-gray-500">—</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Closed trades</CardTitle>
                </CardHeader>
                <CardContent>
                  {performance.closed_trades.length === 0 ? (
                    <p className="text-sm text-gray-600 py-4 text-center">
                      No closed round-trips in this period.
                    </p>
                  ) : (
                    <div className="border rounded-lg overflow-hidden">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Date</TableHead>
                            <TableHead>Ticker</TableHead>
                            <TableHead className="text-right">Entry</TableHead>
                            <TableHead className="text-right">Exit</TableHead>
                            <TableHead className="text-right">Hold</TableHead>
                            <TableHead>Personas</TableHead>
                            <TableHead>Followed rec</TableHead>
                            <TableHead className="text-right">Realized P&amp;L</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {performance.closed_trades.map((trade) => (
                            <TableRow key={trade.id}>
                              <TableCell className="text-sm">{trade.date}</TableCell>
                              <TableCell>
                                <div className="font-mono font-medium">{trade.ticker}</div>
                                <div className="text-xs text-gray-500">{trade.instrument_type}</div>
                              </TableCell>
                              <TableCell className="text-right">${trade.entry_price.toFixed(2)}</TableCell>
                              <TableCell className="text-right">${trade.exit_price.toFixed(2)}</TableCell>
                              <TableCell className="text-right">{trade.hold_days}d</TableCell>
                              <TableCell>
                                <PersonaConsensusIcons
                                  consensus={trade.persona_consensus}
                                  matched={trade.matched_personas}
                                />
                              </TableCell>
                              <TableCell>
                                {trade.followed_rec ? (
                                  <Badge variant="default" className="text-xs">
                                    Yes
                                  </Badge>
                                ) : (
                                  <Badge variant="outline" className="text-xs">
                                    No
                                  </Badge>
                                )}
                              </TableCell>
                              <TableCell className="text-right">
                                <div className="flex items-center justify-end gap-2">
                                  {trade.realized_pnl > 0 ? (
                                    <TrendingUp className="w-4 h-4 text-green-600" />
                                  ) : (
                                    <TrendingDown className="w-4 h-4 text-red-600" />
                                  )}
                                  <span
                                    className={
                                      trade.realized_pnl > 0
                                        ? "text-green-600 font-medium"
                                        : "text-red-600 font-medium"
                                    }
                                  >
                                    ${Math.abs(trade.realized_pnl).toFixed(2)}
                                  </span>
                                  <span className="text-gray-500 text-sm">
                                    ({trade.pnl_pct > 0 ? "+" : ""}
                                    {trade.pnl_pct.toFixed(2)}%)
                                  </span>
                                </div>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          ) : null}
        </TabsContent>

        <TabsContent value="personas" className="space-y-6 mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Persona performance</CardTitle>
              <p className="text-sm text-gray-600 mt-1">
                Performance for recommendations where this persona agreed — open positions and closed trades.
              </p>
            </CardHeader>
            <CardContent>
              {loading && !personas ? (
                <p className="text-sm text-gray-600">Loading…</p>
              ) : personas && personas.personas.length > 0 ? (
                <div className="border rounded-lg overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Persona</TableHead>
                        <TableHead className="text-right">Stance agreements</TableHead>
                        <TableHead className="text-right">Closed</TableHead>
                        <TableHead className="text-right">Open</TableHead>
                        <TableHead className="text-right">Win rate</TableHead>
                        <TableHead className="text-right">Avg return</TableHead>
                        <TableHead>Best trade</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {personas.personas.map((row) => {
                        const Icon =
                          PERSONA_ICONS[row.persona as keyof typeof PERSONA_ICONS] || Target;
                        return (
                          <TableRow key={row.persona}>
                            <TableCell>
                              <Badge variant={personaBadgeVariant(row.persona)} className="gap-1">
                                <Icon className="w-3 h-3" />
                                {row.label}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">{row.stance_agreements}</TableCell>
                            <TableCell className="text-right">{row.matched_trades}</TableCell>
                            <TableCell className="text-right">{row.active_positions}</TableCell>
                            <TableCell className="text-right">
                              {row.win_rate_pct != null ? `${row.win_rate_pct}%` : "—"}
                            </TableCell>
                            <TableCell className="text-right">
                              {row.avg_return_pct != null ? (
                                <span
                                  className={
                                    row.avg_return_pct >= 0 ? "text-green-600 font-medium" : "text-red-600"
                                  }
                                >
                                  {row.avg_return_pct >= 0 ? "+" : ""}
                                  {row.avg_return_pct}%
                                </span>
                              ) : (
                                "—"
                              )}
                            </TableCell>
                            <TableCell className="text-sm text-gray-600">
                              {row.best_trade || "—"}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <p className="text-sm text-gray-600 py-4 text-center">
                  No persona-matched positions or closed trades yet.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="lessons" className="space-y-6 mt-6">
          <div className="flex justify-end">
            <Button onClick={generate} disabled={busy}>
              <FileText className="w-4 h-4 mr-2" />
              {busy ? "Generating…" : "Generate lessons report"}
            </Button>
          </div>
          {!report ? (
            <Card>
              <CardContent className="py-8 text-center text-gray-600">
                No lessons report yet. Log trades and decisions, then generate.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Lessons learned</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                {summary && <p>{summary}</p>}
                {worked.length > 0 && (
                  <div>
                    <p className="font-medium mb-1">What worked</p>
                    <ul className="list-disc list-inside text-gray-600">
                      {worked.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {failed.length > 0 && (
                  <div>
                    <p className="font-medium mb-1">What failed</p>
                    <ul className="list-disc list-inside text-gray-600">
                      {failed.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {improvements.length > 0 && (
                  <div>
                    <p className="font-medium mb-1">Process improvements</p>
                    <ul className="list-disc list-inside text-gray-600">
                      {improvements.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {risk.length > 0 && (
                  <div>
                    <p className="font-medium mb-1">Risk observations</p>
                    <ul className="list-disc list-inside text-gray-600">
                      {risk.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
