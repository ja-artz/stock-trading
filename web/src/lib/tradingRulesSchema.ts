export type RuleFieldType = "number" | "boolean" | "text" | "select";

export type RuleFieldDef = {
  key: string;
  label: string;
  description?: string;
  type: RuleFieldType;
  step?: number;
  min?: number;
  max?: number;
  options?: { value: string; label: string }[];
  suffix?: string;
};

export type RuleFieldGroup = {
  id: string;
  title: string;
  description?: string;
  fields: RuleFieldDef[];
};

export const TRADING_RULE_GROUPS: RuleFieldGroup[] = [
  {
    id: "portfolio",
    title: "Portfolio limits",
    description: "Caps on concentration and cash reserve.",
    fields: [
      { key: "max_position_pct_nav", label: "Max position size", type: "number", min: 0, max: 100, suffix: "% NAV" },
      { key: "cash_floor_pct", label: "Minimum cash floor", type: "number", min: 0, max: 100, suffix: "% NAV" },
      { key: "max_sector_pct_nav", label: "Max sector exposure", type: "number", min: 0, max: 100, suffix: "% NAV" },
      { key: "max_theme_pct_nav", label: "Max theme exposure", type: "number", min: 0, max: 100, suffix: "% NAV" },
      { key: "max_portfolio_options_pct", label: "Max options (portfolio)", type: "number", min: 0, max: 100, suffix: "% NAV" },
    ],
  },
  {
    id: "activity",
    title: "Activity limits",
    fields: [
      { key: "max_new_positions_per_week", label: "New positions per week", type: "number", min: 0 },
      { key: "max_open_option_positions", label: "Open option positions", type: "number", min: 0 },
      { key: "tier_1_max_new_trades_per_month", label: "Tier 1 new trades / month", type: "number", min: 0 },
      { key: "trade_commit_hours", label: "Trade commit window", type: "number", min: 0, suffix: "hours" },
    ],
  },
  {
    id: "tier_budgets",
    title: "Tier budgets",
    description: "Must sum to 100% of NAV.",
    fields: [
      { key: "tier_1_pct", label: "Tier 1 — Quick Strike", type: "number", min: 0, max: 100, suffix: "%" },
      { key: "tier_2_pct", label: "Tier 2 — Core Opportunity", type: "number", min: 0, max: 100, suffix: "%" },
      { key: "tier_3_pct", label: "Tier 3 — Long Conviction", type: "number", min: 0, max: 100, suffix: "%" },
      { key: "dry_powder_pct", label: "Tier 4 — Dry powder", type: "number", min: 0, max: 100, suffix: "%" },
    ],
  },
  {
    id: "tier_capacity",
    title: "Tier capacity",
    fields: [
      { key: "tier_1_max_positions", label: "Tier 1 max positions", type: "number", min: 0 },
      { key: "tier_2_max_positions", label: "Tier 2 max positions", type: "number", min: 0 },
      { key: "tier_3_max_positions", label: "Tier 3 max positions", type: "number", min: 0 },
      { key: "tier_2_max_options_pct", label: "Tier 2 max options", type: "number", min: 0, max: 100, suffix: "% of tier" },
      { key: "tier_3_max_options_pct", label: "Tier 3 max options", type: "number", min: 0, max: 100, suffix: "% of tier" },
    ],
  },
  {
    id: "permissions",
    title: "Permissions",
    fields: [
      { key: "options_allowed", label: "Options allowed", type: "boolean" },
      { key: "shorts_allowed", label: "Shorts allowed", type: "boolean" },
    ],
  },
  {
    id: "schedule",
    title: "Weekly plan schedule",
    fields: [
      {
        key: "weekly_plan_day",
        label: "Plan day",
        type: "select",
        options: [
          { value: "Sunday", label: "Sunday" },
          { value: "Monday", label: "Monday" },
          { value: "Tuesday", label: "Tuesday" },
          { value: "Wednesday", label: "Wednesday" },
          { value: "Thursday", label: "Thursday" },
          { value: "Friday", label: "Friday" },
          { value: "Saturday", label: "Saturday" },
        ],
      },
      { key: "weekly_plan_hour_local", label: "Plan hour (local)", type: "number", min: 0, max: 23 },
      { key: "timezone", label: "Timezone", type: "text" },
    ],
  },
];

export const TIER_BUDGET_KEYS = ["tier_1_pct", "tier_2_pct", "tier_3_pct", "dry_powder_pct"] as const;

export function tierBudgetSum(rules: Record<string, unknown>): number {
  return TIER_BUDGET_KEYS.reduce((sum, key) => sum + Number(rules[key] ?? 0), 0);
}
