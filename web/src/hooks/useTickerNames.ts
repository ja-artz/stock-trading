import { useEffect, useState } from "react";
import { api } from "@/api/client";

const cache = new Map<string, string | null>();

export function useTickerNames(symbols: string[]): Record<string, string | null> {
  const key = symbols
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
    .sort()
    .join(",");
  const [names, setNames] = useState<Record<string, string | null>>(() => {
    const initial: Record<string, string | null> = {};
    for (const s of key.split(",").filter(Boolean)) {
      if (cache.has(s)) initial[s] = cache.get(s) ?? null;
    }
    return initial;
  });

  useEffect(() => {
    const needed = key.split(",").filter(Boolean).filter((s) => !cache.has(s));
    if (needed.length === 0) {
      const all: Record<string, string | null> = {};
      for (const s of key.split(",").filter(Boolean)) {
        all[s] = cache.get(s) ?? null;
      }
      setNames(all);
      return;
    }
    let cancelled = false;
    api
      .get<{ names: Record<string, string | null> }>(
        `/tickers/names?symbols=${encodeURIComponent(needed.join(","))}`
      )
      .then((r) => {
        if (cancelled) return;
        for (const [sym, n] of Object.entries(r.names)) {
          cache.set(sym, n);
        }
        const merged: Record<string, string | null> = {};
        for (const s of key.split(",").filter(Boolean)) {
          merged[s] = cache.get(s) ?? null;
        }
        setNames(merged);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [key]);

  return names;
}
