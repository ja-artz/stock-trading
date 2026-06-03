import { useCallback, useState } from "react";
import {
  api,
  type ChatMessage,
  type ChatThread,
  type PlanRevision,
  type PlanRevisionPreview,
} from "@/api/client";

export type FocusPreview = {
  focus?: Record<string, unknown>;
  focused_plan_item?: Record<string, unknown> | null;
  focused_story?: Record<string, unknown> | null;
  error?: string;
};

function parseApiError(e: unknown): string {
  const raw = String(e);
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* plain text */
  }
  return raw || "Request failed";
}

export function useAgentChat(portfolioId = 1) {
  const [thread, setThread] = useState<ChatThread | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [focusPreview, setFocusPreview] = useState<FocusPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingRevision, setPendingRevision] = useState<{
    revision: PlanRevision;
    preview?: PlanRevisionPreview;
    weeklyPlanId: number;
  } | null>(null);

  const reset = useCallback(() => {
    setThread(null);
    setMessages([]);
    setFocusPreview(null);
    setError(null);
    setPendingRevision(null);
  }, []);

  const ensureThread = useCallback(
    async (opts?: { weeklyPlanId?: number; focus?: Record<string, unknown>; title?: string }) => {
      setError(null);
      try {
        const res = await api.post<{ thread: ChatThread; focus_preview?: FocusPreview }>(
          "/chat/threads",
          {
            portfolio_id: portfolioId,
            weekly_plan_id: opts?.weeklyPlanId,
            focus: opts?.focus,
            title: opts?.title,
          }
        );
        setThread(res.thread);
        setFocusPreview(res.focus_preview ?? null);
        const hist = await api.get<{ messages: ChatMessage[] }>(
          `/chat/threads/${res.thread.id}/messages?portfolio_id=${portfolioId}`
        );
        setMessages(hist.messages);
        return res.thread;
      } catch (e) {
        setError(parseApiError(e));
        throw e;
      }
    },
    [portfolioId]
  );

  const send = useCallback(
    async (content: string, focus?: Record<string, unknown>) => {
      if (!thread) return;
      setBusy(true);
      setError(null);
      setPendingRevision(null);
      try {
        const res = await api.post<{
          content: string;
          plan_revision?: PlanRevision;
          plan_revision_preview?: PlanRevisionPreview;
          weekly_plan_id?: number;
        }>(`/chat/threads/${thread.id}/messages?portfolio_id=${portfolioId}`, {
          content,
          focus,
        });
        const hist = await api.get<{ messages: ChatMessage[] }>(
          `/chat/threads/${thread.id}/messages?portfolio_id=${portfolioId}`
        );
        setMessages(hist.messages);
        if (res.plan_revision && res.weekly_plan_id) {
          setPendingRevision({
            revision: res.plan_revision,
            preview: res.plan_revision_preview,
            weeklyPlanId: res.weekly_plan_id,
          });
        }
      } catch (e) {
        setError(parseApiError(e));
      } finally {
        setBusy(false);
      }
    },
    [thread, portfolioId]
  );

  const applyRevision = useCallback(async () => {
    if (!pendingRevision) return false;
    setBusy(true);
    setError(null);
    try {
      await api.post("/chat/plan-revisions/apply", {
        portfolio_id: portfolioId,
        weekly_plan_id: pendingRevision.weeklyPlanId,
        revision: pendingRevision.revision,
        thread_id: thread?.id,
      });
      setPendingRevision(null);
      return true;
    } catch (e) {
      setError(parseApiError(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, [pendingRevision, portfolioId, thread?.id]);

  const dismissRevision = useCallback(() => setPendingRevision(null), []);

  return {
    thread,
    messages,
    focusPreview,
    busy,
    error,
    pendingRevision,
    reset,
    ensureThread,
    send,
    applyRevision,
    dismissRevision,
    setError,
  };
}
