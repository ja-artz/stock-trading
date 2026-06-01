import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { RunLogLine } from "@/hooks/useRunStream";

type Props = {
  open: boolean;
  busy: boolean;
  stageLabel: string | null;
  logs: RunLogLine[];
  error?: string | null;
  titles: { running: string; failed: string; done: string };
  hint?: string;
};

export function RunProgressPanel({
  open,
  busy,
  stageLabel,
  logs,
  error,
  titles,
  hint,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (!open && !busy && logs.length === 0) return null;

  return (
    <Card className="border-blue-200 bg-slate-50/80">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold">
          {busy ? titles.running : error ? titles.failed : titles.done}
        </CardTitle>
        {stageLabel && busy && (
          <p className="text-sm text-blue-800 font-medium">{stageLabel}</p>
        )}
      </CardHeader>
      <CardContent>
        <div
          className="max-h-52 overflow-y-auto rounded-md border bg-white p-3 font-mono text-xs text-gray-700 space-y-1"
          role="log"
          aria-live="polite"
        >
          {logs.length === 0 && busy && <p className="text-gray-500">Waiting for server…</p>}
          {logs.map((line) => (
            <div
              key={line.id}
              className={line.level === "error" ? "text-red-700" : "text-gray-700"}
            >
              {line.stage && <span className="text-gray-400 mr-2">[{line.stage}]</span>}
              {line.message}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        {busy && hint && <p className="text-xs text-gray-500 mt-2">{hint}</p>}
      </CardContent>
    </Card>
  );
}

/** @deprecated use RunProgressPanel */
export const DailyRunProgress = RunProgressPanel;
