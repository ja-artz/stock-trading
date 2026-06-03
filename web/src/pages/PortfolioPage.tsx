import { useCallback, useEffect, useState } from "react";
import { api, type ActionItem, type DisciplineSummary } from "@/api/client";
import { TierLegendBlock } from "@/components/TierBadge";
import { getTierDefinition } from "@/lib/tierLabels";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TickerDisplay } from "@/components/TickerDisplay";
import { MessageSquare, Plus } from "lucide-react";
import { useChatContext } from "@/context/ChatContext";

type Position = {
  ticker: string;
  company_name?: string | null;
  instrument_type: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  is_option?: boolean;
  strike?: string | null;
  expiry?: string | null;
};

type PortfolioState = {
  portfolio: { id: number; name: string };
  state: {
    cash_usd: number;
    nav_usd: number;
    cash_pct: number;
    invested_usd: number;
    positions: Position[];
  };
  discipline?: DisciplineSummary;
};

export function PortfolioPage() {
  const [data, setData] = useState<PortfolioState | null>(null);
  const [error, setError] = useState("");
  const { openChat } = useChatContext();

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Portfolio</h1>
          <p className="text-gray-600 mt-1">{data.portfolio.name} · log trades from Sofi</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => openChat({ focus: { type: "portfolio" } })}>
            <MessageSquare className="w-4 h-4 mr-2" />
            Discuss book
          </Button>
          <LogTradeDialog portfolioId={data.portfolio.id} onSaved={load} />
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="NAV" value={`$${state.nav_usd.toFixed(2)}`} />
        <MetricCard label="Cash" value={`$${state.cash_usd.toFixed(2)}`} sub={`${state.cash_pct.toFixed(1)}%`} />
        <MetricCard label="Invested" value={`$${state.invested_usd.toFixed(2)}`} />
        <MetricCard label="Positions" value={String(state.positions.length)} />
      </div>

      {discipline && (
        <DisciplinePanel
          portfolioId={data.portfolio.id}
          discipline={discipline}
          onUpdated={load}
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle>Positions</CardTitle>
        </CardHeader>
        <CardContent>
          {state.positions.length === 0 ? (
            <p className="text-gray-600 text-sm py-4 text-center">No open positions.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="text-right w-32">Resolve</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {state.positions.map((p) => (
                  <TableRow key={`${p.ticker}-${p.instrument_type}`}>
                    <TableCell>
                      <TickerDisplay symbol={p.ticker} companyName={p.company_name} />
                    </TableCell>
                    <TableCell className="text-gray-600">
                      {p.instrument_type}
                      {p.is_option && p.expiry && (
                        <span className="block text-xs text-gray-500">exp {p.expiry}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {p.is_option ? `${p.quantity} contract${p.quantity === 1 ? "" : "s"}` : p.quantity}
                    </TableCell>
                    <TableCell className="text-right">
                      ${p.avg_cost.toFixed(2)}
                      {p.is_option && <span className="block text-xs text-gray-500">premium total</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      ${p.market_value.toFixed(2)}
                      {p.is_option && <span className="block text-xs text-gray-500">at cost (paper)</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      <ClosePositionDialog portfolioId={data.portfolio.id} position={p} onSaved={load} />
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow className="bg-gray-50 font-medium">
                  <TableCell>CASH</TableCell>
                  <TableCell>USD</TableCell>
                  <TableCell />
                  <TableCell />
                  <TableCell className="text-right">${state.cash_usd.toFixed(2)}</TableCell>
                  <TableCell />
                </TableRow>
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-gray-600">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function ClosePositionDialog({
  portfolioId,
  position,
  onSaved,
}: {
  portfolioId: number;
  position: Position;
  onSaved: () => void;
}) {
  const isOption = position.is_option || position.instrument_type.includes("option");
  const [open, setOpen] = useState(false);
  const [resolution, setResolution] = useState(isOption ? "sell" : "sell");
  const [quantity, setQuantity] = useState(String(position.quantity));
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      const body: Record<string, unknown> = {
        portfolio_id: portfolioId,
        ticker: position.ticker,
        instrument_type: position.instrument_type,
        resolution,
        quantity: parseFloat(quantity),
        note: note || undefined,
      };
      if (resolution === "sell" && price.trim()) {
        body.price = parseFloat(price);
      }
      const res = await api.post<{ ok: boolean }>("/portfolio/positions/close", body);
      if (!res.ok) {
        setErr("Close failed");
        return;
      }
      setOpen(false);
      onSaved();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Close
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            Close{" "}
            <TickerDisplay symbol={position.ticker} companyName={position.company_name} layout="inline" />{" "}
            {isOption ? "option" : "stock"}
          </DialogTitle>
          <DialogDescription>
            Record how this position was resolved in Sofi (paper book updates immediately).
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label>Resolution</Label>
            <Select
              value={resolution}
              onValueChange={(v) => {
                setResolution(v);
                if (v === "expire_worthless") setPrice("0");
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {isOption ? (
                  <>
                    <SelectItem value="sell">Sell to close (premium received)</SelectItem>
                    <SelectItem value="expire_worthless">Expired worthless</SelectItem>
                  </>
                ) : (
                  <SelectItem value="sell">Sell shares</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Quantity</Label>
              <Input
                type="number"
                step="any"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                required
              />
            </div>
            <div>
              <Label>{isOption ? "Premium / share ($)" : "Sell price ($)"}</Label>
              <Input
                type="number"
                step="any"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder={resolution === "expire_worthless" ? "0" : "Last fill"}
                disabled={resolution === "expire_worthless"}
              />
            </div>
          </div>
          <div>
            <Label>Note</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          </div>
          {err && <p className="text-sm text-red-600">{err}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Confirm</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LogTradeDialog({ portfolioId, onSaved }: { portfolioId: number; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    side: "buy",
    ticker: "",
    instrument_type: "stock",
    quantity: "",
    price: "",
    note: "",
  });
  const [err, setErr] = useState("");
  const isOption = form.instrument_type.includes("option");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      const res = await api.post<{ ok: boolean; violations?: { message: string }[] }>("/trades", {
        portfolio_id: portfolioId,
        side: form.side,
        ticker: form.ticker.toUpperCase(),
        instrument_type: form.instrument_type,
        quantity: parseFloat(form.quantity),
        price: parseFloat(form.price),
        note: form.note || undefined,
      });
      if (!res.ok) {
        setErr(res.violations?.map((v) => v.message).join("; ") || "Trade rejected");
        return;
      }
      setOpen(false);
      onSaved();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="w-4 h-4 mr-2" />
          Log trade
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Log trade</DialogTitle>
          <DialogDescription>Record what you executed in Sofi.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Action</Label>
              <Select value={form.side} onValueChange={(v) => setForm({ ...form, side: v })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="buy">Buy</SelectItem>
                  <SelectItem value="sell">Sell</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Instrument</Label>
              <Select
                value={form.instrument_type}
                onValueChange={(v) => setForm({ ...form, instrument_type: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="stock">Stock</SelectItem>
                  <SelectItem value="call_option">Call</SelectItem>
                  <SelectItem value="put_option">Put</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>Ticker</Label>
            <Input value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value })} required />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>{isOption ? "Contracts" : "Quantity"}</Label>
              <Input
                type="number"
                step="any"
                value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                required
              />
            </div>
            <div>
              <Label>{isOption ? "Premium / share ($)" : "Fill price ($)"}</Label>
              <Input
                type="number"
                step="any"
                value={form.price}
                onChange={(e) => setForm({ ...form, price: e.target.value })}
                required
              />
            </div>
          </div>
          <div>
            <Label>Note</Label>
            <Textarea value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} rows={2} />
          </div>
          {err && <p className="text-sm text-red-600">{err}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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
      portfolio_id,
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

  const assignTier = (p: Position, tier: number) => {
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
