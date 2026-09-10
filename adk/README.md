# EP2 · the same DJ on Google ADK

Same Mira, same browser, same four tracks — only the plumbing changed. Three files: [`agent.py`](agent.py) · [`tools.py`](tools.py) · [`server.py`](server.py).

![architecture on ADK](../docs/architecture-adk.png)

## What the framework replaced

| You wrote this in EP1 (raw SDK) | ADK gives you this instead |
|---|---|
| Two hand-rolled asyncio tasks (mic up / voice down) | `LiveRequestQueue` for up, `runner.run_live()` for down — see [`server.py`](server.py) |
| `while True: session.receive()` — the per-turn loop you must remember | One continuous `async for event in runner.run_live(...)`. The framework owns the turns. |
| `TOOL_DECLARATIONS` as JSON + `dispatch_tool()` + a manual `send_tool_response` | Plain `async def` functions in [`tools.py`](tools.py). ADK reads the schema from the signature and docstring, runs the tool, and returns the result to the model. |
| You own session history | `Runner` + `InMemorySessionService` — one session per browser |

**The one design call it leaves to you:** a tool's return value goes to the *model*, not the browser. So the `{"type":"play"}` command the music player needs is emitted in the `run_live` loop, when the `function_call` streams past — `to_play_command` in [`tools.py`](tools.py), `handle()` in [`server.py`](server.py). Same instant-return rule as EP1: the tools never block the voice.

**Honest footnote:** ADK holds tool events while a transcription is still streaming (so transcript and action land in order). With a real microphone that's about a second — verified on `google-adk` 2.8.0 + `gemini-3.1-flash-live-preview`. In text-only tests it can look stuck. If you ever need the UI to react before the transcript settles, drive it from a `before_tool_callback` instead — that's EP3.

## Start the app

From the repo root:

```bash
uv sync
cp .env.example .env            # GOOGLE_API_KEY — same key as EP1
uv run uvicorn adk.server:app --port 8000
```

Open <http://localhost:8000>, **headphones on**, tap 🎙. It's the same page as EP1 — that's deliberate.

Try: *"hey Mira"* · *"can you play something dream pop"* · *"skip this"* — then **talk over her** while she's speaking and hear her pick the thread back up.

## Play around in `adk web`

The same agent runs unchanged inside ADK's dev UI. Do this once — it's the best way to *see* the framework: every tool call shows up as an event card while Mira talks.

```bash
uv run adk web . --port 8000
```

1. Open <http://localhost:8000> and pick **`adk`** from the app dropdown.
2. Click the **mic icon** next to the chat box to switch to live audio (allow the mic). Headphones on.
3. Say **"hey Mira"** — she answers in her own voice (Aoede).
4. Say **"can you play something dream pop"** — watch the **Events** panel: a `play_playlist` **function_call** card, then its **function_response**.
5. Say **"skip this"** — another card. Talk over her — she stops mid-word.

What you're looking at: the `Runner` → `Agent` → tool round-trip the framework runs for you, as data. Click any event to inspect it; the **Trace** tab shows the timing.

Things worth knowing:

- **No music plays in adk web.** It has no `<audio>` player and no play-command bridge, so `play_playlist` fires (you'll see it) and nothing plays. Don't ask her "what do you think of the music" here — she believes it's playing. For the actual radio, start the app above.
- **Her voice travels with the agent.** adk web builds its own `RunConfig` with no `speech_config`, so Aoede is attached to the model in [`agent.py`](agent.py) via `Gemini(speech_config=...)` — it works wherever the agent runs.
- adk web writes its session store into `adk/.adk/` — gitignored.
- You can also type instead of talking once audio mode is on; typed text goes down the same live socket.

## What's inside

| | |
|---|---|
| `agent.py` | `Agent(name="mira", tools=[play_playlist, play_track, skip, pause])` on a `Gemini(...)` model that carries the voice |
| `tools.py` | the four tools as plain `async def` functions + `to_play_command`, the model→browser bridge |
| `server.py` | FastAPI `/ws`: `LiveRequestQueue` up, `runner.run_live()` down, `RunConfig(BIDI, AUDIO, transcriptions)` |
| `persona.py` | same wrapper as EP1 (kept local so this folder runs on its own) |
