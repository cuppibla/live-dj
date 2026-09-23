"""Quiet-hours policy for Mira — EP3's `before_tool_callback` (recording copy).

ONE function stands at the door of EVERY tool call. Three verbs:

  - OBSERVE — log the call and return None (the tool runs). Every call, allowed
    or not, streams to the browser's action log via `action_events`.
  - BLOCK   — return a dict. ADK skips the tool and hands that dict to the
    model as the "result", so Mira explains the refusal in character.
  - REWRITE — (not used here) edit `args` in place and return None.

Quiet hours for the shoot are driven by the QUIET_HOURS env var, NOT the real
clock, so a take never depends on what time you record:

    QUIET_HOURS unset/0  -> off (default — cold-open takes work at any hour)
    QUIET_HOURS=1        -> on  (the DEMO #3 "play something loud" -> Blocked take)
    QUIET_HOURS=auto     -> the honest version: 22:00-07:00 by the real clock
"""
import asyncio
import os
from datetime import datetime
from typing import Any, Optional

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

# Tools that START music — the ones quiet hours block. Control tools
# (skip / pause / set_sleep_timer) always pass.
_BLOCKED_DURING_QUIET = {"play_playlist", "play_track"}

# Policy verdicts -> the browser action log (drained by adk_server's policy_feed).
action_events: asyncio.Queue = asyncio.Queue()


def _quiet_hours_active() -> bool:
    mode = os.getenv("QUIET_HOURS", "").strip().lower()
    if mode in {"1", "true", "on", "always"}:
        return True
    if mode == "auto":
        return datetime.now().hour >= 22 or datetime.now().hour < 7
    return False


async def quiet_hours_gate(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    if _quiet_hours_active() and tool.name in _BLOCKED_DURING_QUIET:
        action_events.put_nowait(
            {"tool": tool.name, "args": dict(args), "status": "blocked",
             "reason": "quiet hours (22:00–07:00)"}
        )
        # Returning a dict SKIPS the tool; this dict is what the model sees.
        return {
            "result": "blocked",
            "reason": ("Quiet hours are on (22:00–07:00) — you can't start music "
                       "right now. Let the listener down softly, in character."),
        }
    action_events.put_nowait({"tool": tool.name, "args": dict(args), "status": "ok"})
    return None  # observe only — the tool runs
