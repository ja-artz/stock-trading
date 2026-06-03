"""Multi-turn chat with the household trader agent."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

import config
from analysis_agent import AnalysisAgent
from core.trader_context import build_trader_context
from core import store


_REVISION_BLOCK_RE = re.compile(
    r'```(?:json)?\s*(\{[\s\S]*?"intent"\s*:\s*"revise_plan"[\s\S]*?\})\s*```',
    re.IGNORECASE,
)


class TraderChatAgent:
    def __init__(self) -> None:
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL
        self._parser = AnalysisAgent()

    def _messages_create(
        self,
        system: str,
        messages: List[dict[str, str]],
        max_tokens: int = 4096,
    ) -> str:
        max_attempts = getattr(config, "ANTHROPIC_MAX_RETRIES", 6)
        base_delay = getattr(config, "ANTHROPIC_RETRY_BASE_DELAY_SEC", 2.0)
        last_exc = None
        for attempt in range(max_attempts):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                )
                return self._parser._extract_response_text(message)
            except Exception as e:
                last_exc = e
                if not self._parser._is_retryable_anthropic(e) or attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2**attempt) + random.uniform(0, 1.5)
                time.sleep(delay)
        raise last_exc

    def _build_system_prompt(self, ctx: dict[str, Any]) -> str:
        plan = ctx.get("current_plan") or {}
        items = plan.get("items") or []
        item_ids = [i.get("id") for i in items if i.get("id")]
        focus = ctx.get("focus") or {}
        focused = ctx.get("focused_plan_item")
        focus_block = ""
        if focus.get("type") == "plan_item" and focused:
            focus_block = f"""

The user opened this chat to discuss ONE plan line item (priority {focused.get("priority")}, id {focused.get("id")}):
{json.dumps(focused, indent=2)}
Address this line first unless they change topic."""
        elif focus.get("type") == "story" and ctx.get("focused_story"):
            focus_block = f"""

The user is focused on this story from analysis:
{json.dumps(ctx.get("focused_story"), indent=2)[:8000]}"""
        return f"""You are the household trader agent in a live chat with the portfolio owner.

Ground truth (never contradict):
- Portfolio state, trading rules, and market_quotes in the context JSON.
- Current trading plan line items include database ids — use these exact plan_item_id values in revisions.
- Accepted and deferred recommendations are commitments unless the user explicitly asks to change them.
- Rejected items stay rejected unless the user explicitly asks to reconsider.

Your role:
- Discuss, defend, or challenge recommendations with clear reasoning tied to analysis and the book.
- Offer general market insight when asked; stay honest about uncertainty.
- Do NOT invent stock prices; use market_quotes only.
- Do NOT claim trades were executed; the household logs trades manually in Sofi.

Capital tiers (capital_tier on plan items): T1 Quick Strike, T2 Core Opportunity, T3 Long Conviction, T4 Dry Powder (cash only). See tier_discipline.tier_catalog in context for budgets and open action items.

Plan revisions:
- You cannot persist changes yourself. When the user wants concrete plan edits (or you conclude edits are warranted), include a JSON block at the END of your reply:

```json
{{
  "intent": "revise_plan",
  "summary": "Brief reason for changes",
  "changes": [
    {{ "op": "update", "plan_item_id": <id>, "patch": {{ ...fields... }} }},
    {{ "op": "add", "item": {{ ...full line item... }} }},
    {{ "op": "remove", "plan_item_id": <id>, "reason": "..." }}
  ]
}}
```

- Only use plan_item_id values from the current plan: {item_ids}
- For updates, patch only fields that change (action, rationale, sizing object, horizon, etc.).
- Pending items may be removed; accepted items cannot be removed (propose trim/sell instead).
- If no plan changes are needed, do NOT include the JSON block — respond in prose only.

Keep replies focused and conversational (under ~400 words unless the user asks for depth).{focus_block}

Portfolio and plan context (ground truth JSON):
{self._context_block(ctx)[:60000]}"""

    def _context_block(self, ctx: dict[str, Any]) -> str:
        block = {
            "plan_as_of": ctx.get("plan_as_of"),
            "analysis_run": ctx.get("analysis_run"),
            "rules": ctx.get("rules"),
            "nav_state": ctx.get("nav_state"),
            "current_plan": ctx.get("current_plan"),
            "recent_plans": ctx.get("recent_plans"),
            "last_plan_timing": ctx.get("last_plan_timing"),
            "market_quotes": ctx.get("market_quotes", {}).get("quotes"),
            "analysis_stories": ctx.get("analysis_stories"),
            "focus": ctx.get("focus"),
            "focused_plan_item": ctx.get("focused_plan_item"),
            "focused_story": ctx.get("focused_story"),
            "tier_discipline": ctx.get("tier_discipline"),
        }
        return json.dumps(block, indent=2, default=str)

    def _messages_for_api(self, history: List[dict], user_message: str) -> List[dict[str, str]]:
        """Build alternating user/assistant messages for the Anthropic API."""
        messages: List[dict[str, str]] = []
        for msg in history:
            role = (msg.get("role") or "").strip().lower()
            content = (msg.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + content
                continue
            messages.append({"role": role, "content": content})
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] += "\n\n" + user_message
        else:
            messages.append({"role": "user", "content": user_message})
        if not messages:
            messages.append({"role": "user", "content": user_message})
        return messages

    def _extract_plan_revision(self, text: str) -> Optional[dict]:
        match = _REVISION_BLOCK_RE.search(text)
        if match:
            try:
                obj = json.loads(match.group(1))
                if obj.get("intent") == "revise_plan" and obj.get("changes"):
                    return obj
            except json.JSONDecodeError:
                pass
        try:
            obj = self._parser._parse_json_object(text)
            if obj.get("intent") == "revise_plan" and obj.get("changes"):
                return obj
        except Exception:
            pass
        return None

    def _strip_revision_block(self, text: str) -> str:
        cleaned = _REVISION_BLOCK_RE.sub("", text).strip()
        return cleaned or text.strip()

    def reply(
        self,
        thread_id: int,
        user_message: str,
        *,
        portfolio_id: int,
        weekly_plan_id: Optional[int] = None,
        focus: Optional[dict] = None,
    ) -> dict[str, Any]:
        thread = store.get_chat_thread(thread_id, portfolio_id)
        if not thread:
            raise ValueError("Chat thread not found")

        plan_id = weekly_plan_id or thread.get("weekly_plan_id")
        merged_focus = dict(thread.get("focus") or {})
        if focus:
            merged_focus.update(focus)

        ctx = build_trader_context(
            portfolio_id,
            weekly_plan_id=plan_id,
            focus=merged_focus or None,
            include_full_analysis=merged_focus.get("type") == "story",
            fetch_quotes=True,
        )
        if plan_id and ctx.get("current_plan"):
            ctx["current_plan"]["weekly_plan_id"] = plan_id

        if focus:
            store.update_chat_thread_focus(thread_id, portfolio_id, merged_focus)

        system = self._build_system_prompt(ctx)
        history = store.get_chat_messages(thread_id)
        api_messages = self._messages_for_api(history, user_message)

        try:
            raw = self._messages_create(system, api_messages)
        except Exception:
            raise

        revision = self._extract_plan_revision(raw)
        display = self._strip_revision_block(raw)

        store.add_chat_message(thread_id, "user", user_message)

        meta: dict[str, Any] = {}
        if revision:
            meta["plan_revision"] = revision
            wid = plan_id or (ctx.get("current_plan") or {}).get("id")
            if wid:
                from core.plan_revision import preview_plan_revision

                try:
                    preview = preview_plan_revision(
                        portfolio_id,
                        int(wid),
                        revision,
                        quote_bundle=ctx.get("market_quotes"),
                    )
                    meta["plan_revision_preview"] = preview
                    store.save_plan_revision_proposal(
                        thread_id=thread_id,
                        weekly_plan_id=int(wid),
                        portfolio_id=portfolio_id,
                        revision=revision,
                        preview=preview,
                        status="pending",
                    )
                except Exception as exc:
                    meta["plan_revision_preview_error"] = str(exc)

        msg_id = store.add_chat_message(thread_id, "assistant", display, meta)

        return {
            "message_id": msg_id,
            "role": "assistant",
            "content": display,
            "plan_revision": revision,
            "plan_revision_preview": meta.get("plan_revision_preview"),
            "weekly_plan_id": plan_id or (ctx.get("current_plan") or {}).get("id"),
        }
