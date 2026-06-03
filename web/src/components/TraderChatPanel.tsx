import React, { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAgentChat } from "@/hooks/useAgentChat";
import type { PlanRevisionPreview } from "@/api/client";
import {
  getContextualGreeting,
  getPageContextLabel,
  getSuggestedQuestions,
} from "@/lib/chatSuggestions";
import { Loader2, Send, Sparkles } from "lucide-react";

type Props = {
  weeklyPlanId?: number;
  focus?: Record<string, unknown>;
  onPlanUpdated?: () => void;
};

function RevisionDiffCard({
  preview,
  onApply,
  onDismiss,
  busy,
}: {
  preview: PlanRevisionPreview;
  onApply: () => void;
  onDismiss: () => void;
  busy: boolean;
}) {
  return (
    <Card className="border-violet-200 bg-violet-50/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Proposed plan changes</CardTitle>
        {preview.summary && <p className="text-sm text-gray-700">{preview.summary}</p>}
      </CardHeader>
      <CardContent className="space-y-3">
        {preview.errors && preview.errors.length > 0 && (
          <Alert className="border-red-200 bg-red-50">
            <AlertDescription>
              <ul className="list-disc pl-4 text-sm">
                {preview.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
        {preview.warnings && preview.warnings.length > 0 && (
          <ul className="text-xs text-amber-800 list-disc pl-4">
            {preview.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
        <div className="space-y-2 text-sm">
          {(preview.after || []).map((ch, i) => (
            <div key={i} className="rounded border bg-white p-2">
              <Badge variant="outline" className="mb-1 capitalize">
                {ch.op}
                {ch.plan_item_id != null ? ` #${ch.plan_item_id}` : ""}
              </Badge>
              {ch.removed ? (
                <p className="text-gray-600">Remove line item</p>
              ) : ch.item ? (
                <p>
                  <span className="font-medium">{ch.item.action}</span>{" "}
                  {ch.item.ticker || "—"} — {ch.item.sizing_summary || ch.item.rationale?.slice(0, 80)}
                </p>
              ) : null}
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={onApply} disabled={busy || !preview.ok}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Apply changes"}
          </Button>
          <Button size="sm" variant="outline" onClick={onDismiss} disabled={busy}>
            Dismiss
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function FocusBanner({
  focus,
  preview,
}: {
  focus?: Record<string, unknown>;
  preview?: Record<string, unknown> | null;
}) {
  const item = (preview || focus) as Record<string, unknown>;
  if (focus?.type !== "plan_item") return null;

  const ticker = (item.ticker as string) || "—";
  const action = (item.action as string) || "";
  const rationale = (item.rationale as string) || (item.sizing_summary as string) || "";

  return (
    <div className="p-3 rounded-lg border border-violet-200 bg-violet-50 text-sm">
      <p className="font-medium text-violet-900">Discussing plan line #{String(item.id ?? focus.plan_item_id)}</p>
      <p className="mt-1 text-violet-800">
        <span className="capitalize">{action}</span> {ticker}
      </p>
      {rationale ? <p className="mt-2 text-gray-700 line-clamp-3">{rationale}</p> : null}
    </div>
  );
}

function visibleMessages(messages: ReturnType<typeof useAgentChat>["messages"]) {
  return messages.filter((m) => m.role === "user" || m.role === "assistant");
}

export function TraderChatPanel({ weeklyPlanId, focus, onPlanUpdated }: Props) {
  const location = useLocation();
  const chat = useAgentChat(1);
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const focusRecord = focus as { type?: string; ticker?: string | null; plan_item_id?: number } | undefined;
  const pageContext = getPageContextLabel(location.pathname, focusRecord);
  const focusedItem =
    chat.focusPreview?.focused_plan_item ||
    (focus?.type === "plan_item" ? focus : null);

  useEffect(() => {
    chat.reset();
    void chat.ensureThread({
      weeklyPlanId,
      focus,
      title: focus?.type === "plan_item" ? "Discuss recommendation" : "Trading plan chat",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weeklyPlanId, JSON.stringify(focus)]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages, chat.busy]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || chat.busy || !chat.thread) return;
    setDraft("");
    await chat.send(text, focus);
  };

  const handleApply = async () => {
    const ok = await chat.applyRevision();
    if (ok) {
      onPlanUpdated?.();
      window.dispatchEvent(new CustomEvent("trading-plan-updated"));
    }
  };

  const displayed = visibleMessages(chat.messages);
  const suggested = getSuggestedQuestions(
    focus?.type === "plan_item" ? "Trading Plan" : pageContext
  );

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-6 pt-2 pb-4 border-b shrink-0">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h2 className="font-semibold text-gray-900">Trading Agent</h2>
            <p className="text-xs text-gray-500">Context: {pageContext}</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 min-h-0">
        <FocusBanner focus={focus} preview={focusedItem as Record<string, unknown> | null} />

        {chat.busy && !displayed.length && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" /> Connecting…
          </div>
        )}

        {displayed.length === 0 && !chat.busy && !chat.error && (
          <div className="space-y-4">
            <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
              <p className="text-sm text-blue-900">
                Hi! I&apos;m your household trader agent. {getContextualGreeting("Trading Plan")}
              </p>
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium text-gray-600 uppercase tracking-wide">Suggested questions</p>
              {suggested.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => setDraft(question)}
                  className="w-full text-left p-3 text-sm bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-200 transition-colors"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        {displayed.map((m) => (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-lg p-3 text-sm whitespace-pre-wrap ${
                m.role === "user" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-900"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}

        {chat.busy && displayed.length > 0 && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg p-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}

        {chat.pendingRevision?.preview && (
          <RevisionDiffCard
            preview={chat.pendingRevision.preview}
            onApply={handleApply}
            onDismiss={chat.dismissRevision}
            busy={chat.busy}
          />
        )}

        {chat.error && (
          <Alert className="border-red-200 bg-red-50">
            <AlertDescription className="text-sm break-words">{chat.error}</AlertDescription>
          </Alert>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="border-t p-4 shrink-0">
        <div className="flex gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
            placeholder="Ask about recommendations, portfolio, or analysis..."
            className="flex-1"
            disabled={!chat.thread || chat.busy}
          />
          <Button
            type="button"
            size="icon"
            onClick={() => void submit()}
            disabled={!chat.thread || chat.busy || !draft.trim()}
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
