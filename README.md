# MERCIL Voice Sales Agent

A configurable, real-time AI sales consultant you can interrupt. It speaks with a prospective
customer, works out what their business actually needs, recommends only what's in the approved
catalogue, and hands a qualified enquiry to the human sales team.

The product is the engine. **Kittichet SPR is a configuration** — one folder of Markdown and JSON.

```
MERCIL Voice Sales Agent
Currently representing: Kittichet SPR
```

Built on the **Gemini Live API** with the raw `google-genai` SDK — no agent framework, so the whole
primitive stays visible.

> **Proof of concept.** All catalogue data is demonstration data. No real prices, stock, or
> Kittichet product information. Enquiries are mock objects, not CRM records.

## Run it

```bash
uv sync
cp .env.example .env          # paste your GOOGLE_API_KEY (Gemini Developer API / AI Studio, not Vertex)

uv run uvicorn backend.raw_server:app --port 8000
```

Open <http://localhost:8000>, **put headphones on** (otherwise it hears itself), tap 🎙 and talk.
Then **talk over it** mid-sentence — barge-in is the most visible thing here.

**End the call when you are done.** The mic streams to Gemini for as long as it is open and
audio is billed by the second whether anyone is speaking or not, so an open tab on an empty room
costs the same as a conversation. The button hangs up, and the session also ends itself after two
minutes of silence or when the tab closes.

The demonstration path is in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## The product / configuration split

Everything company-specific lives in one directory. Nothing about Kittichet is in the Python.

```
company-configs/
├── kittichet/          # the first demonstration configuration
│   ├── persona.md          # who the consultant is, how it qualifies, what it must never do
│   ├── products.json       # 55 product families across 22 categories
│   └── sales-rules.json    # identity, language, segments, safety rules, enquiry prefix
└── default/            # generic, English — the unconfigured product
```

Switch customer with one environment variable:

```bash
COMPANY_PROFILE=default uv run uvicorn backend.raw_server:app --port 8000
```

Same voice engine, different company, different language, different catalogue, rebranded UI — no
code change. That's the whole claim, and it's one command to check.

## What's inside

| | |
|---|---|
| `backend/raw_server.py` | the raw Gemini Live loop + sales-tool dispatch — the reusable engine |
| `backend/config.py` | loads `company-configs/<COMPANY_PROFILE>/` and builds the system instruction |
| `backend/catalog.py` | pure catalogue search + recommendation ranking |
| `backend/tools.py` | `search_products` · `recommend_products` · `capture_requirements` · `create_sales_enquiry` |
| `backend/raw_minimal.py` | the 39-line voice-only extract (from upstream, unmodified) |
| `backend/gotcha_send_client_content.py` | the wrong-way/right-way example (from upstream, unmodified) |
| `frontend/` | 16 kHz mic worklet, 24 kHz playback, client-side barge-in, requirement + recommendation + enquiry panels |
| `tests/test_sales.py` | 55 tests over the config, catalogue, and tool layer |
| `docs/DEMO_SCRIPT.md` | the 90-second presentation path and acceptance checklist |
| `docs/brainstorm.md` | the product thinking this was built from |

## How the grounding works

Two rules do most of the work, and neither is left to the prompt alone:

**Recommendations can't leave the catalogue.** `recommend_products` treats the customer's segment
as a *filter*, not a hint — a hotel is never offered a product only sold into factories. Every
result carries a `why` string built from the catalogue data, so the assistant explains its
reasoning from data instead of inventing one.

**Enquiries can't skip confirmation.** `create_sales_enquiry` returns `not_confirmed` and emits
nothing to the UI unless `confirmed=true`. The prompt asks the assistant to summarise and get a
spoken yes; the tool makes it impossible to submit without one.

**Brands stay at portfolio level.** The catalogue records the brands Kittichet is genuinely an
authorized distributor for — Kimberly-Clark, Ecolab, 3M, Ocean Glass, Twinfish, Fest, Kärcher,
Royal Umbrella and others — against the category they belong to. The assistant may say "for
washroom systems we carry Kimberly-Clark", because that is true. It may not produce a model name,
model number, specification, dilution rate, or certification, and `specifications` is empty on
every record by design: invented detail that looks precise is more dangerous than detail that
looks vague, because nobody questions a number. A test enforces that no product name reads as a
brand SKU.

Prices, availability, specifications, and chemical safety are never answered — the assistant says
so and offers a human specialist.

## The gotcha — why your voice agent goes silent after one sentence

`session.receive()` is a **per-turn** async generator. It ends the moment the model finishes one
reply. Iterate it once and your agent answers exactly one sentence, then never speaks again:

```python
# ❌ one reply, then silence forever
async for response in session.receive():
    ...

# ✅ a conversation
while True:
    async for response in session.receive():
        ...
```

Its sibling is in [`backend/gotcha_send_client_content.py`](backend/gotcha_send_client_content.py):
mic audio goes to `send_realtime_input`, **not** `send_client_content` — get that wrong and the
model simply never hears you.

## Notes

- **Voice** is a Gemini Live *native* voice (`LIVE_VOICE`, default `Aoede`). The Live API has its
  own voice set. The persona carries the character, not the timbre.
- **Barge-in** is client-side: the browser cuts playback the instant the mic hears you (RMS gate in
  `frontend/main.js`), which feels faster than waiting for the server signal. The server forwards
  `interrupted` too. It needs sustained energy rather than one loud sample, and the remainder of a
  cut turn is discarded — otherwise the tail of the reply arrives after the cut and plays as a
  jump to the end of the sentence.
- **Interruption can be switched off** for a loud room. There are two paths to interrupt and the
  toggle closes both: it skips the client RMS gate, and it stops sending microphone audio while
  the assistant speaks, so Gemini's own voice-activity detection has nothing to trigger on. That
  works mid-call, and unlike the API's `NO_INTERRUPTION` it discards the room noise instead of
  ingesting it as the next turn.
- **Tools return instantly.** In a live session function calls are synchronous — the voice pauses
  until the tool returns, so every handler does list filtering and nothing else.
- The model is **audio-only**; `response_modalities: ["TEXT"]` is rejected by
  `gemini-3.1-flash-live-preview`.
- **Transcript language cannot be pinned on the Developer API.** Each profile declares
  `transcription_languages`, but `language_codes` is Vertex/Enterprise only and the Developer API
  rejects it at session open, so it is dropped there with a warning. Transcription is
  auto-detected and short utterances can come back as the wrong language; the model still
  understands the speech, only the displayed transcript is affected.
- **Cost.** Live sessions bill continuously on streamed audio, so the controls that matter are
  hanging up and not leaving the tab open — not the model choice, which is already the Flash tier.
  Context also accumulates server-side for the life of a session, so `context_window_compression`
  caps it with a sliding window set well above any demo-length conversation.

## Attribution and licensing

The real-time voice foundation is derived from **[`cuppibla/live-dj`](https://github.com/cuppibla/live-dj)**,
a demonstration of the Gemini Live API (EP1 of the Multimodal Agents Cookbook) — originally a
late-night radio DJ. The live loop in `raw_server.py`, the `session.receive()` per-turn gotcha,
`raw_minimal.py`, `gotcha_send_client_content.py`, and the browser audio pipeline all come from
there. The sales layer, configuration system, catalogue, tools, and UI panels are new.

The upstream repository does not carry an explicit open-source license, so default copyright
applies. This prototype is private and non-commercial. Before any commercial delivery, either
obtain explicit permission from the author or reimplement the voice foundation from the official
API documentation. Do not present the upstream implementation as proprietary work.
