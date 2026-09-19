"""live-dj on ADK with abilities — the EP3 backend: tools + the policy gate.

The SAME radio as EP1 (live-dj), rebuilt with Google ADK instead of the raw
google-genai SDK. What the framework does for you, vs EP1's `raw_server.py`:

  - the two hand-rolled asyncio tasks  -> LiveRequestQueue (up) + runner.run_live() (down)
  - the per-turn `while True: session.receive()` loop  -> GONE (run_live is continuous)
  - tool declarations + manual send_tool_response       -> plain Python functions; ADK runs them

A tool returns to the MODEL, not the browser — so the music "play" command is
emitted *here*, in the run_live loop, when we see the function_call (the one
real design call of the rewrite). Everything the browser sees is byte-for-byte
the EP1 protocol, so the copied frontend is unchanged.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.genai import types
from google.adk.runners import Runner, RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.agents import LiveRequestQueue
from google.adk.sessions import InMemorySessionService

from adk_tools.agent import root_agent
from adk_tools.policy import action_events
from adk_tools.tools import to_play_command

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("live-dj-tools")

VOICE = os.getenv("LIVE_VOICE", "Aoede")
APP_NAME = "live-dj-tools"

# ADK owns the session + the run loop (EP1 did both by hand).
session_service = InMemorySessionService()
runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)

RUN_CONFIG = RunConfig(
    streaming_mode=StreamingMode.BIDI,                 # full-duplex live
    response_modalities=["AUDIO"],
    speech_config=types.SpeechConfig(                  # Mira's native voice (EP1 parity)
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
        )
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
)

app = FastAPI(title="live-dj · tools (EP3)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FRONTEND = Path(__file__).resolve().parent / "frontend"   # EP3 ships its own (action-log panel)
ASSETS = Path(__file__).resolve().parents[1] / "assets"


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    log.info("ws connected; opening ADK live session (model=%s, voice=%s)", root_agent.model, VOICE)
    session = await session_service.create_session(app_name=APP_NAME, user_id="listener")
    live_request_queue = LiveRequestQueue()

    async def upstream():
        # browser mic (16k PCM) -> the queue. ADK feeds the queue to Gemini.
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                log.info("upstream: browser disconnected")
                return
            raw = msg.get("bytes")
            if raw:
                live_request_queue.send_realtime(
                    types.Blob(data=raw, mime_type="audio/pcm;rate=16000")
                )

    async def handle(event):
        # mirror EP1's handle(), but the source is an ADK run_live Event.
        it = getattr(event, "input_transcription", None)
        ot = getattr(event, "output_transcription", None)
        if it and getattr(it, "text", None):
            await websocket.send_text(json.dumps({"type": "transcript", "role": "user", "text": it.text}))
        if ot and getattr(ot, "text", None):
            await websocket.send_text(json.dumps({"type": "transcript", "role": "mira", "text": ot.text}))
        content = getattr(event, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                idata = getattr(part, "inline_data", None)
                if idata and getattr(idata, "data", None):
                    await websocket.send_bytes(idata.data)             # 24k voice
                # NOTE (recording copy): the tool -> browser bridge moved to
                # policy_feed(). On ADK 2.2.0 + gemini-3.1-flash-live, run_live
                # BUFFERS function_call/response events while a transcription is
                # streaming (runners.py), so bridging here is late or never. The
                # before_tool_callback fires instantly — so the ONE policy door
                # now feeds both the action log and the play commands.
        if getattr(event, "interrupted", None):
            await websocket.send_text(json.dumps({"type": "interrupted"}))   # barge-in

    async def downstream():
        # ONE continuous loop — no per-turn `while True`. ADK owns the turn-taking.
        async for event in runner.run_live(
            user_id=session.user_id, session_id=session.id,
            live_request_queue=live_request_queue, run_config=RUN_CONFIG,
        ):
            await handle(event)

    async def policy_feed():
        # policy verdicts (from the before_tool_callback) -> the browser:
        #   every verdict -> the action log; allowed ones -> the play command.
        while True:
            verdict = await action_events.get()
            await websocket.send_text(json.dumps({"type": "action", **verdict}))
            if verdict.get("status") == "ok":
                cmd = to_play_command(verdict["tool"], verdict.get("args") or {})
                if cmd:
                    await websocket.send_text(json.dumps({"type": "play", **cmd}))

    while not action_events.empty():   # drop verdicts left over from a previous session
        action_events.get_nowait()

    up = asyncio.create_task(upstream(), name="upstream")
    down = asyncio.create_task(downstream(), name="downstream")
    feed = asyncio.create_task(policy_feed(), name="policy_feed")
    try:
        done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        live_request_queue.close()   # let run_live wind down cleanly before we cancel anything
        for t in done:
            exc = t.exception()
            if exc:
                log.exception("%s task FAILED: %r", t.get_name(), exc, exc_info=exc)
                try:
                    await websocket.send_text(json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}))
                except Exception:
                    pass
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        log.info("ws disconnected")
    finally:
        feed.cancel()
        await asyncio.gather(feed, return_exceptions=True)
        live_request_queue.close()
        log.info("ws closed")


if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
