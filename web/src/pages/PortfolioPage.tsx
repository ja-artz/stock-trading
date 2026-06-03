import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TrendingDown, TrendingUp } from "lucide-react";
import { api, type ActionItem, type DisciplineSummary } from "@/api/client";
import { TierLegendBlock } from "@/components/TierBadge";
import { getTierDefinition } from "@/lib/tierLabels";
import { ImportPositionsDialog } from "@/components/portfolio/ImportPositionsDialog";
import { LogTradeDialog } from "@/components/portfolio/TradeDialogs";
import {
  formatInstrumentType,
  formatSignedPct,
  formatSignedUsd,
  formatUsd,
  pnlColorClass,
  portfolioPct,
  positionDetailPath,
  type PositionRow,
} from "@/lib/positionMetrics";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { TickerDisplay } from "@/components/TickerDisplay";

type PortfolioState = {
  portfolio: { id: number; name: string };
  state: {
    cash_usd: number;
    nav_usd: number;
    cash_pct: number;
    invested_usd: number;
    unrealized_pnl?: number;
    unrealized_pnl_pct?: number;
    positions: PositionRow[];
  };
  discipline?: DisciplineSummary;
  initial_cash?: number;
};

export function PortfolioPage() {
  const [data, setData] = useState<PortfolioState | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .get<PortfolioState>("/portfolio")
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!data) return <p className="text-gray-600">Loading…</p>;

  const { state, discipline } = data;
  const unrealizedPnl = state.unrealized_pnl ?? 0;
  const unrealizedPnlPct = state.unrealized_pnl_pct ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Portfolio</h1>
          <p className="text-gray-600 mt-1">Holdings &amp; trade log</p>
        </div>
        <div className="flex gap-2">
          <ImportPositionsDialog
            portfolioId={data.portfolio.id}
            initialCash={data.initial_cash ?? 1000}
            onSaved={load}
          />
          <LogTradeDialog portfolioId={data.portfolio.id} onSaved={load} />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard label="NAV" value={formatUsd(state.nav_usd)} />
        <MetricCard
          label="Cash"
          value={formatUsd(state.cash_usd)}
          sub={`${portfolioPct(state.cash_usd, state.nav_usd)} of portfolio`}
        />
        <MetricCard
          label="Invested"
          value={formatUsd(state.invested_usd)}
          sub={`${portfolioPct(state.invested_usd, state.nav_usd)} of portfolio`}
        />
        <MetricCard
          label="Unrealized P&amp;L"
          value={formatSignedUsd(unrealizedPnl)}
          sub={formatSignedPct(unrealizedPnlPct)}
          valueClass={pnlColorClass(unrealizedPnl)}
        />
      </div>

      {discipline && (
        <DisciplinePanel portfolioId={data.portfolio.id} discipline={discipline} onUpdated={load} />
      )}

      <Card>
        <CardHeader>
          <CardTitle>Positions</CardTitle>
        </CardHeader>
        <CardContent>
          {state.positions.length === 0 ? (
            <p className="text-gray-600 text-sm py-4 text-center">No open positions.</p>
          ) : (
            <div className="border rounded-lg overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ticker</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Avg Cost</TableHead>
                    <TableHead className="text-right">Market Value</TableHead>
                    <TableHead className="text-right">% of Portfolio</TableHead>
                    <TableHead className="text-right">P&amp;L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {state.positions.map((p) => {
                    const pnl = p.unrealized_pnl ?? 0;
                    const pnlPct = p.unrealized_pnl_pct ?? 0;
                    const href = positionDetailPath(p.ticker, p.instrument_type);
                    return (
                      <TableRow key={`${p.ticker}-${p.instrument_type}`} className="cursor-pointer hover:bg-gray-50">
                        <TableCell className="font-mono font-medium">
                          <Link to={href} className="block">
                            <TickerDisplay symbol={p.ticker} companyName={p.company_name} />
                          </Link>
                        </TableCell>
                        <TableCell className="text-sm text-gray-600">
                          <Link to={href} className="block">
                            {formatInstrumentType(p.instrument_type, p.expiry)}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right">
                          <Link to={href} className="block">
                            {p.is_option
                              ? `${p.quantity} contract${p.quantity === 1 ? "" : "s"}`
                              : p.quantity}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right">
                          <Link to={href} className="block">
                            {formatUsd(p.avg_cost)}
                            {p.is_option && (
                              <span className="block text-xs text-gray-500">premium total</span>
                            )}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right font-medium">
                          <Link to={href} className="block">
                            {formatUsd(p.market_value)}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right">
                          <Link to={href} className="block">
                            {portfolioPct(p.market_value, state.nav_usd)}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right">
                          <Link to={href} className="block">
                            <div className="flex items-center justify-end gap-2">
                              {pnl > 0 ? (
                                <TrendingUp className="w-4 h-4 text-green-600" />
                              ) : pnl < 0 ? (
                                <TrendingDown className="w-4 h-4 text-red-600" />
                              ) : null}
                              <span className={pnlColorClass(pnl)}>{formatSignedUsd(pnl)}</span>
                              <span className="text-gray-500 text-sm">({formatSignedPct(pnlPct)})</span>
                            </div>
                          </Link>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  <TableRow className="bg-gray-50 font-medium">
                    <TableCell>CASH</TableCell>
                    <TableCell className="text-sm text-gray-600">USD</TableCell>
                    <TableCell />
                    <TableCell />
                    <TableCell className="text-right">{formatUsd(state.cash_usd)}</TableCell>
                    <TableCell className="text-right">{portfolioPct(state.cash_usd, state.nav_usd)}</TableCell>
                    <TableCell />
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-gray-600">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${valueClass ?? ""}`}>{value}</div>
        {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

const PRIORITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  high: "bg-amber-100 text-amber-900 border-amber-200",
  medium: "bg-slate-100 text-slate-800 border-slate-200",
};

function DisciplinePanel({
  portfolioId,
  discipline,
  onUpdated,
}: {
  portfolioId: number;
  discipline: DisciplineSummary;
  onUpdated: () => void;
}) {
  const [overrideId, setOverrideId] = useState<number | null>(null);
  const [overrideNote, setOverrideNote] = useState("");
  const [err, setErr] = useState("");

  const runCheck = () => {
    api
      .post(`/runs/discipline?portfolio_id=${portfolioId}`)
      .then(() => onUpdated())
      .catch((e) => setErr(String(e)));
  };

  const setStatus = (item: ActionItem, status: string) => {
    const body: { portfolio_id: number; status: string; override_note?: string } = {
      portfolio_id: portfolioId,
      status,
    };
    if (status === "overridden") body.override_note = overrideNote;
    api
      .post(`/portfolio/discipline/items/${item.id}/status`, body)
      .then(() => {
        setOverrideId(null);
        setOverrideNote("");
        onUpdated();
      })
      .catch((e) => setErr(String(e)));
  };

  const assignTier = (p: PositionRow, tier: number) => {
    api
      .post("/portfolio/positions/assign-tier", {
        portfolio_id: portfolioId,
        ticker: p.ticker,
        instrument_type: p.instrument_type,
        capital_tier: tier,
      })
      .then(() => onUpdated())
      .catch((e) => setErr(String(e)));
  };

  const items = discipline.open_action_items || [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Tier discipline</CardTitle>
        <Button variant="outline" size="sm" onClick={runCheck}>
          Run daily check
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {err && <p className="text-sm text-red-600">{err}</p>}
        <TierLegendBlock catalog={discipline.tier_catalog} />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          {Object.entries(discipline.tier_state || {}).map(([tier, b]) => {
            const def = getTierDefinition(Number(tier)) ?? (b.name ? { name: b.name, hint: b.hint ?? "" } : null);
            return (
              <div key={tier} className="rounded border p-3">
                <p className="font-medium">
                  {def?.name ?? `Tier ${tier}`}
                  <span className="text-gray-500 font-normal"> (T{tier})</span>
                </p>
                {def?.hint && <p className="text-xs text-gray-500 mt-0.5">{def.hint}</p>}
                <p className="text-gray-600 mt-1">
                  {b.position_count}/{b.max_positions} positions · ${b.deployed_usd.toFixed(0)} / $
                  {b.budget_usd.toFixed(0)}
                </p>
              </div>
            );
          })}
        </div>
        {discipline.unmapped_positions?.length > 0 && (
          <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">
            <p className="font-medium mb-2">Unmapped positions (assign tier)</p>
            {discipline.unmapped_positions.map((p) => (
              <div key={`${p.ticker}-${p.instrument_type}`} className="flex items-center gap-2 py-1">
                <TickerDisplay symbol={p.ticker} companyName={p.company_name} />
                {[1, 2, 3].map((t) => {
                  const def = getTierDefinition(t);
                  return (
                    <Button
                      key={t}
                      size="sm"
                      variant="outline"
                      title={def?.summary}
                      onClick={() => assignTier(p, t)}
                    >
                      {def?.name ?? `T${t}`}
                    </Button>
                  );
                })}
              </div>
            ))}
          </div>
        )}
        {items.length === 0 ? (
          <p className="text-gray-600 text-sm">No open discipline actions.</p>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li
                key={item.id}
                className={`rounded border p-3 text-sm ${PRIORITY_STYLES[item.priority] || PRIORITY_STYLES.medium}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <span className="font-medium uppercase text-xs">{item.priority}</span>
                    <p className="font-medium">
                      {(item.detail?.ticker as string) || item.ticker || "—"} · {item.action.replace(/_/g, " ")}
                    </p>
                    <p className="text-gray-700">{item.reason_code.replace(/_/g, " ")}</p>
                    {item.detail?.pl_pct != null && (
                      <p className="text-gray-600">
                        P/L {Number(item.detail.pl_pct).toFixed(1)}% · held {String(item.detail.days_held)}d
                      </p>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="outline" onClick={() => setStatus(item, "acknowledged")}>
                      Ack
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setStatus(item, "executed")}>
                      Done
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setOverrideId(item.id)}>
                      Override
                    </Button>
                  </div>
                </div>
                {overrideId === item.id && (
                  <div className="mt-2 flex gap-2">
                    <Input
                      placeholder="Why override? (required)"
                      value={overrideNote}
                      onChange={(e) => setOverrideNote(e.target.value)}
                    />
                    <Button
                      size="sm"
                      disabled={!overrideNote.trim()}
                      onClick={() => setStatus(item, "overridden")}
                    >
                      Save override
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
