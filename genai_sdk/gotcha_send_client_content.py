"""EP1's "where the AI got it wrong" — kept runnable so the failure is real on camera.

Prompt a coding agent with "send the user's mic audio to the Gemini Live session" and it
very often reaches for send_client_content — it's the documented way to send *content*.
But live audio is a STREAM, not a discrete turn. send_client_content is only for seeding
history before the conversation; used for the mic, the live turn never fires and you get dead air.

The fix is one line: send_realtime_input. (That's what raw_server.py uses.)
"""
from google.genai import types


# ❌ THE WRONG WAY — what the AI tends to write.
async def send_mic_audio_WRONG(session, pcm_16k: bytes):
    await session.send_client_content(
        turns=types.Content(
            role="user",
            parts=[types.Part(inline_data=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000"))],
        )
    )
    # → the live turn doesn't fire as expected. dead air.


# ✅ THE RIGHT WAY — live input is a continuous realtime stream.
async def send_mic_audio_RIGHT(session, pcm_16k: bytes):
    await session.send_realtime_input(
        audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
    )
