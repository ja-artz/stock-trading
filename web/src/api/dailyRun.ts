import { streamPost, type RunStreamEvent } from "@/api/runStream";

export type { RunStreamEvent };

export const DAILY_STAGE_LABELS: Record<string, string> = {
  start: "Starting",
  fetch_news: "Fetching news",
  retrieval: "Story selection (AI)",
  merge: "Merging candidates",
  triage: "Actionability triage",
  analyze: "Analyst personas",
  validate: "Ticker validation",
  export: "Writing export file",
  persist: "Saving to database",
  done: "Complete",
};

/** POST /runs/daily?stream=1 */
export function streamDailyRun(onEvent: (event: RunStreamEvent) => void) {
  return streamPost("/runs/daily?stream=1", onEvent);
}

/** @deprecated use DAILY_STAGE_LABELS */
export const STAGE_LABELS = DAILY_STAGE_LABELS;
