import { useCallback, useRef, useState } from "react";
import type { RunStreamEvent } from "@/api/runStream";

export type RunLogLine = {
  id: number;
  stage?: string;
  message: string;
  level?: string;
};

export function useRunStream(
  streamFn: (onEvent: (event: RunStreamEvent) => void) => Promise<RunStreamEvent>,
  stageLabels: Record<string, string>
) {
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<RunLogLine[]>([]);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logId = useRef(0);

  const appendLog = useCallback((ev: RunStreamEvent) => {
    if (ev.type === "stage") {
      setStage(ev.stage);
      return;
    }
    if (ev.type === "log") {
      if (ev.stage) setStage(ev.stage);
      const id = ++logId.current;
      setLogs((prev) => [...prev, { id, stage: ev.stage, message: ev.message, level: ev.level }]);
    }
  }, []);

  const run = useCallback(
    async (onComplete?: () => void) => {
      setBusy(true);
      setError(null);
      setLogs([]);
      setStage("start");
      logId.current = 0;

      try {
        await streamFn(appendLog);
        onComplete?.();
      } catch (e) {
        const msg = String(e);
        setError(msg);
        const id = ++logId.current;
        setLogs((prev) => [...prev, { id, message: msg, level: "error" }]);
      } finally {
        setBusy(false);
      }
    },
    [appendLog, streamFn]
  );

  const stageLabel = stage ? stageLabels[stage] ?? stage : null;

  return { busy, logs, stage, stageLabel, error, run };
}
