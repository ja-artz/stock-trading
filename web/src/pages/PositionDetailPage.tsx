import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Info, Pencil, TrendingDown, TrendingUp, X } from "lucide-react";
import { api } from "@/api/client";
import { ClosePositionDialog, EditTradeDialog, LogTradeDialog } from "@/components/portfolio/TradeDialogs";
import { PositionValueChart } from "@/components/portfolio/PositionValueChart";
import {
  formatInstrumentType,
  formatMarkSourceLabel,
  formatSignedPct,
  formatSignedUsd,
  formatTradeDate,
  formatUsd,
  pnlColorClass,
  type PositionRow,
} from "@/lib/positionMetrics";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";

type PositionTrade = {
  id: number;
  side: string;
  quantity: number;
  price: number;
  fees: number;
  total: number;
  logged_at: string;
  note?: string | null;
};

type PositionDetail = {
  portfolio_id: number;
  portfolio_name?: string | null;
  position: PositionRow & { display_type?: string };
  trades: PositionTrade[];
  first_purchase?: string | null;
  days_held?: number | null;
  value_history: { as_of: string; market_value: number }[];
};

export function PositionDetailPage() {
  const { ticker = "" } = useParams();
  const [searchParams] = useSearchParams();
  const instrumentType = searchParams.get("instrument_type") || "stock";
  const strikeParam = searchParams.get("strike");
  const expiryParam = searchParams.get("expiry");
  const strike = strikeParam != null && strikeParam !== "" ? Number(strikeParam) : undefined;
  const navigate = useNavigate();
  const [data, setData] = useState<PositionDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params = new URLSearchParams({ ticker, instrument_type: instrumentType });
    if (strike != null && Number.isFinite(strike)) params.set("strike", String(strike));
    if (expiryParam) params.set("expiry", expiryParam);
    api
      .get<PositionDetail>(`/portfolio/position?${params}`)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [ticker, instrumentType, strike, expiryParam]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div className="space-y-4">
        <BackLink />
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  if (!data) return <p className="text-gray-600">Loading…</p>;

  const { position, trades, portfolio_id, portfolio_name } = data;
  const pnl = position.unrealized_pnl ?? 0;
  const pnlPct = position.unrealized_pnl_pct ?? 0;
  const isOption = position.is_option || position.instrument_type.includes("option");
  const displayType = position.display_type ?? formatInstrumentType(position.instrument_type, position.expiry, position.strike);
  const markPrice = position.mark_price ?? (position.quantity ? position.market_value / position.quantity : 0);
  const markSub =
    formatMarkSourceLabel(position) ??
    (isOption ? "per share" : position.mark_source === "live" ? "real-time" : "at cost");

  const onClosed = () => navigate("/portfolio");

  return (
    <div className="space-y-6">
      <BackLink />

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-3xl font-bold font-mono">{position.ticker}</h1>
            <Badge variant="outline">{displayType}</Badge>
            {portfolio_name && <Badge variant="secondary">{portfolio_name}</Badge>}
          </div>
          {position.company_name && (
            <p className="text-gray-600 mt-1 break-words">{position.company_name}</p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <LogTradeDialog
            portfolioId={portfolio_id}
            onSaved={load}
            preset={{
              ticker: position.ticker,
              instrument_type: position.instrument_type,
              strike: position.strike != null ? String(position.strike) : undefined,
              expiry: position.expiry ?? undefined,
            }}
            lockFields={{ ticker: true, instrument_type: true, strike: true, expiry: true }}
            description="Add shares or log a partial sell to trim this position."
            trigger={
              <Button variant="outline">
                Log Trade
              </Button>
            }
          />
          <ClosePositionDialog
            portfolioId={portfolio_id}
            position={position}
            onSaved={onClosed}
            trigger={
              <Button variant="outline">
                <X className="w-4 h-4 mr-2" />
                Close Position
              </Button>
            }
          />
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard
          label="Quantity"
          value={String(position.quantity)}
          sub={isOption ? "contracts" : "shares"}
        />
        <StatCard
          label="Avg Cost"
          value={formatUsd(position.avg_cost)}
          sub={isOption ? "premium total" : "per share"}
        />
        <StatCard label="Current Price" value={formatUsd(markPrice)} sub={markSub} />
        <StatCard label="Market Value" value={formatUsd(position.market_value)} sub="total position" />
        <StatCard
          label="Unrealized P&amp;L"
          value={formatSignedUsd(pnl)}
          sub={formatSignedPct(pnlPct)}
          valueClass={pnlColorClass(pnl)}
          icon={
            pnl > 0 ? (
              <TrendingUp className="w-5 h-5 text-green-600" />
            ) : pnl < 0 ? (
              <TrendingDown className="w-5 h-5 text-red-600" />
            ) : null
          }
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Info className="w-4 h-4" />
            Position Details
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <DetailField label="Cost Basis" value={formatUsd(position.cost_basis ?? position.market_value - pnl)} />
            {isOption && position.strike != null && (
              <DetailField label="Strike" value={formatUsd(position.strike)} />
            )}
            {isOption && position.expiry && <DetailField label="Expiry" value={position.expiry} />}
            <DetailField label="First Purchase" value={formatTradeDate(data.first_purchase ?? undefined)} />
            <DetailField
              label="Days Held"
              value={data.days_held != null ? `${data.days_held} days` : "—"}
            />
            <DetailField label="Total Trades" value={String(trades.length)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Position Value Over Time</CardTitle>
        </CardHeader>
        <CardContent>
          <PositionValueChart history={data.value_history} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Trade History for {position.ticker}</CardTitle>
        </CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">No trades logged for this position.</p>
          ) : (
            <div className="border rounded-lg overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead className="text-right">Fees</TableHead>
                    <TableHead>Note</TableHead>
                    <TableHead className="w-16" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trades.map((trade) => (
                    <TableRow key={trade.id}>
                      <TableCell className="text-sm">{formatTradeDate(trade.logged_at)}</TableCell>
                      <TableCell>
                        <Badge variant={trade.side.toLowerCase() === "buy" ? "default" : "destructive"}>
                          {trade.side.charAt(0).toUpperCase() + trade.side.slice(1)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{trade.quantity}</TableCell>
                      <TableCell className="text-right">{formatUsd(trade.price)}</TableCell>
                      <TableCell className="text-right font-medium">{formatUsd(trade.total)}</TableCell>
                      <TableCell className="text-right text-sm text-gray-600">{formatUsd(trade.fees)}</TableCell>
                      <TableCell className="text-sm text-gray-600 max-w-md">{trade.note || "—"}</TableCell>
                      <TableCell>
                        <EditTradeDialog
                          ledgerEventId={trade.id}
                          onSaved={load}
                          trigger={
                            <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                              <span className="sr-only">Edit trade</span>
                              <Pencil className="w-4 h-4" />
                            </Button>
                          }
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {isOption && !position.option_quote_available && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Live option quote unavailable — showing cost basis until yfinance returns a chain price. Ensure strike and expiry are set on the position.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/portfolio">
      <Button variant="ghost" size="sm">
        <ArrowLeft className="w-4 h-4 mr-2" />
        Back to Portfolio
      </Button>
    </Link>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueClass,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
  icon?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-gray-600">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={`flex items-center gap-2 ${valueClass ?? ""}`}>
          {icon}
          <div className="text-2xl font-bold">{value}</div>
        </div>
        {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-sm text-gray-600 mb-1">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
