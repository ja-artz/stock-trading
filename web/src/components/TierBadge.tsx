import { Badge } from "@/components/ui/badge";
import {
  getTierDefinition,
  tierShortLabel,
  TIER_CATALOG,
  type TierDefinition,
} from "@/lib/tierLabels";

type Props = {
  tier: number | null | undefined;
  /** Show numeric id in badge text, e.g. "Quick Strike · 1" */
  showId?: boolean;
  className?: string;
};

export function TierBadge({ tier, showId = false, className }: Props) {
  if (tier == null) return null;
  const def = getTierDefinition(tier);
  const label = showId && def ? `${def.name} · ${def.id}` : tierShortLabel(tier, false);
  const title = def ? `${def.name} (T${def.id}) — ${def.summary}` : undefined;

  return (
    <Badge variant="secondary" className={className} title={title}>
      {label}
    </Badge>
  );
}

export function TierLegendBlock({ catalog }: { catalog?: TierDefinition[] }) {
  const rows = (catalog?.length ? catalog : TIER_CATALOG).filter((t) => t.deployable);

  return (
    <div className="rounded border bg-slate-50 p-3 text-xs text-gray-700 space-y-2">
      <p className="font-medium text-gray-900">Capital tiers</p>
      <ul className="space-y-1.5">
        {rows.map((t) => (
          <li key={t.id}>
            <span className="font-medium text-gray-900">
              T{t.id} — {t.name}
            </span>
            <span className="text-gray-600"> · {t.summary || t.hint}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
