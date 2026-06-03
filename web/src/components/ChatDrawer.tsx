import { Sheet, SheetContent } from "@/components/ui/sheet";
import { TraderChatPanel } from "@/components/TraderChatPanel";
import type { ChatFocus } from "@/context/ChatContext";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  weeklyPlanId?: number;
  focus?: ChatFocus | null;
  sessionKey: number;
};

export function ChatDrawer({ open, onOpenChange, weeklyPlanId, focus, sessionKey }: Props) {
  if (!open) return null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[500px] p-0 flex flex-col gap-0">
        <TraderChatPanel
          key={sessionKey}
          weeklyPlanId={weeklyPlanId}
          focus={focus ?? undefined}
        />
      </SheetContent>
    </Sheet>
  );
}
