# Diagrams

Four hand-authored SVGs explaining how `live-dj` works. Sized for screen and slides
(1600×900, rendered at 2× → 3200×1800 PNG). Sources in `svg/`, renders in `png/`.

| | Diagram | What it shows |
|---|---|---|
| 1 | `01-tts-vs-live` | Text-to-speech is one direction. Gemini Live is audio-to-audio, both ways at once. |
| 2 | `02-architecture` | Browser, backend, model — one WebSocket, two concurrent tasks. |
| 3 | `03-the-loop` | The whole agent: open, send, receive, play — and the per-turn gotcha. |
| 4 | `04-barge-in` | Two detections race when you interrupt. The local one is why it feels instant. |

`../architecture.png` is the denser, single-walk version used in the top-level README.
These are the same system at lower density and larger type. Both are maintained.

## Every label, and where it comes from

| Claim | Source |
|---|---|
| `:8000`, `/ws` | `README.md` run command · `backend/raw_server.py:53` |
| mic → 16 kHz | `frontend/pcm-processor.js:6` |
| `send_realtime_input`, `audio/pcm;rate=16000` | `backend/raw_server.py:69-70` |
| `session.receive()` wrapped in `while True` | `backend/raw_server.py:102-105` |
| `upstream()` / `downstream()` as two tasks | `backend/raw_server.py:119-121` |
| 24 kHz playback | `frontend/main.js:57` |
| `mic RMS ≥ 0.02` → `stopVoice()` | `frontend/main.js:9,100` |
| server `interrupted` signal | `backend/raw_server.py:88-89` |
| `gemini-3.1-flash-live-preview`, voice `Aoede` | `.env.example` · `backend/raw_server.py:33-34` |
| barge-in must land well under 200 ms | `docs/UX.md:101` |

## Re-render

Edit the SVG, then:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --force-device-scale-factor=2 --window-size=1600,900 \
  --screenshot=png/02-architecture.png "file://$PWD/svg/02-architecture.svg"
```
