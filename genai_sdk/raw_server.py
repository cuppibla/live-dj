"""live-dj — the raw Gemini Live backend (EP1).

No framework. One Gemini Live session per browser, two asyncio tasks:
  - upstream:   browser mic (16k PCM)  -> session.send_realtime_input
  - downstream: session.receive()      -> browser (voice bytes + transcripts + play commands)

GOTCHA (the reason it dropped after one turn): session.receive() is a PER-TURN async
generator — it ends when a turn completes. You must call it again in a loop for the next turn.

Mira also CONTROLS MUSIC via function calling (tools.py), returning INSTANTLY so the voice never stalls.
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
from google import genai
from google.genai import types

from genai_sdk.persona import MIRA_INSTRUCTION
from genai_sdk.tools import TOOL_DECLARATIONS, dispatch_tool

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("live-dj")

MODEL = os.getenv("LIVE_MODEL", "gemini-3.1-flash-live-preview")
VOICE = os.getenv("LIVE_VOICE", "Aoede")

client = genai.Client()  # reads GOOGLE_API_KEY + GOOGLE_GENAI_USE_VERTEXAI=FALSE from .env

LIVE_CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": MIRA_INSTRUCTION,
    "input_audio_transcription": {},
    "output_audio_transcription": {},
    "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": VOICE}}},
    "tools": [{"function_declarations": TOOL_DECLARATIONS}],
}

app = FastAPI(title="live-dj")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
ASSETS = Path(__file__).resolve().parents[1] / "assets"


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    log.info("ws connected; opening Live session (model=%s, voice=%s)", MODEL, VOICE)
    try:
        async with client.aio.live.connect(model=MODEL, config=LIVE_CONFIG) as session:
            log.info("Live session open")

            async def upstream():
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        log.info("upstream: browser disconnected")
                        return
                    raw = msg.get("bytes")
                    if raw:
                        await session.send_realtime_input(
                            audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000"))

            async def handle(response):
                sc = getattr(response, "server_content", None)
                tc = getattr(response, "tool_call", None)
                if sc is not None:
                    it = getattr(sc, "input_transcription", None)
                    ot = getattr(sc, "output_transcription", None)
                    mt = getattr(sc, "model_turn", None)
                    if it and getattr(it, "text", None):
                        await websocket.send_text(json.dumps({"type": "transcript", "role": "user", "text": it.text}))
                    if ot and getattr(ot, "text", None):
                        await websocket.send_text(json.dumps({"type": "transcript", "role": "mira", "text": ot.text}))
                    if mt and getattr(mt, "parts", None):
                        for part in mt.parts:
                            idata = getattr(part, "inline_data", None)
                            if idata and getattr(idata, "data", None):
                                await websocket.send_bytes(idata.data)  # 24k voice
                    if getattr(sc, "interrupted", None):
                        await websocket.send_text(json.dumps({"type": "interrupted"}))
                if tc:
                    results = []
                    for fc in tc.function_calls:
                        cmd, result = dispatch_tool(fc.name, dict(getattr(fc, "args", None) or {}))
                        if cmd:
                            await websocket.send_text(json.dumps({"type": "play", **cmd}))
                        results.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
                    await session.send_tool_response(function_responses=results)

            async def downstream():
                # session.receive() ends after each turn — loop it for the whole conversation.
                empty = 0
                while True:
                    got = 0
                    try:
                        async for response in session.receive():
                            got += 1
                            await handle(response)
                    except Exception:
                        log.exception("downstream: receive() raised — ending")
                        return
                    if got == 0:
                        empty += 1
                        if empty >= 2:
                            log.info("downstream: receive() empty %dx — session closed, ending", empty)
                            return
                    else:
                        empty = 0  # a real turn ended; wait for the next one

            up = asyncio.create_task(upstream(), name="upstream")
            down = asyncio.create_task(downstream(), name="downstream")
            done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc:
                    log.exception("%s task FAILED: %r", t.get_name(), exc, exc_info=exc)
                    try:
                        await websocket.send_text(json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}))
                    except Exception:
                        pass
                else:
                    log.info("%s task ended -> tearing down", t.get_name())
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        log.info("ws disconnected")
    except Exception as e:
        log.exception("ws handler error")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": f"{type(e).__name__}: {e}"}))
        except Exception:
            pass
    log.info("ws closed")


if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
