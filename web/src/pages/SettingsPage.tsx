import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { TradingRulesForm } from "@/components/settings/TradingRulesForm";
import { TierExitLogicPanel, type TierExitLogic } from "@/components/settings/TierExitLogicPanel";
import type { TierDefinition } from "@/lib/tierLabels";

type RulesResponse = {
  rules: Record<string, unknown>;
  defaults: Record<string, unknown>;
  tier_catalog?: TierDefinition[];
  tier_exit_logic?: TierExitLogic;
  session?: { started_at: string };
};

export function SettingsPage() {
  const navigate = useNavigate();
  const [rulesData, setRulesData] = useState<RulesResponse | null>(null);
  const [sessionStarted, setSessionStarted] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState(localStorage.getItem("apiKey") || "");
  const [cashUsd, setCashUsd] = useState("1000");
  const [csvText, setCsvText] = useState(
    "ticker,quantity,avg_cost,instrument_type\nAAPL,5,180.50,stock"
  );
  const [status, setStatus] = useState("");
  const [portfolioMeta, setPortfolioMeta] = useState<{
    initial_cash?: number;
    trade_count?: number;
    is_cash_only?: boolean;
  } | null>(null);
  const [busy, setBusy] = useState("");

  const load = () => {
    api.get<RulesResponse>("/settings/rules").then((r) => {
      setRulesData(r);
      setSessionStarted(r.session?.started_at || null);
    });
    api.get<{ initial_cash?: number; trade_count?: number; is_cash_only?: boolean }>("/portfolio").then((r) => {
      setPortfolioMeta({
        initial_cash: r.initial_cash,
        trade_count: r.trade_count,
        is_cash_only: r.is_cash_only,
      });
    });
  };

  useEffect(() => {
    load();
  }, []);

  const saveKey = () => {
    localStorage.setItem("apiKey", apiKey);
    setStatus("API key saved.");
  };

  const saveRules = async (rules: Record<string, unknown>) => {
    const r = await api.post<{ rules: Record<string, unknown>; tier_catalog?: TierDefinition[] }>(
      "/settings/rules",
      { portfolio_id: 1, rules }
    );
    setRulesData((prev) =>
      prev
        ? {
            ...prev,
            rules: r.rules,
            tier_catalog: r.tier_catalog ?? prev.tier_catalog,
          }
        : null
    );
  };

  const resetCash = async () => {
    if (!confirm(`Reset portfolio to $${cashUsd} cash? This clears all logged trades.`)) return;
    setBusy("reset");
    setStatus("");
    try {
      await api.post("/portfolio/reset", {
        portfolio_id: 1,
        cash_usd: parseFloat(cashUsd),
      });
      setStatus(`Portfolio reset to $${cashUsd} cash.`);
      load();
    } catch (e) {
      setStatus(String(e));
    } finally {
      setBusy("");
    }
  };

  const importCsv = async () => {
    setBusy("import");
    setStatus("");
    try {
      const r = await api.post<{ nav_usd?: number; cash_after_import?: number }>("/portfolio/import-csv", {
        portfolio_id: 1,
        cash_usd: parseFloat(cashUsd),
        csv_text: csvText,
      });
      setStatus(
        `Imported. NAV $${r.nav_usd?.toFixed(2) ?? "?"}, cash $${r.cash_after_import?.toFixed(2) ?? "?"}.`
      );
      load();
    } catch (e) {
      setStatus(String(e));
    } finally {
      setBusy("");
    }
  };

  const importCashOnly = async () => {
    setBusy("import");
    try {
      await api.post("/portfolio/import", { portfolio_id: 1, cash_usd: parseFloat(cashUsd), positions: [] });
      setStatus(`Starting state: $${cashUsd} cash, no positions.`);
      load();
    } catch (e) {
      setStatus(String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-gray-600 mt-1">Trading rules, tier exit logic, API access, and starting portfolio state</p>
      </div>

      {portfolioMeta && !portfolioMeta.is_cash_only && (
        <Alert className="border-amber-200 bg-amber-50">
          <AlertDescription className="text-amber-900">
            Your book has {portfolioMeta.trade_count} logged trade(s) — dashboard NAV reflects real ledger data,
            not mock UI. Use <strong>Reset to cash</strong> below for a clean $1,000 starting point.
          </AlertDescription>
        </Alert>
      )}

      {rulesData && (
        <>
          <TradingRulesForm
            rules={rulesData.rules}
            defaults={rulesData.defaults}
            tierCatalog={rulesData.tier_catalog}
            sessionStarted={sessionStarted}
            onSave={saveRules}
          />
          {rulesData.tier_exit_logic && <TierExitLogicPanel logic={rulesData.tier_exit_logic} />}
        </>
      )}

      <Card className="border-amber-200">
        <CardHeader>
          <CardTitle>Fresh start</CardTitle>
          <CardDescription>
            Clear all trading recommendations (plans, decisions) and reset the paper book to ${cashUsd} cash.
            Analysis stories are kept; generate a new trading plan when ready.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="destructive"
            disabled={!!busy}
            onClick={async () => {
              if (
                !confirm(
                  `Fresh start: delete all trading plans and reset portfolio to $${cashUsd} cash? This cannot be undone.`
                )
              )
                return;
              setBusy("fresh");
              setStatus("");
              try {
                const r = await api.post<{ weekly_plans_cleared?: number }>("/portfolio/fresh-start", {
                  portfolio_id: 1,
                  cash_usd: parseFloat(cashUsd),
                });
                setStatus(
                  `Fresh start complete. Cleared ${r.weekly_plans_cleared ?? 0} trading plan(s). Book is $${cashUsd} cash.`
                );
                load();
              } catch (e) {
                setStatus(String(e));
              } finally {
                setBusy("");
              }
            }}
          >
            Fresh start (clear recommendations + reset book)
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Starting state</CardTitle>
          <CardDescription>
            Set the household paper book before you log Sofi trades. Uncommitted = all cash, no positions.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="cash">Free cash (USD)</Label>
            <Input
              id="cash"
              type="number"
              step="0.01"
              className="mt-1 max-w-xs"
              value={cashUsd}
              onChange={(e) => setCashUsd(e.target.value)}
            />
            <p className="text-xs text-gray-500 mt-1">
              For import with positions, this is cash <em>after</em> those holdings at the costs below.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={importCashOnly} disabled={!!busy} variant="default">
              Apply ${cashUsd} cash only
            </Button>
            <Button onClick={resetCash} disabled={!!busy} variant="outline">
              Reset to cash (clear trades)
            </Button>
            <Button variant="ghost" onClick={() => navigate("/")}>
              View dashboard
            </Button>
          </div>

          <div>
            <Label htmlFor="csv">Import positions (CSV)</Label>
            <Textarea
              id="csv"
              className="mt-1 font-mono text-xs"
              rows={5}
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              placeholder="ticker,quantity,avg_cost,instrument_type"
            />
            <Button className="mt-2" variant="secondary" onClick={importCsv} disabled={!!busy}>
              Import CSV + cash
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>API key</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-gray-600">
            Required for reset, import, runs, trades, decisions, and saving trading rules. Match{" "}
            <code className="bg-gray-100 px-1 rounded">HOUSEHOLD_API_KEY</code> in server `.env`.
          </p>
          <div>
            <Label htmlFor="apiKey">X-API-Key</Label>
            <Input
              id="apiKey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="mt-1"
            />
          </div>
          <Button onClick={saveKey}>Save API key</Button>
        </CardContent>
      </Card>

      {status && <p className="text-sm text-blue-700">{status}</p>}
    </div>
  );
}
