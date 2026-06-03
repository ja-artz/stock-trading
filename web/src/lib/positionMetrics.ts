export type PositionRow = {
  ticker: string;
  company_name?: string | null;
  instrument_type: string;
  quantity: number;
  avg_cost: number;
  mark_price?: number;
  market_value: number;
  cost_basis?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  is_option?: boolean;
  expiry?: string | null;
  display_type?: string;
};

export function formatInstrumentType(type: string, expiry?: string | null): string {
  const t = (type || "stock").toLowerCase();
  if (t.includes("call")) return expiry ? `Call (${expiry})` : "Call option";
  if (t.includes("put")) return expiry ? `Put (${expiry})` : "Put option";
  return "Stock";
}

export function positionDetailPath(ticker: string, instrumentType: string): string {
  const params = new URLSearchParams({ instrument_type: instrumentType });
  return `/portfolio/${encodeURIComponent(ticker.toUpperCase())}?${params}`;
}

export function formatUsd(value: number, digits = 2): string {
  return `$${value.toFixed(digits)}`;
}

export function formatSignedUsd(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toFixed(digits)}`;
}

export function formatSignedPct(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function pnlColorClass(value: number): string {
  if (value > 0) return "text-green-600";
  if (value < 0) return "text-red-600";
  return "text-gray-600";
}

export function portfolioPct(value: number, navUsd: number): string {
  if (navUsd <= 0) return "0.0%";
  return `${((value / navUsd) * 100).toFixed(1)}%`;
}

export function formatTradeDate(iso: string | undefined): string {
  if (!iso || iso === "now") return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
