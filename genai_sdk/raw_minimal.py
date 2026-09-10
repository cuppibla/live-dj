"""live-dj, stripped to the primitive — a live voice agent in ~40 lines.

The whole thing, nothing else: open a session, send the mic up, get voice back,
play it. No framework, no tools, no persona. Everything that makes Mira *Mira*
lives in raw_server.py; this file is just the loop underneath her.

    uv run uvicorn genai_sdk.raw_minimal:app --port 8000
    # open http://localhost:8000 — headphones on — tap the mic and talk

THE GOTCHA (the two lines a coding agent gets wrong):
`session.receive()` is a PER-TURN async generator — it ends the moment the model
finishes one reply. Iterate it once and your agent answers exactly one sentence,
then goes silent forever. It needs an outer `while True`. See play_voice().
"""
import asyncio
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

MODEL = "gemini-3.1-flash-live-preview"
CONFIG = {
    "response_modalities": ["AUDIO"],                                     # she speaks, not types
    "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}}},
}

client = genai.Client()          # GOOGLE_API_KEY + GOOGLE_GENAI_USE_VERTEXAI=FALSE from .env
app = FastAPI(title="live-dj minimal")


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:   # 1. OPEN

        async def send_mic():                          # 2. SEND — browser mic → Gemini
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                if chunk := msg.get("bytes"):          # 16 kHz PCM from the AudioWorklet
                    await session.send_realtime_input(
                        audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))

        async def play_voice():                        # 3. RECEIVE + 4. PLAY — Gemini → speakers
            while True:                                # ← the gotcha: receive() is per-turn
                async for response in session.receive():
                    turn = getattr(response.server_content, "model_turn", None)
                    for part in (turn.parts if turn else []):
                        if part.inline_data and part.inline_data.data:
                            await websocket.send_bytes(part.inline_data.data)   # 24 kHz voice

        up, down = asyncio.create_task(send_mic()), asyncio.create_task(play_voice())
        _, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()


# the same minimal browser client the full app uses (mic worklet + playback + barge-in)
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "frontend", html=True), name="ui")
