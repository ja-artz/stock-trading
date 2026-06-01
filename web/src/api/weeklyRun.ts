import { streamPost, type RunStreamEvent } from "@/api/runStream";

export type { RunStreamEvent };

export const WEEKLY_STAGE_LABELS: Record<string, string> = {
  start: "Starting",
  session: "Loading session",
  analysis: "Loading analysis",
  portfolio: "Reading portfolio",
  history: "Prior plans & decisions",
  rules: "Loading rules",
  llm: "Trader agent (AI)",
  parse: "Parsing plan",
  persist: "Saving plan",
  done: "Complete",
};

/** POST /runs/weekly?stream=1 */
export function streamWeeklyRun(onEvent: (event: RunStreamEvent) => void) {
  return streamPost("/runs/weekly?stream=1", onEvent);
}
