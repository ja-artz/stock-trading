export type PositionRow = {
  ticker: string;
  company_name?: string | null;
  instrument_type: string;
  quantity: number;
  avg_cost: number;
  mark_price?: number;
  mark_source?: string;
  quote_as_of?: string | null;
  market_value: number;
  cost_basis?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  is_option?: boolean;
  strike?: number | null;
  expiry?: string | null;
  display_type?: string;
  option_quote_available?: boolean;
};

export function formatQuoteAsOf(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatMarkSourceLabel(
  p: Pick<PositionRow, "is_option" | "mark_source" | "option_quote_available" | "quote_as_of">,
): string | null {
  if (p.is_option) {
    if (p.option_quote_available) {
      const when = formatQuoteAsOf(p.quote_as_of);
      return when ? `yfinance · ${when}` : "yfinance · live";
    }
    return "At cost (no quote)";
  }
  if (p.mark_source === "live") {
    const when = formatQuoteAsOf(p.quote_as_of);
    return when ? `Live · ${when}` : "Live";
  }
  return null;
}

export function formatInstrumentType(type: string, expiry?: string | null, strike?: number | null): string {
  const t = (type || "stock").toLowerCase();
  const strikeLabel = strike != null ? ` $${strike}` : "";
  if (t.includes("call")) return expiry ? `Call${strikeLabel} (${expiry})` : "Call option";
  if (t.includes("put")) return expiry ? `Put${strikeLabel} (${expiry})` : "Put option";
  return "Stock";
}

export function positionDetailPath(
  ticker: string,
  instrumentType: string,
  strike?: number | null,
  expiry?: string | null,
): string {
  const params = new URLSearchParams({ instrument_type: instrumentType });
  if (strike != null) params.set("strike", String(strike));
  if (expiry) params.set("expiry", expiry.slice(0, 10));
  return `/portfolio/${encodeURIComponent(ticker.toUpperCase())}?${params}`;
}

export function positionRowKey(p: Pick<PositionRow, "ticker" | "instrument_type" | "strike" | "expiry">): string {
  const base = `${p.ticker}-${p.instrument_type}`;
  if (p.strike != null || p.expiry) {
    return `${base}-${p.strike ?? ""}-${p.expiry ?? ""}`;
  }
  return base;
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
