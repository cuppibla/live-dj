"""Mira as an ADK agent with abilities (EP3): tools + ONE policy door.

Same persona, same tools as EP1's raw build — but expressed the framework way:
an `Agent` with plain-function tools. The Runner + LiveRequestQueue + run_live
(in adk_server.py) replace EP1's two hand-rolled asyncio tasks and the per-turn
receive() loop.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from adk_tools.persona import MIRA_INSTRUCTION
from adk_tools.policy import quiet_hours_gate
from adk_tools.tools import play_playlist, play_track, skip, pause, set_sleep_timer

# Recording-copy note: policy lives in CODE (the quiet_hours_gate), not in the
# persona — so Mira must always ATTEMPT the tool and let the gate decide.
# Without this, she deflects requests like "play something loud" in character
# and the on-camera "⛔ blocked" moment never happens.
_POLICY_NOTE = (
    "\n\nwhen the listener asks for music — any mood, any volume — always call the "
    "play_playlist tool first. never refuse or redirect a music request on your own: "
    "the radio's policy system decides what's allowed. if a call comes back blocked, "
    "relay the reason softly, in your own words."
)

root_agent = Agent(
    # Gemini(...) carries the voice with the agent, so `adk web` uses Aoede too.
    model=Gemini(
        model=os.getenv("LIVE_MODEL", "gemini-3.1-flash-live-preview"),
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=os.getenv("LIVE_VOICE", "Aoede")))),
    ),
    name="mira",
    instruction=MIRA_INSTRUCTION + _POLICY_NOTE,
    tools=[play_playlist, play_track, skip, pause, set_sleep_timer],
    before_tool_callback=quiet_hours_gate,
)
