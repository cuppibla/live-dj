"""Mira as an ADK agent (EP2).

Same persona, same tools as EP1's raw build — but expressed the framework way:
an `Agent` with plain-function tools. The Runner + LiveRequestQueue + run_live
(in server.py) replace EP1's two hand-rolled asyncio tasks and the per-turn
receive() loop.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from google.adk.agents import Agent

from backend.persona import MIRA_INSTRUCTION
from backend.adk.tools import play_playlist, play_track, skip, pause

root_agent = Agent(
    model=os.getenv("LIVE_MODEL", "gemini-3.1-flash-live-preview"),
    name="mira",
    instruction=MIRA_INSTRUCTION,
    tools=[play_playlist, play_track, skip, pause],
)
