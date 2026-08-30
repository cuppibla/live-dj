"""MERCIL Voice Sales Agent — the raw Gemini Live backend.

No framework. One Gemini Live session per browser, two asyncio tasks:
  - upstream:   browser mic (16k PCM)  -> session.send_realtime_input
  - downstream: session.receive()      -> browser (voice bytes + transcripts + play commands)

GOTCHA (the reason it dropped after one turn): session.receive() is a PER-TURN async
generator — it ends when a turn completes. You must call it again in a loop for the next turn.

The consultant also CALLS SALES TOOLS (tools.py) — catalogue search, requirement capture, enquiry
creation — returning INSTANTLY so the voice never stalls mid-sentence.

Everything company-specific (persona, catalogue, rules) comes from config.py, which loads
company-configs/<COMPANY_PROFILE>/. This file is the reusable engine.
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

from backend.config import CONFIG, SYSTEM_INSTRUCTION
from backend.tools import TOOL_DECLARATIONS, dispatch_tool, reset_state

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-sales-agent")

MODEL = os.getenv("LIVE_MODEL", "gemini-3.1-flash-live-preview")
VOICE = os.getenv("LIVE_VOICE", "Aoede")

client = genai.Client()  # reads GOOGLE_API_KEY + GOOGLE_GENAI_USE_VERTEXAI=FALSE from .env

# Pinning the transcription language is Vertex/Enterprise only — the Developer API rejects
# language_codes outright at session open. The profile still declares its languages so the
# setting travels if this ever moves to Vertex; here it is simply dropped.
USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").strip().upper() == "TRUE"
if CONFIG.transcription_languages and not USE_VERTEX:
    log.warning(
        "transcription_languages=%s ignored: the Gemini Developer API does not support "
        "language_codes, so the transcript language is auto-detected and can drift on "
        "short utterances. Vertex AI supports it.", CONFIG.transcription_languages)
TRANSCRIPTION = ({"language_codes": CONFIG.transcription_languages}
                 if USE_VERTEX and CONFIG.transcription_languages else {})

LIVE_CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": SYSTEM_INSTRUCTION,
    # Language hints come from the active company profile, not from here — a customer
    # configured for another market pins its own languages. Empty on the Developer API.
    "input_audio_transcription": TRANSCRIPTION,
    "output_audio_transcription": TRANSCRIPTION,
    "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": VOICE}}},
    "tools": [{"function_declarations": TOOL_DECLARATIONS}],
    # Live sessions accumulate context server-side, so every turn in a long call is
    # priced against a bigger context than the last. The sliding window caps that. It is
    # set well above a demo conversation, so it should never fire during a presentation —
    # it exists to stop an afternoon of rehearsal compounding. The system instruction is
    # never truncated, and the requirements/shortlist live in tools.py rather than in the
    # model's context, so the panels survive a truncation even if the chat memory doesn't.
    "context_window_compression": {
        "trigger_tokens": 20000,
        "sliding_window": {"target_tokens": 10000},
    },
}

app = FastAPI(title="MERCIL Voice Sales Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
ASSETS = Path(__file__).resolve().parents[1] / "assets"


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    reset_state()   # a new browser session is a new customer
    log.info("ws connected; profile=%s (%s); opening Live session (model=%s, voice=%s)",
             CONFIG.profile, CONFIG.company_name, MODEL, VOICE)
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
                        await websocket.send_text(json.dumps(
                            {"type": "transcript", "role": "user", "text": it.text}, ensure_ascii=False))
                    if ot and getattr(ot, "text", None):
                        await websocket.send_text(json.dumps(
                            {"type": "transcript", "role": "agent", "text": ot.text}, ensure_ascii=False))
                    if mt and getattr(mt, "parts", None):
                        for part in mt.parts:
                            idata = getattr(part, "inline_data", None)
                            if idata and getattr(idata, "data", None):
                                await websocket.send_bytes(idata.data)  # 24k voice
                    if getattr(sc, "turn_complete", None):
                        # Closes the current transcript line. Transcription arrives in
                        # fragments; without this the browser can't tell where a sentence
                        # ends and two consecutive replies run together.
                        await websocket.send_text(json.dumps({"type": "turn_end"}))
                    if getattr(sc, "interrupted", None):
                        await websocket.send_text(json.dumps({"type": "interrupted"}))
                if tc:
                    results = []
                    for fc in tc.function_calls:
                        args = dict(getattr(fc, "args", None) or {})
                        events, result = dispatch_tool(fc.name, args)
                        # Log every call: when the screen disagrees with the conversation,
                        # this is the only place the truth is written down.
                        log.info("tool %s(%s) -> %s", fc.name, args,
                                 {k: v for k, v in result.items()
                                  if k not in ("products", "recommendations")})
                        for event in events:
                            await websocket.send_text(json.dumps(event, ensure_ascii=False))
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


@app.get("/api/company")
async def company():
    """The browser reads its own branding from the active profile, so switching
    COMPANY_PROFILE rebrands the UI without touching the frontend."""
    return {
        "product_name": "MERCIL Voice Sales Agent",
        "company_name": CONFIG.company_name,
        "assistant_role": CONFIG.assistant_role,
        "language": CONFIG.language,
        "profile": CONFIG.profile,
    }


if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
