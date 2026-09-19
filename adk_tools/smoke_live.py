"""Live smoke test for the EP3 recording copy — no mic needed.

Drives Mira through three text turns (a fresh live session each) and checks the
three EP3 demo beats end-to-end against the real live model:

  1. QUIET_HOURS off: "play something dream pop"   -> play_playlist runs (allowed)
  2. QUIET_HOURS on:  "play something loud"        -> the gate BLOCKS play_playlist
  3. sleep timer:     "stop the music in 30 min"   -> set_sleep_timer(minutes=30)

Run from the repo root:  uv run python adk_tools/smoke_live.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo root

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from google.genai import types
from google.adk.runners import Runner, RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.agents import LiveRequestQueue
from google.adk.sessions import InMemorySessionService

from adk_tools.agent import root_agent
from adk_tools.policy import action_events

RUN_CONFIG = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    response_modalities=["AUDIO"],
    output_audio_transcription=types.AudioTranscriptionConfig(),
)

session_service = InMemorySessionService()
runner = Runner(app_name="smoke", agent=root_agent, session_service=session_service)


async def one_turn(label: str, text: str, seconds: float = 22.0, attempts: int = 2):
    for attempt in range(1, attempts + 1):
        session = await session_service.create_session(app_name="smoke", user_id="tester")
        queue = LiveRequestQueue()
        calls, responses, transcript, errors = [], [], [], []

        async def consume():
            try:
                async for event in runner.run_live(
                    user_id=session.user_id, session_id=session.id,
                    live_request_queue=queue, run_config=RUN_CONFIG,
                ):
                    ot = getattr(event, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        transcript.append(ot.text)
                    content = getattr(event, "content", None)
                    for part in (getattr(content, "parts", None) or []):
                        fc = getattr(part, "function_call", None)
                        if fc:
                            calls.append((fc.name, dict(getattr(fc, "args", None) or {})))
                        fr = getattr(part, "function_response", None)
                        if fr:
                            responses.append((fr.name, dict(getattr(fr, "response", None) or {})))
            except Exception as e:  # live-service flakes (1011 etc.) — report, don't crash
                errors.append(f"{type(e).__name__}: {e}")

        task = asyncio.create_task(consume())
        queue.send_content(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        waited = 0.0
        while waited < seconds and not task.done():
            await asyncio.sleep(0.5)
            waited += 0.5
        queue.close()
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.TimeoutError:
            task.cancel()

        verdicts = []
        while not action_events.empty():
            verdicts.append(action_events.get_nowait())

        if errors and not (calls or verdicts) and attempt < attempts:
            print(f"\n=== {label} === attempt {attempt} hit a live-service error, retrying: {errors[0]}")
            await asyncio.sleep(3)
            continue

        print(f"\n=== {label} ===")
        print("  you said:    ", text)
        print("  tool calls:  ", calls or "(none)")
        print("  tool results:", responses or "(none)")
        print("  policy log:  ", verdicts or "(none)")
        print("  mira said:   ", ("".join(transcript)).strip() or "(no transcript)")
        if errors:
            print("  errors:      ", errors)
        return calls, responses, verdicts


async def main():
    # The browser bridge runs off the POLICY verdicts (the before_tool_callback),
    # not off run_live's function events — those get buffered by ADK while a
    # transcription streams (runners.py) and can arrive late or never on
    # gemini-3.1-flash-live. So the checks below assert on the verdicts, and
    # simulate exactly what the browser would receive.
    from adk_tools.tools import to_play_command

    def bridged(verdicts):
        return [to_play_command(v["tool"], v.get("args") or {})
                for v in verdicts if v.get("status") == "ok"]

    os.environ["QUIET_HOURS"] = "0"
    calls, responses, verdicts = await one_turn(
        "1 · allowed (quiet hours OFF)", "hey mira, play something dream pop")
    cmds = bridged(verdicts)
    print("  -> browser gets:", cmds)
    ok1 = any(v["tool"] == "play_playlist" and v["status"] == "ok" for v in verdicts) \
        and any(c and c["action"] == "playlist" for c in cmds)

    os.environ["QUIET_HOURS"] = "1"
    calls, responses, verdicts = await one_turn(
        "2 · blocked (QUIET_HOURS=1)", "mira, play something loud")
    cmds = bridged(verdicts)
    print("  -> browser gets:", cmds)
    ok2 = any(v.get("status") == "blocked" for v in verdicts) and not any(
        c and c["action"] in ("playlist", "track") for c in cmds)

    os.environ["QUIET_HOURS"] = "0"
    calls, responses, verdicts = await one_turn(
        "3 · sleep timer", "mira, stop the music in thirty minutes")
    cmds = bridged(verdicts)
    print("  -> browser gets:", cmds)
    ok3 = any(v["tool"] == "set_sleep_timer" and v.get("args", {}).get("minutes") == 30
              and v["status"] == "ok" for v in verdicts) \
        and any(c and c["action"] == "sleep_timer" and c["value"] == 30 for c in cmds)

    print("\n--- verdict ---")
    print("  1 allowed play:      ", "PASS" if ok1 else "FAIL")
    print("  2 quiet-hours block: ", "PASS" if ok2 else "FAIL")
    print("  3 set_sleep_timer:   ", "PASS" if ok3 else "FAIL")
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
