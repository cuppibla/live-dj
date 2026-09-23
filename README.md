# live-dj — a voice agent you can interrupt

Talk to **Mira**, a late-night radio DJ. Ask her to play something. Talk over her mid-sentence and she stops, listens, and picks the thread back up.

Built on the **Gemini Live API** — three times over, with the same browser and the same Mira: raw SDK, then ADK, then ADK with real abilities and a policy gate — so you can see exactly what each layer buys you.

![live-dj](docs/screenshot.png)

## Three builds, one app

| Folder | Episode | What's inside |
|---|---|---|
| [`genai_sdk/`](genai_sdk/) | **EP1** — raw `google-genai` SDK | The whole primitive with no framework: a **39-line** `raw_minimal.py`, the full `raw_server.py`, and the gotcha that makes voice agents go silent after one sentence. |
| [`adk/`](adk/) | **EP2** — Google ADK | The same DJ rebuilt on `LiveRequestQueue` + `run_live` + plain-function tools — plus how to run her inside **`adk web`** and watch the tool calls land as events. |
| [`adk_tools/`](adk_tools/) | **EP3** — abilities | A new tool she can act on mid-sentence (`set_sleep_timer`), and **one policy door** every tool call passes through — a `before_tool_callback` that observes or **blocks**, with an action log that shows the verdict live. |

`frontend/` and `assets/` sit at the root because EP1 and EP2 share them **byte for byte** — that's the point. EP3 ships its own copy of the frontend (it grows an action-log panel).

## Quick start

```bash
uv sync
cp .env.example .env          # paste your GOOGLE_API_KEY (Gemini Developer API / AI Studio, not Vertex)

uv run uvicorn genai_sdk.raw_server:app --port 8000     # EP1 · the DJ on the raw SDK
uv run uvicorn adk.server:app --port 8000               # EP2 · the same DJ on ADK
uv run uvicorn adk_tools.server:app --port 8000         # EP3 · abilities + the policy gate (QUIET_HOURS=1 for the blocked take)
uv run adk web . --port 8000                            # EP2/EP3 · the same agents inside ADK's dev UI
```

Open <http://localhost:8000>, **put headphones on** (otherwise she hears her own radio), tap 🎙 and talk.

Try: *"hey Mira"* · *"can you play something dream pop"* · *"skip this"* · *"what do you think of the music?"* — then **talk over her** while she's speaking.

## What's shared

| | |
|---|---|
| `frontend/` | minimal browser client: 16 kHz mic worklet, 24 kHz playback, client-side barge-in, music ducking |
| `assets/tracks/` · `assets/mira_persona.txt` | four dream-pop tracks and who Mira is |
| `docs/` | architecture diagrams for all three builds, the product / UX / engineering design docs, the de-risk test |

## Notes

- **Voice** is a Gemini Live *native* voice (`LIVE_VOICE`, default `Aoede`) — the Live API has its own voice set, so it can't reproduce a TTS voice you used elsewhere. The persona carries the character, not the timbre.
- **Barge-in** is client-side: the browser cuts playback the instant the mic hears you (RMS gate in `frontend/main.js`), which feels faster than waiting for the server signal. The server forwards `interrupted` too.
- **Music ducking** drops the track to 12% while Mira speaks, then brings it back.
- The four tracks and Mira's persona come from **aniradio**, a static AI-radio app of mine — the music is generated with **Lyria 3 Pro**.

## Going deeper

A second ADK live app (NOVA — voice + camera) plus a raw-SDK-vs-ADK exercise lives in [`cuppibla/multimodal-levels`](https://github.com/cuppibla/multimodal-levels) → `05-live/`.
