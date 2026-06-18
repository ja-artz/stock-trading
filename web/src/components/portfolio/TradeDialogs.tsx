import { useState } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
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
import { AlertTriangle, DollarSign, Plus, Wallet } from "lucide-react";
import type { PositionRow } from "@/lib/positionMetrics";

export function LogTradeDialog({
  portfolioId,
  onSaved,
  preset,
  trigger,
  lockFields,
  description,
}: {
  portfolioId: number;
  onSaved: () => void;
  preset?: { ticker?: string; instrument_type?: string; side?: string };
  trigger?: React.ReactNode;
  lockFields?: { ticker?: boolean; instrument_type?: boolean };
  description?: string;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    side: preset?.side ?? "buy",
    ticker: preset?.ticker ?? "",
    instrument_type: preset?.instrument_type ?? "stock",
    quantity: "",
    price: "",
    fees: "",
    note: "",
  });
  const [err, setErr] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const isOption = form.instrument_type.includes("option");

  const resetForm = () => {
    setForm({
      side: preset?.side ?? "buy",
      ticker: preset?.ticker ?? "",
      instrument_type: preset?.instrument_type ?? "stock",
      quantity: "",
      price: "",
      fees: "",
      note: "",
    });
    setErr("");
    setWarnings([]);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setWarnings([]);
    try {
      const res = await api.post<{ ok: boolean; violations?: { message: string }[] }>("/trades", {
        portfolio_id: portfolioId,
        side: form.side,
        ticker: form.ticker.toUpperCase(),
        instrument_type: form.instrument_type,
        quantity: parseFloat(form.quantity),
        price: parseFloat(form.price),
        fees: form.fees.trim() ? parseFloat(form.fees) : 0,
        note: form.note || undefined,
      });
      if (!res.ok) {
        setErr(res.violations?.map((v) => v.message).join("; ") || "Trade rejected");
        return;
      }
      const ruleWarnings = res.violations?.map((v) => v.message).filter(Boolean) ?? [];
      if (ruleWarnings.length > 0) {
        setWarnings(ruleWarnings);
      }
      setOpen(false);
      resetForm();
      onSaved();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <>
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (v && preset) {
          setForm((f) => ({
            ...f,
            side: preset.side ?? f.side,
            ticker: preset.ticker ?? f.ticker,
            instrument_type: preset.instrument_type ?? f.instrument_type,
          }));
        }
        if (!v) resetForm();
      }}
    >
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            <Plus className="w-4 h-4 mr-2" />
            Log Trade
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Log Trade</DialogTitle>
          <DialogDescription>
            {description ??
              "Record a trade you executed in Sofi. Trading rules guide recommendations but do not block logging."}
          </DialogDescription>
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
                  <SelectItem value="sell">Sell (trim or exit)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Instrument</Label>
              <Select
                value={form.instrument_type}
                onValueChange={(v) => setForm({ ...form, instrument_type: v })}
                disabled={lockFields?.instrument_type}
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
            <Input
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              required
              readOnly={lockFields?.ticker}
              className={lockFields?.ticker ? "bg-gray-50" : undefined}
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
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
            <div>
              <Label>Fees (optional)</Label>
              <Input
                type="number"
                step="any"
                placeholder="0.00"
                value={form.fees}
                onChange={(e) => setForm({ ...form, fees: e.target.value })}
              />
            </div>
          </div>
          <div>
            <Label>Note</Label>
            <Textarea
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              rows={3}
              placeholder="Following weekly plan recommendation…"
            />
          </div>
          {err && <p className="text-sm text-red-600">{err}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">
              <DollarSign className="w-4 h-4 mr-2" />
              Log Trade
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    {warnings.length > 0 && (
      <div className="fixed bottom-4 right-4 max-w-md rounded-lg border border-amber-200 bg-amber-50 p-4 shadow-lg z-50">
        <p className="text-sm font-medium text-amber-900 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Trade logged with rule warnings
        </p>
        <ul className="mt-2 text-sm text-amber-800 list-disc pl-5 space-y-1">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => setWarnings([])}
        >
          Dismiss
        </Button>
      </div>
    )}
    </>
  );
}

export function AddCashDialog({
  portfolioId,
  onSaved,
}: {
  portfolioId: number;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    const parsed = parseFloat(amount);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setErr("Enter a positive dollar amount");
      return;
    }
    try {
      await api.post("/portfolio/cash-deposit", {
        portfolio_id: portfolioId,
        amount_usd: parsed,
        note: note.trim() || undefined,
      });
      setOpen(false);
      setAmount("");
      setNote("");
      onSaved();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) {
          setAmount("");
          setNote("");
          setErr("");
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">
          <Wallet className="w-4 h-4 mr-2" />
          Add Cash
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add cash</DialogTitle>
          <DialogDescription>
            Record money you transferred into your Sofi account. This increases cash and NAV in the paper book.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Label>Amount (USD)</Label>
            <Input
              type="number"
              step="any"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="500.00"
              required
            />
          </div>
          <div>
            <Label>Note (optional)</Label>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder="Monthly contribution…"
            />
          </div>
          {err && <p className="text-sm text-red-600">{err}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Add cash</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ClosePositionDialog({
  portfolioId,
  position,
  onSaved,
  trigger,
}: {
  portfolioId: number;
  position: PositionRow;
  onSaved: () => void;
  trigger?: React.ReactNode;
}) {
  const isOption = position.is_option || position.instrument_type.includes("option");
  const [open, setOpen] = useState(false);
  const [resolution, setResolution] = useState("sell");
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
        {trigger ?? (
          <Button size="sm" variant="outline">
            Close
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            Close {position.ticker} {isOption ? "option" : "stock"}
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
