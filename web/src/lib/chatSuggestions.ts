export function getPageContextLabel(
  pathname: string,
  focus?: { type?: string; ticker?: string | null; plan_item_id?: number } | null
): string {
  if (focus?.type === "plan_item") {
    const t = focus.ticker ? ` · ${focus.ticker}` : focus.plan_item_id ? ` #${focus.plan_item_id}` : "";
    return `Plan item${t}`;
  }
  if (focus?.type === "story") return "Story analysis";
  if (focus?.type === "trading_plan") return "Trading plan";
  if (pathname === "/") return "Home Dashboard";
  if (pathname.startsWith("/stories")) return "Stories & Analysis";
  if (pathname.startsWith("/recommendations")) return "Trading Plan";
  if (pathname.startsWith("/portfolio")) return "Portfolio";
  if (pathname.startsWith("/insights")) return "Insights";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Trading Intelligence";
}

export function getContextualGreeting(context: string): string {
  const greetings: Record<string, string> = {
    "Home Dashboard":
      "I can help you understand your portfolio performance, recent analysis, or suggest next steps based on your current positions.",
    "Stories & Analysis":
      "I can explain any story's impact on your portfolio, clarify the three-persona analysis, or suggest which recommendations to prioritize.",
    "Trading Plan":
      "I can help you understand why a recommendation was made, explain the sizing, or discuss how it fits your risk tolerance and portfolio constraints.",
    Portfolio:
      "I can analyze your current allocations, suggest rebalancing opportunities, or explain your positions relative to the trading plan.",
    Insights:
      "I can help interpret your performance metrics and decision history.",
    Settings: "I can explain trading rules and how they affect plan recommendations.",
  };
  return greetings[context] || "I can help you understand your trading data and make better decisions.";
}

export function getSuggestedQuestions(context: string): string[] {
  const questions: Record<string, string[]> = {
    "Home Dashboard": [
      "What should I focus on today?",
      "Should I act on any pending recommendations?",
      "How does my cash position look?",
    ],
    "Stories & Analysis": [
      "How does the latest story affect my holdings?",
      "Which persona should I trust more?",
      "What are the key risks I should watch?",
    ],
    "Trading Plan": [
      "Why were these recommendations made?",
      "How much should I invest in each position?",
      "Which pending items should I prioritize?",
    ],
    Portfolio: [
      "Is my allocation balanced?",
      "Should I rebalance my portfolio?",
      "How do my positions relate to the current plan?",
    ],
    Insights: [
      "What worked in my recent decisions?",
      "Which recommendations should I reconsider?",
    ],
    Settings: ["Explain my trading rules", "What happens if I breach the cash floor?"],
  };
  return (
    questions[context] || [
      "What should I know right now?",
      "Help me understand this data",
      "What action should I take?",
    ]
  );
}
