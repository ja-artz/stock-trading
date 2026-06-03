import { ChatButton } from "@/components/ChatButton";
import { ChatDrawer } from "@/components/ChatDrawer";
import { useChatContext } from "@/context/ChatContext";

export function AgentChatDrawer() {
  const { open, focus, weeklyPlanId, sessionKey, closeChat } = useChatContext();

  return (
    <>
      <ChatButton />
      <ChatDrawer
        open={open}
        onOpenChange={(next) => {
          if (!next) closeChat();
        }}
        weeklyPlanId={weeklyPlanId}
        focus={focus}
        sessionKey={sessionKey}
      />
    </>
  );
}
