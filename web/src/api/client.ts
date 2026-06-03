const BASE = import.meta.env.VITE_API_URL || "/api";

function headers(): HeadersInit {
  const key = localStorage.getItem("apiKey") || "";
  const h: HeadersInit = { "Content-Type": "application/json" };
  if (key) h["X-API-Key"] = key;
  return h;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: { ...headers(), ...init?.headers } });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

export type Dashboard = {
  portfolio_id: number;
  nav: { cash_usd: number; nav_usd: number; cash_pct: number; invested_usd: number; positions: Position[] };
  initial_cash?: number | null;
  trade_count?: number;
  is_cash_only?: boolean;
  last_analysis_run_at: string | null;
  last_analysis_run_id: number | null;
  pending_decisions: number;
  session_started_at: string | null;
  has_weekly_plan: boolean;
  has_trading_plan?: boolean;
  last_trading_plan_at?: string | null;
  last_trading_plan_ago?: string | null;
};

export type Position = {
  ticker: string;
  company_name?: string | null;
  instrument_type: string;
  quantity: number;
  avg_cost: number;
  mark_price: number;
  market_value: number;
  cost_basis?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  is_option?: boolean;
  expiry?: string | null;
};

export type IndirectTicker = {
  ticker?: string;
  role?: string;
  confidence?: number;
};

export type IndirectCausalChain = {
  order?: number;
  steps?: string[];
  sectors?: string[];
  tickers?: IndirectTicker[];
  thesis_one_liner?: string;
  time_horizon?: string;
  already_priced_risk?: string;
  falsifiers?: string[];
  liquidity_ok?: boolean;
};

export type IndirectEffects = {
  enabled?: boolean;
  causal_chains?: IndirectCausalChain[];
  discarded_obvious?: string[];
  skip_reason?: string;
};

export type StoryEnvelope = {
  article_title: string;
  article_link?: string;
  article_published?: string;
  retrieval_type?: string;
  shared_context?: Record<string, unknown>;
  indirect_effects?: IndirectEffects;
  analyst_profiles?: Record<string, Record<string, unknown>>;
};

export type PlanItem = {
  id: number;
  priority: number;
  thesis_type?: string | null;
  detail?: { thesis_type?: string };
  action: string;
  ticker: string | null;
  company_name?: string | null;
  instrument_type: string | null;
  execution_status?: "pending" | "executed" | null;
  horizon: string | null;
  capital_tier?: number | null;
  conviction_grade?: string | null;
  sector?: string | null;
  theme_tag?: string | null;
  size_hint: string | null;
  suggested_notional_usd?: number | null;
  suggested_quantity?: number | null;
  quantity_unit?: string | null;
  pct_nav?: number | null;
  pct_cash?: number | null;
  pct_position?: number | null;
  sizing_summary?: string | null;
  persona_consensus?: Record<string, boolean>;
  rationale: string | null;
  rule_warnings?: string[] | null;
  expected_exit_months?: number | null;
  option_expiry?: string | null;
  status: string;
  latest_decision?: { decision: string; note?: string; display_name?: string };
  auto_trade?: {
    id: number;
    side: string;
    ticker: string;
    instrument_type: string;
    quantity: number;
    price: number;
    logged_at?: string;
  } | null;
};

export type ActionItem = {
  id: number;
  portfolio_id: number;
  position_lot_id?: number | null;
  ticker?: string;
  priority: string;
  action: string;
  reason_code: string;
  status: string;
  detail?: Record<string, unknown>;
  override_note?: string | null;
  generated_at?: string;
};

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

export type DisciplineSummary = {
  tier_catalog?: TierDefinition[];
  tier_state: Record<
    string,
    {
      id?: number;
      name?: string;
      hint?: string;
      budget_usd: number;
      deployed_usd: number;
      available_usd: number;
      position_count: number;
      max_positions: number;
    }
  >;
  open_action_items: ActionItem[];
  unmapped_positions: Position[];
  over_capacity_tiers: number[];
};

export type TradingPlanResponse = {
  plan: {
    id: number;
    summary?: string;
    plan_at?: string;
    plan_ago_label?: string;
    payload?: { summary?: string; no_changes?: boolean };
    items: PlanItem[];
    based_on_analysis_at: string;
    no_changes?: boolean;
  } | null;
  no_changes?: boolean;
  plan_at?: string;
  plan_ago_label?: string;
  staleness_banner?: string;
  based_on_analysis_display?: string;
  is_stale?: boolean;
};

/** @deprecated Use TradingPlanResponse */
export type WeeklyPlanResponse = TradingPlanResponse;

export type ChatThread = {
  id: number;
  household_id: number;
  portfolio_id: number;
  weekly_plan_id?: number | null;
  title?: string | null;
  focus?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
};

export type ChatMessage = {
  id: number;
  thread_id: number;
  role: string;
  content: string;
  metadata?: {
    plan_revision?: PlanRevision;
    plan_revision_preview?: PlanRevisionPreview;
  };
  created_at?: string;
};

export type PlanRevision = {
  intent: string;
  summary?: string;
  changes: Array<{
    op: string;
    plan_item_id?: number;
    patch?: Record<string, unknown>;
    item?: Record<string, unknown>;
    reason?: string;
  }>;
};

export type PlanRevisionPreview = {
  weekly_plan_id: number;
  summary?: string;
  before?: unknown[];
  after?: Array<{
    op: string;
    plan_item_id?: number;
    item?: PlanItem & Record<string, unknown>;
    removed?: boolean;
  }>;
  errors?: string[];
  warnings?: string[];
  ok: boolean;
};
