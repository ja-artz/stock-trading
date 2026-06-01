import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
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
import { Plus } from "lucide-react";

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

  const { state } = data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Portfolio</h1>
          <p className="text-gray-600 mt-1">{data.portfolio.name} · log trades from Sofi</p>
        </div>
        <LogTradeDialog portfolioId={data.portfolio.id} onSaved={load} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="NAV" value={`$${state.nav_usd.toFixed(2)}`} />
        <MetricCard label="Cash" value={`$${state.cash_usd.toFixed(2)}`} sub={`${state.cash_pct.toFixed(1)}%`} />
        <MetricCard label="Invested" value={`$${state.invested_usd.toFixed(2)}`} />
        <MetricCard label="Positions" value={String(state.positions.length)} />
      </div>

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
