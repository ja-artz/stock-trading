import React, { createContext, useCallback, useContext, useState } from "react";

export type ChatFocus = {
  type?: string;
  plan_item_id?: number;
  story_index?: number;
  run_id?: number;
  weekly_plan_id?: number;
  ticker?: string | null;
  action?: string | null;
  rationale?: string | null;
  [key: string]: unknown;
};

type ChatContextValue = {
  open: boolean;
  focus: ChatFocus | null;
  weeklyPlanId?: number;
  sessionKey: number;
  openChat: (opts?: { focus?: ChatFocus; weeklyPlanId?: number }) => void;
  closeChat: () => void;
};

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [focus, setFocus] = useState<ChatFocus | null>(null);
  const [weeklyPlanId, setWeeklyPlanId] = useState<number | undefined>();
  const [sessionKey, setSessionKey] = useState(0);

  const openChat = useCallback((opts?: { focus?: ChatFocus; weeklyPlanId?: number }) => {
    setFocus(opts?.focus ?? null);
    setWeeklyPlanId(opts?.weeklyPlanId);
    setSessionKey((k) => k + 1);
    setOpen(true);
  }, []);

  const closeChat = useCallback(() => {
    setOpen(false);
  }, []);

  return (
    <ChatContext.Provider value={{ open, focus, weeklyPlanId, sessionKey, openChat, closeChat }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within ChatProvider");
  return ctx;
}
