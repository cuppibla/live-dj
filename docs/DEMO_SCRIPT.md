# Demo script — MERCIL Voice Sales Agent · Kittichet SPR

Target: **90 seconds to 3 minutes.** You play a purchasing manager opening an 80-room hotel in
Khao Yai. Speak Thai. Headphones on.

## Pre-flight

```bash
uv run pytest -q                                      # 18 passing
uv run uvicorn backend.raw_server:app --port 8000
```

Open <http://localhost:8000>. Before you tap anything, check the header reads
**MERCIL Voice Sales Agent** / *Currently representing: Kittichet SPR*, and the
**Demonstration data** badge is visible. Then tap **🎙 start call**.

- [ ] Headphones on (otherwise it hears itself and interrupts itself)
- [ ] Quiet room
- [ ] Browser mic permission already granted
- [ ] Backup video ready in case the network or the Live API misbehaves

## Opening line to the audience

> This is a configurable AI voice sales agent. It can be given an organization's product
> catalogue, customer segments, qualification process, business rules, and brand voice.
> For today we configured it as a sales consultant for Kittichet SPR.

## The path

Say these in order. Keep your own answers short — the assistant mirrors your pacing.

| # | You say (Thai) | Watch for |
|---|---|---|
| 1 | สวัสดีครับ ผมกำลังจะเปิดโรงแรม 80 ห้องที่เขาใหญ่ครับ | Requirements panel fills in: business type · location · scale |
| 2 | มีห้องน้ำสาธารณะ 6 ห้อง อยากได้ภาพลักษณ์ดูพรีเมียม แต่คุมการใช้ทิชชูด้วยครับ | It asks about dispensing, not about what business you run |
| 3 | **INTERRUPT IT MID-SENTENCE:** เดี๋ยวครับ แล้วน้ำยาทำความสะอาดล่ะครับ | Its voice cuts instantly. This is the moment worth the demo. |
| 4 | พื้นเป็นกระเบื้องกับพรมครับ มีห้องอาหารด้วย | Recommendation cards appear — housekeeping, floor care |
| 5 | **Off the expected order:** มีเครื่องทำน้ำแข็งไหมครับ | It adapts, doesn't lose the thread |
| 6 | ผมชื่อคุณสมชาย บริษัท เขาใหญ่ ฮอสพิทาลิตี้ เบอร์ 081-234-5678 ครับ | Contact fields land in the panel |
| 7 | ครับ ส่งให้ทีมขายได้เลยครับ | Only after it reads the summary back — then `KT-POC-001` appears |

**Deliberately test the guard once** (optional, ~10s): when it first asks to submit, say
**ยังก่อนครับ** — confirm the enquiry card does *not* appear. Then confirm.

## Ask it something it must not answer

> น้ำยาตัวนี้ผสมน้ำอัตราส่วนเท่าไหร่ครับ · ราคาเท่าไหร่ครับ

It should decline and offer a specialist, not invent a dilution ratio or a price. That refusal is
a feature — point it out.

## Closing lines

> The real-time voice foundation stays the same. For another organization we replace the company
> knowledge, qualification process, sales actions, and branding.
>
> The AI handles the repetitive first conversation; the human salesperson receives a qualified
> opportunity with the customer's requirements already written down.

To prove the configurability claim on the spot:

```bash
COMPANY_PROFILE=default uv run uvicorn backend.raw_server:app --port 8000
```

Same engine, different company, different language, different catalogue — no code change.

## Typed fallback prompts

If Thai speech recognition misfires, switch to English mid-call — the assistant follows the
customer's language. The same path in English:

1. "I'm opening an 80-room hotel in Khao Yai."
2. "Six public washrooms. I want a premium look but I need to control tissue usage."
3. *(interrupt)* "Wait — what about cleaning chemicals?"
4. "Tile and carpet, and we have a restaurant."
5. "Do you have ice machines?"
6. "I'm Somchai, Khao Yai Hospitality, 081-234-5678."
7. "Yes, please send it to the sales team."

## Acceptance criteria to tick during the run

| # | Criterion | Pass |
|---|---|---|
| 1 | Voice round-trip works | ☐ |
| 2 | Natural Thai in and out | ☐ |
| 3 | Barge-in cuts it instantly | ☐ |
| 4 | At least three qualification questions | ☐ |
| 5 | Next question adapts to the last answer | ☐ |
| 6 | Only catalogue products named | ☐ |
| 7 | Explains *why* each fits | ☐ |
| 8–9 | Summarises customer + requirements before submitting | ☐ |
| 10 | Asks for explicit confirmation | ☐ |
| 11 | `KT-POC-001` card appears | ☐ |
| 12 | Whole run inside 3 minutes | ☐ |

A failure in 2–10 is a **persona fix** in `company-configs/kittichet/persona.md` or a tool-description
fix in `backend/tools.py` — not a change to the live loop in `backend/raw_server.py`.
