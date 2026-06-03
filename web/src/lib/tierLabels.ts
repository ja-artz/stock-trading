/** Display names for capital_tier 1–4 (keep in sync with core/tier_config.py). */

export type TierDefinition = {
  id: number;
  slug: string;
  name: string;
  hint: string;
  budget_pct: number;
  max_positions: number;
  deployable: boolean;
  expected_horizon?: string | null;
  summary: string;
};

export const TIER_CATALOG: TierDefinition[] = [
  {
    id: 1,
    slug: "quick_strike",
    name: "Quick Strike",
    hint: "1–4 week catalysts · short horizon · max 28-day hold",
    budget_pct: 15,
    max_positions: 2,
    deployable: true,
    expected_horizon: "short",
    summary: "15% NAV budget · max 2 concurrent positions · 1–4 week catalysts",
  },
  {
    id: 2,
    slug: "core_opportunity",
    name: "Core Opportunity",
    hint: "3–6 month thesis · medium horizon · core book",
    budget_pct: 55,
    max_positions: 3,
    deployable: true,
    expected_horizon: "medium",
    summary: "55% NAV budget · max 3 concurrent positions · 3–6 month thesis",
  },
  {
    id: 3,
    slug: "long_conviction",
    name: "Long Conviction",
    hint: "6–12 month themes · long horizon · patient capital",
    budget_pct: 25,
    max_positions: 2,
    deployable: true,
    expected_horizon: "long",
    summary: "25% NAV budget · max 2 concurrent positions · 6–12 month themes",
  },
  {
    id: 4,
    slug: "dry_powder",
    name: "Dry Powder",
    hint: "Cash reserve only · not for new positions",
    budget_pct: 5,
    max_positions: 0,
    deployable: false,
    expected_horizon: null,
    summary: "5% NAV cash reserve · not deployable",
  },
];

const BY_ID = new Map(TIER_CATALOG.map((t) => [t.id, t]));

export function getTierDefinition(tier: number | null | undefined): TierDefinition | undefined {
  if (tier == null) return undefined;
  return BY_ID.get(tier);
}

export function tierDisplayName(tier: number | null | undefined): string {
  return getTierDefinition(tier)?.name ?? (tier != null ? `Tier ${tier}` : "—");
}

export function tierShortLabel(tier: number | null | undefined, includeId = true): string {
  const def = getTierDefinition(tier);
  if (!def) return tier != null ? `T${tier}` : "—";
  return includeId ? `${def.name} (T${def.id})` : def.name;
}
