import { MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useChatContext } from "@/context/ChatContext";

export function ChatButton() {
  const { openChat } = useChatContext();

  return (
    <div className="fixed bottom-6 right-6 z-40">
      <Button
        type="button"
        onClick={() => openChat()}
        size="lg"
        className="h-14 w-14 rounded-full shadow-lg bg-gradient-to-br from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700 p-0"
        aria-label="Open trading agent chat"
      >
        <MessageCircle className="w-6 h-6 text-white" />
      </Button>
    </div>
  );
}
