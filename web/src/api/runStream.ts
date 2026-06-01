const BASE = import.meta.env.VITE_API_URL || "/api";

function streamHeaders(): HeadersInit {
  const key = localStorage.getItem("apiKey") || "";
  const h: HeadersInit = { Accept: "text/event-stream" };
  if (key) h["X-API-Key"] = key;
  return h;
}

export type RunStreamEvent =
  | { type: "log"; stage?: string; message: string; level?: string }
  | { type: "stage"; stage: string; message?: string }
  | {
      type: "done";
      analysis_run_id?: number | null;
      story_count?: number;
      article_count?: number;
      export_path?: string | null;
      weekly_plan_id?: number;
      item_count?: number;
      no_trade_week?: boolean;
      summary?: string;
      [key: string]: unknown;
    }
  | { type: "error"; message: string };

export function parseSseChunk(buffer: string): { events: RunStreamEvent[]; rest: string } {
  const events: RunStreamEvent[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    for (const line of block.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      try {
        events.push(JSON.parse(line.slice(6)) as RunStreamEvent);
      } catch {
        /* ignore malformed */
      }
    }
  }
  return { events, rest };
}

export async function streamPost(
  path: string,
  onEvent: (event: RunStreamEvent) => void
): Promise<RunStreamEvent> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: streamHeaders(),
  });

  if (!res.ok) {
    const text = await res.text();
    const err: RunStreamEvent = { type: "error", message: text || res.statusText };
    onEvent(err);
    throw new Error(err.message);
  }

  if (!res.body) {
    throw new Error("No response body from stream");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let last: RunStreamEvent = { type: "done" };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.rest;
    for (const ev of parsed.events) {
      onEvent(ev);
      last = ev;
      if (ev.type === "error") throw new Error(ev.message);
    }
  }

  if (buffer.trim()) {
    const parsed = parseSseChunk(buffer + "\n\n");
    for (const ev of parsed.events) {
      onEvent(ev);
      last = ev;
      if (ev.type === "error") throw new Error(ev.message);
    }
  }

  if (last.type !== "done") {
    throw new Error("Stream ended without completion");
  }
  return last;
}
