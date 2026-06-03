import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { TierLegendBlock } from "@/components/TierBadge";
import {
  TRADING_RULE_GROUPS,
  tierBudgetSum,
  type RuleFieldDef,
} from "@/lib/tradingRulesSchema";
import type { TierDefinition } from "@/lib/tierLabels";

type Props = {
  rules: Record<string, unknown>;
  defaults: Record<string, unknown>;
  tierCatalog?: TierDefinition[];
  onSave: (rules: Record<string, unknown>) => Promise<void>;
  sessionStarted?: string | null;
};

function fieldValue(rules: Record<string, unknown>, key: string, type: RuleFieldDef["type"]) {
  const raw = rules[key];
  if (type === "boolean") return Boolean(raw);
  if (raw == null) return "";
  return String(raw);
}

function parseFieldValue(field: RuleFieldDef, raw: string | boolean): unknown {
  if (field.type === "boolean") return Boolean(raw);
  if (field.type === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  return raw;
}

function RuleInput({
  field,
  value,
  defaultValue,
  onChange,
}: {
  field: RuleFieldDef;
  value: string | boolean;
  defaultValue: unknown;
  onChange: (next: unknown) => void;
}) {
  const id = `rule-${field.key}`;
  const changed = String(value) !== String(defaultValue ?? "");

  if (field.type === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="size-4 rounded border-gray-300"
        />
        <Label htmlFor={id} className={changed ? "text-blue-700" : undefined}>
          {field.label}
        </Label>
      </div>
    );
  }

  if (field.type === "select" && field.options) {
    return (
      <div>
        <Label htmlFor={id} className={changed ? "text-blue-700" : undefined}>
          {field.label}
        </Label>
        <Select value={String(value)} onValueChange={(v) => onChange(v)}>
          <SelectTrigger id={id} className="mt-1 max-w-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  return (
    <div>
      <Label htmlFor={id} className={changed ? "text-blue-700" : undefined}>
        {field.label}
        {field.suffix ? <span className="text-gray-500 font-normal"> ({field.suffix})</span> : null}
      </Label>
      <Input
        id={id}
        type={field.type === "number" ? "number" : "text"}
        step={field.step ?? (field.type === "number" ? "any" : undefined)}
        min={field.min}
        max={field.max}
        className="mt-1 max-w-xs"
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
      {field.description ? <p className="text-xs text-gray-500 mt-1">{field.description}</p> : null}
    </div>
  );
}

export function TradingRulesForm({ rules, defaults, tierCatalog, onSave, sessionStarted }: Props) {
  const [draft, setDraft] = useState<Record<string, unknown>>(() => ({ ...rules }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedMsg, setSavedMsg] = useState("");

  useEffect(() => {
    setDraft({ ...rules });
  }, [rules]);

  const budgetSum = useMemo(() => tierBudgetSum(draft), [draft]);
  const budgetOk = Math.abs(budgetSum - 100) < 0.01;
  const isDirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(rules),
    [draft, rules]
  );

  const setField = (key: string, field: RuleFieldDef, raw: unknown) => {
    setDraft((prev) => ({ ...prev, [key]: parseFieldValue(field, raw as string | boolean) }));
    setSavedMsg("");
    setError("");
  };

  const resetToDefaults = () => {
    setDraft({ ...defaults });
    setSavedMsg("");
    setError("");
  };

  const resetToSaved = () => {
    setDraft({ ...rules });
    setSavedMsg("");
    setError("");
  };

  const handleSave = async () => {
    setBusy(true);
    setError("");
    setSavedMsg("");
    try {
      await onSave(draft);
      setSavedMsg("Trading rules saved.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trading rules</CardTitle>
        <CardDescription>
          Portfolio limits, tier budgets, and scheduling. Changes apply to this household&apos;s paper book.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <TierLegendBlock catalog={tierCatalog} />

        {error && (
          <Alert className="border-red-200 bg-red-50">
            <AlertDescription className="text-red-900">{error}</AlertDescription>
          </Alert>
        )}
        {savedMsg && (
          <Alert className="border-green-200 bg-green-50">
            <AlertDescription className="text-green-900">{savedMsg}</AlertDescription>
          </Alert>
        )}

        {TRADING_RULE_GROUPS.map((group) => (
          <div key={group.id} className="space-y-3">
            <div>
              <p className="text-sm font-medium text-gray-900">{group.title}</p>
              {group.description ? <p className="text-xs text-gray-500">{group.description}</p> : null}
              {group.id === "tier_budgets" && (
                <p className={`text-xs mt-1 ${budgetOk ? "text-gray-600" : "text-amber-700 font-medium"}`}>
                  Tier budgets sum: {budgetSum.toFixed(1)}% {budgetOk ? "" : "(must equal 100%)"}
                </p>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {group.fields.map((field) => (
                <RuleInput
                  key={field.key}
                  field={field}
                  value={fieldValue(draft, field.key, field.type)}
                  defaultValue={defaults[field.key]}
                  onChange={(next) => setField(field.key, field, next)}
                />
              ))}
            </div>
          </div>
        ))}

        <div className="flex flex-wrap gap-2 pt-2">
          <Button onClick={handleSave} disabled={busy || !budgetOk}>
            Save trading rules
          </Button>
          <Button variant="outline" onClick={resetToSaved} disabled={busy || !isDirty}>
            Revert changes
          </Button>
          <Button variant="ghost" onClick={resetToDefaults} disabled={busy}>
            Reset to defaults
          </Button>
        </div>

        {sessionStarted && (
          <p className="text-xs text-gray-500">Session started {new Date(sessionStarted).toLocaleString()}</p>
        )}
      </CardContent>
    </Card>
  );
}
