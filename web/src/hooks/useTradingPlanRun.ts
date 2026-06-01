import { streamTradingPlanRun, TRADING_PLAN_STAGE_LABELS } from "@/api/tradingPlanRun";
import { useRunStream } from "@/hooks/useRunStream";

export function useTradingPlanRun() {
  return useRunStream(streamTradingPlanRun, TRADING_PLAN_STAGE_LABELS);
}
