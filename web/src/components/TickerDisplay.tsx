import { useEffect, useState } from "react";
import { api } from "@/api/client";

const nameCache = new Map<string, string | null>();

type Props = {
  symbol?: string | null;
  companyName?: string | null;
  layout?: "stack" | "inline";
  className?: string;
};

export function TickerDisplay({ symbol, companyName, layout = "stack", className = "" }: Props) {
  const sym = (symbol || "").trim().toUpperCase();
  const [resolved, setResolved] = useState<string | null | undefined>(companyName);

  useEffect(() => {
    if (!sym) {
      setResolved(undefined);
      return;
    }
    if (companyName !== undefined && companyName !== null) {
      setResolved(companyName);
      return;
    }
    if (nameCache.has(sym)) {
      setResolved(nameCache.get(sym) ?? null);
      return;
    }
    let cancelled = false;
    api
      .get<{ names: Record<string, string | null> }>(`/tickers/names?symbols=${encodeURIComponent(sym)}`)
      .then((r) => {
        const n = r.names[sym] ?? null;
        nameCache.set(sym, n);
        if (!cancelled) setResolved(n);
      })
      .catch(() => {
        if (!cancelled) setResolved(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sym, companyName]);

  if (!sym) {
    return <span className={className}>—</span>;
  }

  const name = resolved?.trim();

  if (layout === "inline") {
    return (
      <span className={className}>
        <span className="font-mono font-medium">{sym}</span>
        {name ? <span className="text-gray-600 font-normal"> · {name}</span> : null}
      </span>
    );
  }

  return (
    <span className={className}>
      <span className="font-mono font-medium block leading-tight">{sym}</span>
      {name ? <span className="text-xs text-gray-600 font-normal block leading-tight">{name}</span> : null}
    </span>
  );
}
