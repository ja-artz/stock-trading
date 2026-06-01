import { streamPost, type RunStreamEvent } from "@/api/runStream";

export type { RunStreamEvent };

export const TRADING_PLAN_STAGE_LABELS: Record<string, string> = {
  start: "Starting",
  session: "Loading session",
  analysis: "Loading analysis",
  portfolio: "Reading portfolio",
  quotes: "Live market quotes",
  history: "Prior plans & decisions",
  rules: "Loading rules",
  llm: "Trader agent (AI)",
  parse: "Parsing plan",
  persist: "Saving plan",
  done: "Complete",
};

/** POST /runs/trading-plan?stream=1 (alias of /runs/weekly) */
export function streamTradingPlanRun(onEvent: (event: RunStreamEvent) => void) {
  return streamPost("/runs/trading-plan?stream=1", onEvent);
}
