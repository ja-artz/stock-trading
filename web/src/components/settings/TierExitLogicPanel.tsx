import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { tierShortLabel } from "@/lib/tierLabels";

export type ExitStep = {
  threshold_pct: number;
  action: string;
  action_label: string;
  reason_code: string;
  priority: string;
};

export type TierExitTier = {
  tier: number;
  name: string;
  profit_ladder: ExitStep[];
  loss_ladder: ExitStep[];
  time_rules: { kind: string; label: string }[];
  profit_recycling: { target_tier: number; fraction_pct: number }[];
};

export type TierExitLogic = {
  tiers: TierExitTier[];
  thesis_exits: {
    thesis_status: string;
    action: string;
    action_label: string;
    reason_code: string;
    priority: string;
  }[];
  notes?: string[];
};

function priorityVariant(priority: string): "default" | "secondary" | "destructive" | "outline" {
  if (priority === "critical") return "destructive";
  if (priority === "high") return "default";
  return "secondary";
}

function LadderTable({ title, steps, variant }: { title: string; steps: ExitStep[]; variant: "profit" | "loss" }) {
  if (!steps.length) return null;

  return (
    <div>
      <p className="text-xs font-medium text-gray-900 mb-1.5">{title}</p>
      <div className="rounded border overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              <th className="text-left px-2 py-1.5 font-medium">P/L</th>
              <th className="text-left px-2 py-1.5 font-medium">Action</th>
              <th className="text-left px-2 py-1.5 font-medium hidden sm:table-cell">Priority</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step) => (
              <tr key={step.reason_code} className="border-t">
                <td className="px-2 py-1.5 font-mono whitespace-nowrap">
                  {variant === "profit" ? "+" : ""}
                  {step.threshold_pct}%
                </td>
                <td className="px-2 py-1.5 text-gray-700">{step.action_label}</td>
                <td className="px-2 py-1.5 hidden sm:table-cell">
                  <Badge variant={priorityVariant(step.priority)} className="text-[10px]">
                    {step.priority}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TierExitCard({ tier }: { tier: TierExitTier }) {
  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div>
        <p className="font-medium text-gray-900">
          {tierShortLabel(tier.tier)} — {tier.name}
        </p>
      </div>

      <LadderTable title="Profit ladder" steps={tier.profit_ladder} variant="profit" />
      <LadderTable title="Loss ladder" steps={tier.loss_ladder} variant="loss" />

      {tier.time_rules.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-900 mb-1.5">Time rules</p>
          <ul className="text-xs text-gray-700 space-y-1 list-disc list-inside">
            {tier.time_rules.map((rule) => (
              <li key={rule.label}>{rule.label}</li>
            ))}
          </ul>
        </div>
      )}

      {tier.profit_recycling.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-900 mb-1.5">Profit recycling</p>
          <p className="text-xs text-gray-700">
            On profit-taking exits, redeploy freed capital:{" "}
            {tier.profit_recycling
              .map((r) => `${r.fraction_pct}% → T${r.target_tier}`)
              .join(" · ")}
          </p>
        </div>
      )}
    </div>
  );
}

export function TierExitLogicPanel({ logic }: { logic: TierExitLogic }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Tier exit logic</CardTitle>
        <CardDescription>
          Automated profit/loss ladders, time-based exits, and thesis-driven actions enforced by daily discipline.
          These rules are defined in code and apply consistently across tiers.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {logic.tiers.map((tier) => (
            <TierExitCard key={tier.tier} tier={tier} />
          ))}
        </div>

        <div className="rounded-lg border bg-slate-50 p-4 space-y-2">
          <p className="text-sm font-medium text-gray-900">Thesis-driven exits</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
            {logic.thesis_exits.map((row) => (
              <div key={row.reason_code} className="flex items-start gap-2">
                <Badge variant={priorityVariant(row.priority)} className="shrink-0 text-[10px] mt-0.5">
                  {row.priority}
                </Badge>
                <span className="text-gray-700">
                  <span className="font-medium capitalize">{row.thesis_status}</span>
                  {" → "}
                  {row.action_label}
                </span>
              </div>
            ))}
          </div>
        </div>

        {logic.notes?.length ? (
          <ul className="text-xs text-gray-500 space-y-1 list-disc list-inside">
            {logic.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
