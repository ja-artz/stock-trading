import { streamDailyRun, DAILY_STAGE_LABELS } from "@/api/dailyRun";
import { useRunStream, type RunLogLine } from "@/hooks/useRunStream";

export type { RunLogLine };

export function useDailyRun() {
  return useRunStream(streamDailyRun, DAILY_STAGE_LABELS);
}
