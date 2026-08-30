# MERCIL Voice Sales Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the `live-dj` radio-DJ demo into a configurable real-time AI voice **sales consultant**, shipped with a Kittichet SPR demonstration configuration, without touching the Gemini Live primitive that already works.

**Architecture:** The live loop in `backend/raw_server.py` (one `client.aio.live.connect()` session per browser, upstream mic task + downstream `session.receive()` task) is **kept as-is**. Three things swap out around it: (1) the hard-coded Mira persona becomes a `company-configs/<profile>/` directory loaded by a new `backend/config.py` at import time, selected by `COMPANY_PROFILE`; (2) the four music tools in `backend/tools.py` become four sales tools backed by a static JSON catalogue; (3) the browser's music player becomes a requirements / recommendations / enquiry panel driven by the same `type`-tagged JSON messages the server already sends. `dispatch_tool` keeps its exact contract — return instantly, never await — because that is what keeps the voice from stalling mid-sentence.

**Tech Stack:** Python 3.11, FastAPI + uvicorn, `google-genai` raw SDK (Gemini Live API, `gemini-3.1-flash-live-preview`), vanilla JS browser client (AudioWorklet, 16 kHz up / 24 kHz down), pytest for the pure-Python layer, `uv` for deps.

**Spec:** [`docs/brainstorm.md`](../../brainstorm.md) — read §5 (reusable core vs. customer config), §7 (AI behaviour), §10 (tools), §11 (mock data), §12 (UI), §14 (scope), §16 (acceptance criteria).

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- **Product name is `MERCIL Voice Sales Agent`.** Kittichet is a *configuration*, never the product identity. UI shows `Currently representing: Kittichet SPR` (spec §12).
- **Active profile is chosen by env var `COMPANY_PROFILE=kittichet`** (spec §5). Default when unset: `kittichet` (so the demo runs with an untouched `.env`).
- **Default conversation language is Thai.** Tone: professional, helpful, consultative (spec §5).
- **Never invent prices, availability, specifications, discounts, certifications, or chemical safety instructions** (spec §7). `price_status` is always `contact_sales`; `availability_status` is always `confirmation_required`.
- **Every catalogue entry carries `"demo_only": true`** and demo-labelled names (spec §11: "Do not present invented product names, specifications, prices, or stock levels as real Kittichet information").
- **Write actions require explicit customer confirmation** before execution (spec §7, §10).
- **The AI must not expose internal tool names to the customer** (spec §10).
- **Tools return instantly.** No I/O, no `await`, no network inside `dispatch_tool` — the model's voice pauses until it returns (existing `backend/tools.py` docstring).
- **Preserve upstream attribution.** Do not delete the `cuppibla/live-dj` credit or rewrite git history (spec §19). `backend/raw_minimal.py` and `backend/gotcha_send_client_content.py` are teaching artifacts — **do not modify them**.
- **Out of scope, do not build:** CRM integration, auth, real quotations, stock checks, payments, discount negotiation, admin/config portal (spec §14).
- **Commit cadence:** few big commits (user's global rule). Checkpoint per task is fine; squash to ~2 commits before finishing. No Claude attribution trailers.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `company-configs/kittichet/persona.md` | Create | Kittichet consultant persona + qualification guidance, in prose. The only file a new customer *must* rewrite. |
| `company-configs/kittichet/products.json` | Create | 18 demo product families (spec §11 schema). The single source of product truth. |
| `company-configs/kittichet/sales-rules.json` | Create | Company identity, language, segments, safety rules, qualification fields, enquiry-id prefix. |
| `company-configs/default/persona.md` | Create | Generic unbranded consultant — proves the product is not a Kittichet chatbot. |
| `company-configs/default/products.json` | Create | 3 placeholder generic products. |
| `company-configs/default/sales-rules.json` | Create | Generic identity, English default. |
| `backend/config.py` | Create | Loads the active profile off `COMPANY_PROFILE`; exposes `CONFIG` (a `CompanyConfig`) and builds `SYSTEM_INSTRUCTION`. Replaces `backend/persona.py`. |
| `backend/catalog.py` | Create | Pure functions over the loaded product list: `search`, `recommend`. No model, no I/O. |
| `backend/tools.py` | Rewrite | Four sales tool declarations + `dispatch_tool` returning `(ui_events, result)`. |
| `backend/raw_server.py` | Modify | Swap imports (`config`/`tools`), forward a *list* of UI events per tool call, add `GET /api/company`. |
| `backend/persona.py` | Delete | Superseded by `config.py`. |
| `frontend/index.html` | Rewrite | Sales UI: brand header, orb, transcript, requirements panel, recommendation cards, enquiry card, demo-data label. |
| `frontend/main.js` | Rewrite | Same socket/mic/barge-in logic; music player replaced by panel renderers. |
| `frontend/pcm-processor.js` | Untouched | Mic worklet works; don't touch it. |
| `tests/test_sales.py` | Create | pytest over `catalog.py` + `tools.py` + `config.py`. Fast, no network. |
| `pyproject.toml` | Modify | Add `[dependency-groups] dev = ["pytest>=8"]`. |
| `.env.example` | Modify | Add `COMPANY_PROFILE=kittichet`. |
| `README.md` | Modify | Reframe as MERCIL Voice Sales Agent, keep upstream attribution. |
| `docs/DEMO_SCRIPT.md` | Create | The 90-second presentation path + typed fallback prompts (spec §17, §18). |
| `assets/tracks/`, `assets/tracks.json`, `assets/mira_persona.txt` | Keep on disk | Unreferenced after this change. Deleting them is a separate cleanup; leaving them costs nothing and preserves upstream diffability. |

---

### Task 1: Company configuration layer

Loads a customer profile from disk and turns it into one system instruction. This is the "reusable product vs. customer configuration" split from spec §5 — everything Kittichet-specific lives in JSON/Markdown, not Python.

**Files:**
- Create: `company-configs/kittichet/sales-rules.json`
- Create: `company-configs/kittichet/persona.md`
- Create: `company-configs/kittichet/products.json`
- Create: `company-configs/default/sales-rules.json`, `company-configs/default/persona.md`, `company-configs/default/products.json`
- Create: `backend/config.py`
- Delete: `backend/persona.py`
- Modify: `pyproject.toml`, `.env.example`
- Test: `tests/test_sales.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `backend.config.CompanyConfig` — a frozen dataclass with fields `profile: str`, `company_name: str`, `assistant_role: str`, `language: str`, `enquiry_prefix: str`, `persona: str`, `products: list[dict]`, `rules: dict`.
  - `backend.config.CONFIG: CompanyConfig` — module-level singleton, loaded at import.
  - `backend.config.SYSTEM_INSTRUCTION: str` — the full Live system instruction.
  - `backend.config.load_config(profile: str) -> CompanyConfig` — explicit loader (used by tests to load `default`).

`sales-rules.json` schema (exact keys — `config.py` and the tests both depend on them):

```json
{
  "company_name": "Kittichet SPR",
  "assistant_role": "Hygiene and facility sales consultant",
  "language": "Thai",
  "enquiry_prefix": "KT-POC",
  "customer_segments": ["hotel", "restaurant", "hospital", "factory", "office"],
  "qualification_fields": ["contact_name", "company_name", "phone", "email_or_line", "business_type", "location", "scale", "priority", "timeline"],
  "safety_rules": [
    "Never invent prices, availability, specifications, discounts, certifications, or chemical safety instructions.",
    "Recommend only products returned by the catalogue tools.",
    "For chemical safety or technical specification questions, offer a human specialist."
  ],
  "handoff_line": "I can connect you with a Kittichet specialist who will follow up directly."
}
```

`products.json` — a JSON array of 18 objects using the spec §11 schema exactly:

```json
{
  "id": "demo-product-001",
  "name": "Demo Controlled Tissue Dispenser",
  "name_th": "เครื่องจ่ายกระดาษทิชชูแบบควบคุมปริมาณ (ตัวอย่างสาธิต)",
  "brand": "Approved brand",
  "category": "washroom_dispenser",
  "customer_types": ["hotel", "restaurant", "office", "hospital"],
  "use_cases": ["high-traffic washroom", "consumption control"],
  "benefits": ["controlled dispensing", "consistent premium appearance", "lower tissue waste"],
  "specifications": {},
  "price_status": "contact_sales",
  "availability_status": "confirmation_required",
  "demo_only": true
}
```

The 18 entries — ids `demo-product-001` … `demo-product-018`, every one `"demo_only": true`, `"brand": "Approved brand"`, `price_status`/`availability_status` fixed as above, `specifications` `{}`:

| id | name | category | customer_types |
|---|---|---|---|
| 001 | Demo Controlled Tissue Dispenser | `washroom_dispenser` | hotel, restaurant, office, hospital |
| 002 | Demo Jumbo Roll Dispenser | `washroom_dispenser` | factory, office, hospital |
| 003 | Demo Sensor Hand Towel Dispenser | `washroom_dispenser` | hotel, hospital, office |
| 004 | Demo Premium Toilet Tissue Roll | `toilet_tissue` | hotel, restaurant, office |
| 005 | Demo High-Yield Jumbo Toilet Tissue | `toilet_tissue` | factory, office, hospital |
| 006 | Demo Interfold Hand Towel | `paper_towel` | hotel, restaurant, hospital, office |
| 007 | Demo Roll Hand Towel | `paper_towel` | factory, office |
| 008 | Demo Foam Hand Soap | `hand_hygiene` | hotel, restaurant, hospital, office |
| 009 | Demo Alcohol Hand Sanitiser Gel | `hand_hygiene` | hospital, hotel, factory, office |
| 010 | Demo Multi-Surface Cleaner Concentrate | `cleaning_chemical` | hotel, restaurant, office, factory |
| 011 | Demo Heavy-Duty Kitchen Degreaser | `degreaser` | restaurant, hotel, factory |
| 012 | Demo Surface Disinfectant Category | `disinfectant` | hospital, hotel, restaurant |
| 013 | Demo Floor Cleaning Pad Set | `floor_care` | hotel, factory, office, hospital |
| 014 | Demo Single-Disc Floor Machine | `floor_equipment` | hotel, factory, office |
| 015 | Demo Housekeeping Trolley | `floor_equipment` | hotel, hospital |
| 016 | Demo Restaurant Glassware Range | `glassware` | hotel, restaurant |
| 017 | Demo Compostable Food Packaging | `food_packaging` | restaurant, hotel |
| 018 | Demo Modular Ice Machine | `ice_machine` | hotel, restaurant |

Write a plausible `name_th`, two-to-four `use_cases`, and two-to-three `benefits` for each — grounded in the category, never claiming a spec, a rate, or a certification. Example for 018: `use_cases: ["hotel beverage service", "restaurant bar", "banquet operations"]`, `benefits: ["continuous ice supply for food service", "sized to daily consumption during consultation"]`.

`default/products.json` is 3 entries — `demo-generic-001/002/003`, categories `consumable`, `equipment`, `service`, `customer_types: ["general"]`.

`persona.md` (Kittichet) — prose, no JSON. It carries §7's ten behaviour principles in the assistant's own voice. Write it to say, at minimum: who the assistant is; that it speaks Thai by default and switches if the customer does; that it asks **one** question at a time and adapts to previous answers; that it must understand the business before recommending; that recommendations come from the catalogue tools and it explains *why* each fits; that it says so plainly when it doesn't know and offers a specialist; that it summarises and asks for explicit confirmation before creating an enquiry; that spoken replies stay short and natural for voice.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sales.py
import json
from pathlib import Path

import pytest

from backend.config import CONFIG, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_kittichet_profile_loads():
    cfg = load_config("kittichet")
    assert cfg.company_name == "Kittichet SPR"
    assert cfg.language == "Thai"
    assert cfg.enquiry_prefix == "KT-POC"
    assert len(cfg.products) >= 15


def test_default_profile_is_not_kittichet():
    cfg = load_config("default")
    assert "Kittichet" not in cfg.company_name
    assert cfg.products


@pytest.mark.parametrize("profile", ["kittichet", "default"])
def test_every_product_is_demo_labelled(profile):
    for p in load_config(profile).products:
        assert p["demo_only"] is True
        assert p["price_status"] == "contact_sales"
        assert p["availability_status"] == "confirmation_required"
        assert set(p) >= {"id", "name", "category", "customer_types", "use_cases", "benefits"}


def test_product_ids_are_unique():
    ids = [p["id"] for p in load_config("kittichet").products]
    assert len(ids) == len(set(ids))


def test_system_instruction_carries_company_and_safety_rules():
    from backend.config import SYSTEM_INSTRUCTION

    assert CONFIG.company_name in SYSTEM_INSTRUCTION
    assert "Thai" in SYSTEM_INSTRUCTION
    for rule in CONFIG.rules["safety_rules"]:
        assert rule in SYSTEM_INSTRUCTION
    assert "confirmation" in SYSTEM_INSTRUCTION.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_sales.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.config'`

- [ ] **Step 3: Add the pytest dev dependency**

Append to `pyproject.toml` (after the `[tool.uv]` block):

```toml
[dependency-groups]
dev = ["pytest>=8"]
```

Run: `uv sync --group dev`

- [ ] **Step 4: Write the config files**

Create the six files under `company-configs/` per the schemas and the 18-row table above.

- [ ] **Step 5: Write the minimal implementation**

```python
# backend/config.py
"""The customer layer. Everything company-specific lives in company-configs/<profile>/.

The Python here is the reusable product; the JSON and Markdown are the configuration.
Swap COMPANY_PROFILE and the same voice engine sells for a different organization.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIGS = Path(__file__).resolve().parents[1] / "company-configs"


@dataclass(frozen=True)
class CompanyConfig:
    profile: str
    company_name: str
    assistant_role: str
    language: str
    enquiry_prefix: str
    persona: str
    products: list
    rules: dict


def load_config(profile: str) -> CompanyConfig:
    base = CONFIGS / profile
    if not base.is_dir():
        raise FileNotFoundError(f"no company profile at {base}")
    rules = json.loads((base / "sales-rules.json").read_text(encoding="utf-8"))
    return CompanyConfig(
        profile=profile,
        company_name=rules["company_name"],
        assistant_role=rules["assistant_role"],
        language=rules["language"],
        enquiry_prefix=rules["enquiry_prefix"],
        persona=(base / "persona.md").read_text(encoding="utf-8").strip(),
        products=json.loads((base / "products.json").read_text(encoding="utf-8")),
        rules=rules,
    )


def build_instruction(cfg: CompanyConfig) -> str:
    categories = sorted({p["category"] for p in cfg.products})
    return f"""You are a professional AI sales consultant representing {cfg.company_name}.
Your role: {cfg.assistant_role}.

{cfg.persona}

LANGUAGE: Speak {cfg.language} by default. If the customer speaks another language, follow them.
Keep spoken replies short and natural — this is a live voice call, not a written document.

OBJECTIVE: Understand the customer's business and operational needs, recommend relevant
solutions using approved company information, and prepare a qualified enquiry for a human
salesperson. Ask ONE relevant question at a time and adapt it to the customer's previous answer.

CATALOGUE: Use search_products and recommend_products for anything factual about products.
Available categories: {", ".join(categories)}.
Explain WHY a recommendation fits what the customer just told you.

QUALIFICATION: Collect, conversationally and only when relevant:
{", ".join(cfg.rules["qualification_fields"])}.
Call capture_requirements whenever you learn something new about the customer so the screen
stays in step with the conversation.

RULES:
{chr(10).join("- " + r for r in cfg.rules["safety_rules"])}
- All catalogue data is DEMONSTRATION data. Prices and availability always require a human.
- Before creating an enquiry you MUST summarize the customer details and requirements aloud
  and get explicit spoken confirmation. Only then call create_sales_enquiry with confirmed=true.
- Never mention tool names, JSON, or internal system details to the customer.
- When you do not know something, say so plainly and offer a specialist:
  "{cfg.rules["handoff_line"]}"
"""


CONFIG = load_config(os.getenv("COMPANY_PROFILE", "kittichet"))
SYSTEM_INSTRUCTION = build_instruction(CONFIG)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sales.py -v`
Expected: PASS (5 tests / 6 with the parametrize expansion)

- [ ] **Step 7: Retire the DJ persona module and update `.env.example`**

```bash
git rm backend/persona.py
```

Add to `.env.example`, under the API-key block:

```text
# which customer configuration to load from company-configs/
COMPANY_PROFILE=kittichet
```

Note: `raw_server.py` still imports `backend.persona` at this point and will not boot until Task 3. That is expected — Task 2 has no server dependency.

- [ ] **Step 8: Checkpoint commit**

```bash
git add company-configs backend/config.py tests/test_sales.py pyproject.toml uv.lock .env.example
git add -u backend/persona.py
git commit -m "feat: company configuration layer with Kittichet demo profile"
```

---

### Task 2: Sales tools

Replaces music control with the four tools from spec §10. Same `dispatch_tool` shape as the music version — return instantly, hand the browser a UI command — because a blocking tool audibly stalls the model mid-sentence.

**Files:**
- Create: `backend/catalog.py`
- Rewrite: `backend/tools.py`
- Test: `tests/test_sales.py` (append)

**Interfaces:**
- Consumes: `backend.config.CONFIG` (`.products`, `.enquiry_prefix`, `.company_name`) from Task 1.
- Produces:
  - `backend.catalog.search(products: list, query: str = "", category: str = "", customer_type: str = "") -> list[dict]`
  - `backend.catalog.recommend(products: list, business_type: str, needs: list[str]) -> list[dict]` — each result is a product dict plus a `"why": str` key.
  - `backend.tools.TOOL_DECLARATIONS: list[dict]` — four declarations, consumed by `raw_server.LIVE_CONFIG`.
  - `backend.tools.dispatch_tool(name: str, args: dict) -> tuple[list[dict], dict]` — **note the changed return type**: a *list* of UI events (each a dict with a `"type"` key), and the function result for the model. Task 3 depends on this exact signature.
  - `backend.tools.reset_state() -> None` — clears the in-memory requirements + enquiry counter (used by tests and by a fresh websocket connection).

The four tools:

| Tool | Args | UI events emitted | Returns to model |
|---|---|---|---|
| `search_products` | `query`, `category?`, `customer_type?` | `{"type":"products", "items":[...]}` | `{"count": n, "products": [...]}` |
| `recommend_products` | `business_type`, `needs` (array of strings) | `{"type":"products", "items":[...]}` | `{"count": n, "recommendations": [...]}` |
| `capture_requirements` | `business_type?`, `location?`, `scale?`, `priority?`, `contact_name?`, `company_name?`, `phone?`, `email_or_line?`, `timeline?`, `notes?` | `{"type":"requirements", "requirements":{...}}` | `{"result":"ok", "captured": {...}}` |
| `create_sales_enquiry` | `summary`, `confirmed` (boolean) | `{"type":"enquiry", ...}` *(only when confirmed)* | enquiry dict, or a refusal |

`create_sales_enquiry` is the confirmation guard made mechanical: when `confirmed` is not `true` it emits **no** UI event and returns `{"result": "not_confirmed", "instruction": "..."}` telling the model to summarize and ask first. The prompt asks for confirmation; this makes it impossible to skip.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sales.py`:

```python
from backend import catalog, tools
from backend.config import CONFIG


def test_search_matches_category():
    hits = catalog.search(CONFIG.products, category="ice_machine")
    assert hits and all(h["category"] == "ice_machine" for h in hits)


def test_search_matches_free_text_in_name_or_use_case():
    assert catalog.search(CONFIG.products, query="dispenser")
    assert catalog.search(CONFIG.products, query="ไม่มีสินค้านี้แน่นอน") == []


def test_search_filters_by_customer_type():
    hits = catalog.search(CONFIG.products, customer_type="hotel")
    assert hits and all("hotel" in h["customer_types"] for h in hits)


def test_recommend_returns_reasons_and_matches_business_type():
    recs = catalog.recommend(CONFIG.products, "hotel", ["washroom", "housekeeping"])
    assert recs
    assert all(r["why"] for r in recs)
    assert all("hotel" in r["customer_types"] for r in recs)


def test_recommend_unknown_business_type_still_returns_something():
    assert catalog.recommend(CONFIG.products, "spaceport", ["cleaning"])


def test_dispatch_search_emits_product_event():
    events, result = tools.dispatch_tool("search_products", {"query": "glassware"})
    assert result["count"] >= 1
    assert events[0]["type"] == "products"
    assert events[0]["items"]


def test_capture_requirements_accumulates_across_calls():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"business_type": "hotel"})
    events, result = tools.dispatch_tool("capture_requirements", {"scale": "80 rooms"})
    reqs = events[0]["requirements"]
    assert reqs["business_type"] == "hotel"
    assert reqs["scale"] == "80 rooms"
    assert result["result"] == "ok"


def test_capture_requirements_ignores_empty_values():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"business_type": "hotel"})
    events, _ = tools.dispatch_tool("capture_requirements", {"business_type": "", "location": None})
    assert events[0]["requirements"]["business_type"] == "hotel"
    assert "location" not in events[0]["requirements"]


def test_enquiry_refuses_without_confirmation():
    tools.reset_state()
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "80-room hotel", "confirmed": False})
    assert events == []
    assert result["result"] == "not_confirmed"


def test_enquiry_creates_numbered_reference_when_confirmed():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"business_type": "hotel", "contact_name": "Khun A"})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "80-room hotel in Khao Yai", "confirmed": True})
    assert result["enquiry_id"] == f"{CONFIG.enquiry_prefix}-001"
    assert events[0]["type"] == "enquiry"
    assert events[0]["enquiry_id"] == f"{CONFIG.enquiry_prefix}-001"
    assert events[0]["requirements"]["contact_name"] == "Khun A"


def test_unknown_tool_is_not_fatal():
    events, result = tools.dispatch_tool("play_playlist", {"mood": "dream pop"})
    assert events == []
    assert "unknown" in result["result"]


def test_declarations_cover_every_dispatchable_tool():
    names = {d["name"] for d in tools.TOOL_DECLARATIONS}
    assert names == {"search_products", "recommend_products",
                     "capture_requirements", "create_sales_enquiry"}
    for d in tools.TOOL_DECLARATIONS:
        assert d["parameters"]["type"] == "object"
        assert d["description"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sales.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.catalog'`

- [ ] **Step 3: Write `backend/catalog.py`**

```python
"""Pure catalogue lookups. No model, no I/O, no network — these run inside a live
function call, and every millisecond here is a gap in the assistant's voice.
"""


def _haystack(p: dict) -> str:
    parts = [p.get("name", ""), p.get("name_th", ""), p.get("category", "")]
    parts += p.get("use_cases", []) + p.get("benefits", []) + p.get("customer_types", [])
    return " ".join(parts).lower()


def search(products: list, query: str = "", category: str = "", customer_type: str = "") -> list:
    """Filter the catalogue. Empty filters match everything; all filters are AND-ed."""
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()
    ctype = (customer_type or "").strip().lower()
    out = []
    for p in products:
        if cat and p.get("category", "").lower() != cat:
            continue
        if ctype and ctype not in [c.lower() for c in p.get("customer_types", [])]:
            continue
        if q and not any(token in _haystack(p) for token in q.split()):
            continue
        out.append(p)
    return out


def recommend(products: list, business_type: str, needs: list) -> list:
    """Rank by how well a product serves this business type and these stated needs.

    Returns product dicts with an added "why" — the assistant is required to explain
    its reasoning, so the reason ships with the data instead of being invented.
    """
    bt = (business_type or "").strip().lower()
    needs = [n.strip().lower() for n in (needs or []) if n and n.strip()]
    scored = []
    for p in products:
        types = [c.lower() for c in p.get("customer_types", [])]
        score = 2 if bt and bt in types else 0
        hay = _haystack(p)
        matched = [n for n in needs if any(tok in hay for tok in n.split())]
        score += len(matched)
        if score == 0:
            continue
        reasons = []
        if bt and bt in types:
            reasons.append(f"suited to {business_type} operations")
        if matched:
            reasons.append("matches the stated need for " + ", ".join(matched))
        if p.get("benefits"):
            reasons.append("; ".join(p["benefits"][:2]))
        scored.append((score, {**p, "why": " — ".join(reasons)}))
    scored.sort(key=lambda s: -s[0])
    hits = [p for _, p in scored[:8]]
    if hits:
        return hits
    # Nothing matched: fall back to the broadest entries rather than returning
    # nothing, so the assistant always has grounded data instead of improvising.
    return [{**p, "why": "general-purpose option — needs confirmation with a specialist"}
            for p in products[:3]]
```

- [ ] **Step 4: Write `backend/tools.py`**

```python
"""Sales tools for the voice consultant.

The lesson from the DJ build still holds: in a live session, function calls are
SYNCHRONOUS — the model's voice pauses until the tool returns. Every handler here does
the minimum (filter a list, update a dict) and returns INSTANTLY.

Each returns (ui_events, result): the events go to the browser panels, the result goes
back to the model.
"""
from backend import catalog
from backend.config import CONFIG

# Fields worth putting on screen. Anything else the model volunteers lands in notes.
_REQUIREMENT_FIELDS = [
    "contact_name", "company_name", "phone", "email_or_line",
    "business_type", "location", "scale", "priority", "timeline", "notes",
]

_requirements: dict = {}
_enquiry_count = 0


def reset_state() -> None:
    """Fresh conversation — a new browser session starts from an empty sheet."""
    global _requirements, _enquiry_count
    _requirements = {}
    _enquiry_count = 0


def _slim(p: dict) -> dict:
    """What the model and the UI actually need — never the whole record."""
    out = {
        "id": p["id"], "name": p["name"], "name_th": p.get("name_th", ""),
        "category": p["category"], "benefits": p.get("benefits", []),
        "price_status": p["price_status"], "availability_status": p["availability_status"],
        "demo_only": p.get("demo_only", True),
    }
    if p.get("why"):
        out["why"] = p["why"]
    return out


TOOL_DECLARATIONS = [
    {
        "name": "search_products",
        "description": (
            "Search the approved product catalogue. Use this for ANY factual product question "
            "— never answer from memory. Returns demonstration catalogue entries only."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what the customer needs, in their own words"},
                "category": {"type": "string", "description": "optional exact category filter"},
                "customer_type": {"type": "string", "description": "optional segment, e.g. hotel, restaurant, hospital, factory, office"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recommend_products",
        "description": (
            "Recommend suitable product categories for a customer once you understand their "
            "business and needs. Each result includes a reason you should paraphrase aloud."),
        "parameters": {
            "type": "object",
            "properties": {
                "business_type": {"type": "string", "description": "hotel, restaurant, hospital, factory, office, ..."},
                "needs": {"type": "array", "items": {"type": "string"},
                          "description": "the needs the customer has stated so far"},
            },
            "required": ["business_type", "needs"],
        },
    },
    {
        "name": "capture_requirements",
        "description": (
            "Record what you have learned about the customer. Call this as soon as you learn "
            "anything new — it keeps the on-screen requirement summary in step with the talk. "
            "Send only the fields you actually learned."),
        "parameters": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in _REQUIREMENT_FIELDS},
        },
    },
    {
        "name": "create_sales_enquiry",
        "description": (
            "Submit the qualified enquiry to the human sales team. You MUST first summarize the "
            "customer details and requirements aloud and receive explicit spoken confirmation; "
            "only then call this with confirmed=true."),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "the requirement summary you just read to the customer"},
                "confirmed": {"type": "boolean", "description": "true only if the customer explicitly said yes"},
            },
            "required": ["summary", "confirmed"],
        },
    },
]


def dispatch_tool(name: str, args: dict):
    """Return (ui_events, function_result). Instant — never awaits anything."""
    global _enquiry_count

    if name == "search_products":
        hits = [_slim(p) for p in catalog.search(
            CONFIG.products,
            query=args.get("query", ""),
            category=args.get("category", ""),
            customer_type=args.get("customer_type", ""),
        )][:8]
        events = [{"type": "products", "items": hits}] if hits else []
        return events, {"count": len(hits), "products": hits,
                        "note": "demonstration catalogue data; price and availability require a human"}

    if name == "recommend_products":
        hits = [_slim(p) for p in catalog.recommend(
            CONFIG.products, args.get("business_type", ""), args.get("needs") or [])]
        return [{"type": "products", "items": hits}], {
            "count": len(hits), "recommendations": hits,
            "note": "explain why each fits what the customer told you"}

    if name == "capture_requirements":
        for field in _REQUIREMENT_FIELDS:
            value = args.get(field)
            if isinstance(value, str) and value.strip():
                _requirements[field] = value.strip()
        return ([{"type": "requirements", "requirements": dict(_requirements)}],
                {"result": "ok", "captured": dict(_requirements)})

    if name == "create_sales_enquiry":
        if not args.get("confirmed"):
            return [], {"result": "not_confirmed",
                        "instruction": "Summarize the customer details and requirements aloud, "
                                       "then ask the customer to confirm before calling this again."}
        _enquiry_count += 1
        enquiry = {
            "type": "enquiry",
            "enquiry_id": f"{CONFIG.enquiry_prefix}-{_enquiry_count:03d}",
            "company": CONFIG.company_name,
            "summary": args.get("summary", ""),
            "requirements": dict(_requirements),
            "status": "prepared_for_sales_team",
            "demo_only": True,
        }
        return [enquiry], {k: v for k, v in enquiry.items() if k != "type"}

    return [], {"result": f"unknown tool: {name}"}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sales.py -v`
Expected: PASS — all tests, including the two Task 1 groups.

- [ ] **Step 6: Checkpoint commit**

```bash
git add backend/catalog.py backend/tools.py tests/test_sales.py
git commit -m "feat: sales catalogue and tool dispatch"
```

---

### Task 3: Wire the live server to the sales layer

The smallest diff in the plan, and the one that must not break the working loop. Only the imports, the tool-result fan-out, and one new HTTP route change. **The `downstream()` / `session.receive()` loop, the upstream mic task, and the barge-in forwarding are not to be touched.**

**Files:**
- Modify: `backend/raw_server.py` (imports at :23-24, `LIVE_CONFIG` at :31-38, the `if tc:` block at :91-99, websocket entry ~:56, routes at end)
- Test: manual — the server must boot and serve.

**Interfaces:**
- Consumes: `backend.config.SYSTEM_INSTRUCTION`, `backend.config.CONFIG`, `backend.tools.TOOL_DECLARATIONS`, `backend.tools.dispatch_tool`, `backend.tools.reset_state` from Tasks 1-2.
- Produces: the browser message contract Task 4 renders —
  - `{"type":"transcript","role":"user"|"agent","text":str}`
  - `{"type":"products","items":[{id,name,name_th,category,benefits,price_status,availability_status,demo_only,why?}]}`
  - `{"type":"requirements","requirements":{field:value}}`
  - `{"type":"enquiry","enquiry_id","company","summary","requirements","status","demo_only"}`
  - `{"type":"interrupted"}` · `{"type":"error","message":str}`
  - binary frames = 24 kHz PCM voice (unchanged)
  - `GET /api/company` → `{"product_name","company_name","assistant_role","language","profile"}`

- [ ] **Step 1: Swap the imports and the config block**

Replace lines 23-24:

```python
from backend.persona import MIRA_INSTRUCTION
from backend.tools import TOOL_DECLARATIONS, dispatch_tool
```

with:

```python
from backend.config import CONFIG, SYSTEM_INSTRUCTION
from backend.tools import TOOL_DECLARATIONS, dispatch_tool, reset_state
```

In `LIVE_CONFIG`, change `"system_instruction": MIRA_INSTRUCTION,` to `"system_instruction": SYSTEM_INSTRUCTION,`. Change the logger name and FastAPI title from `live-dj` to `voice-sales-agent`.

- [ ] **Step 2: Reset per-conversation state on connect**

Immediately after `await websocket.accept()`:

```python
    reset_state()   # a new browser session is a new customer
    log.info("ws connected; profile=%s (%s)", CONFIG.profile, CONFIG.company_name)
```

- [ ] **Step 3: Fan out the tool UI events**

Replace the `if tc:` block (currently the `cmd, result = dispatch_tool(...)` / `{"type": "play", **cmd}` shape) with:

```python
                if tc:
                    results = []
                    for fc in tc.function_calls:
                        events, result = dispatch_tool(fc.name, dict(getattr(fc, "args", None) or {}))
                        for event in events:
                            await websocket.send_text(json.dumps(event, ensure_ascii=False))
                        results.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
                    await session.send_tool_response(function_responses=results)
```

`ensure_ascii=False` matters — the catalogue and the transcript are Thai.

- [ ] **Step 4: Rename the transcript role and make transcripts UTF-8 safe**

In `handle()`, change the output-transcription role from `"mira"` to `"agent"`, and add `ensure_ascii=False` to every `json.dumps` for transcripts:

```python
                    if it and getattr(it, "text", None):
                        await websocket.send_text(json.dumps(
                            {"type": "transcript", "role": "user", "text": it.text}, ensure_ascii=False))
                    if ot and getattr(ot, "text", None):
                        await websocket.send_text(json.dumps(
                            {"type": "transcript", "role": "agent", "text": ot.text}, ensure_ascii=False))
```

- [ ] **Step 5: Add the company route**

Before the `StaticFiles` mounts at the bottom of the file (order matters — the `/` mount swallows later routes):

```python
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
```

- [ ] **Step 6: Verify the server boots and the route answers**

Run:

```bash
uv run uvicorn backend.raw_server:app --port 8000 &
sleep 4
curl -s http://localhost:8000/api/company
```

Expected: `{"product_name":"MERCIL Voice Sales Agent","company_name":"Kittichet SPR",...}` and no traceback in the log. Then stop the server.

- [ ] **Step 7: Verify the profile switch works**

Run: `COMPANY_PROFILE=default uv run python -c "from backend.config import CONFIG; print(CONFIG.company_name, len(CONFIG.products))"`
Expected: the generic company name and `3`. This is the reusability claim in spec §17 — prove it before presenting it.

- [ ] **Step 8: Checkpoint commit**

```bash
git add backend/raw_server.py
git commit -m "feat: wire live server to the configurable sales layer"
```

---

### Task 4: Sales UI

Same socket, same mic, same barge-in. The music player and ducking come out; three panels go in. Keep the visual restraint of the original — the demo's credibility comes from the voice, not from chrome.

**Files:**
- Rewrite: `frontend/index.html`
- Rewrite: `frontend/main.js`
- Untouched: `frontend/pcm-processor.js`

**Interfaces:**
- Consumes: the message contract from Task 3, and `GET /api/company`.
- Produces: nothing downstream.

**What must be on screen** (spec §12):

1. Header: `MERCIL Voice Sales Agent` with `Currently representing: <company_name>` beneath it, both filled from `/api/company` — never hard-coded.
2. A persistent `DEMONSTRATION DATA` badge.
3. Orb with `idle` / `listening` / `thinking` / `speaking` states (keep the existing CSS animations).
4. Live transcript, `you` / `agent` distinguished by colour.
5. **Requirements panel** — a definition list of captured fields, empty-state `— not yet captured —`, field keys humanised (`business_type` → `Business type`).
6. **Recommendation cards** — name, Thai name, category, up to two benefits, the `why` line when present, and `Price: contact sales · Availability: to confirm`.
7. **Enquiry card** — hidden until an `enquiry` message arrives, then shows the enquiry id large, the summary, and `Prepared for the sales team`.
8. Mic button and a headphones hint.

**Carry over unchanged from the current `main.js`:** `playVoice`, `stopVoice`, `startMic`, `connect`, the `BARGE_RMS = 0.02` client-side barge-in, and the 24 kHz scheduling. **Delete:** `loadTracks`, `startQueue`, `setNow`, `handlePlay`, `duck`, `music`, `tracks`, `queue`, `qi`, `duckTimer`, and the `<audio id="music">` element. Remove the `duck()` call inside `playVoice`.

The new message routing in `ws.onmessage`:

```javascript
    const m = JSON.parse(evt.data);
    if (m.type === "transcript") { if (m.role === "user") setOrb("thinking"); addLine(m.role, m.text); }
    else if (m.type === "products") renderProducts(m.items);
    else if (m.type === "requirements") renderRequirements(m.requirements);
    else if (m.type === "enquiry") renderEnquiry(m);
    else if (m.type === "interrupted") stopVoice();
    else if (m.type === "error") { setStatus("error: " + m.message); console.error(m.message); }
```

The three renderers:

```javascript
const FIELD_LABELS = {
  contact_name: "Contact", company_name: "Company", phone: "Phone",
  email_or_line: "Email / LINE", business_type: "Business type", location: "Location",
  scale: "Scale", priority: "Priority", timeline: "Timeline", notes: "Notes",
};

function renderRequirements(reqs) {
  const entries = Object.entries(reqs || {});
  if (!entries.length) return;
  reqEl.innerHTML = entries.map(([k, v]) =>
    `<div class="req"><span class="k">${FIELD_LABELS[k] || k}</span><span class="v"></span></div>`
  ).join("");
  // set text via textContent so customer-typed values can never inject markup
  reqEl.querySelectorAll(".v").forEach((el, i) => { el.textContent = entries[i][1]; });
}

function renderProducts(items) {
  prodEl.innerHTML = "";
  (items || []).forEach((p) => {
    const card = document.createElement("div");
    card.className = "card";
    const bits = [
      ["name", p.name], ["th", p.name_th || ""], ["cat", p.category.replace(/_/g, " ")],
      ["why", p.why || (p.benefits || []).slice(0, 2).join(" · ")],
    ];
    bits.forEach(([cls, text]) => {
      if (!text) return;
      const d = document.createElement("div");
      d.className = cls; d.textContent = text; card.appendChild(d);
    });
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = "Price: contact sales · Availability: to confirm · demo data";
    card.appendChild(meta);
    prodEl.appendChild(card);
  });
}

function renderEnquiry(m) {
  enqEl.hidden = false;
  enqEl.querySelector(".eid").textContent = m.enquiry_id;
  enqEl.querySelector(".esum").textContent = m.summary || "";
  setStatus("enquiry prepared for the sales team");
}
```

- [ ] **Step 1: Rewrite `frontend/index.html`**

Keep the existing dark palette, orb keyframes, and layout skeleton. Restructure the body to a two-column stage — voice on the left (orb, status, transcript, mic button), panels on the right (requirements, recommendations, enquiry) — collapsing to one column under `@media (max-width: 860px)`. Set `<title>MERCIL Voice Sales Agent</title>`, `<html lang="th">`. Header markup:

```html
  <header class="chrome">
    <div>
      <div class="brand">MERCIL Voice Sales Agent</div>
      <div class="rep">Currently representing: <span id="company">…</span></div>
    </div>
    <span class="badge">Demonstration data</span>
  </header>
```

Panel skeleton the renderers above depend on — the ids and class names must match exactly:

```html
    <section class="panel">
      <h2>Customer requirements</h2>
      <div id="requirements"><div class="empty">— not yet captured —</div></div>
    </section>
    <section class="panel">
      <h2>Recommended for this customer</h2>
      <div id="products"><div class="empty">— recommendations appear as you talk —</div></div>
    </section>
    <section id="enquiry" class="panel enquiry" hidden>
      <h2>Enquiry prepared</h2>
      <div class="eid"></div>
      <div class="esum"></div>
      <div class="meta">Prepared for the sales team · demonstration only</div>
    </section>
```

- [ ] **Step 2: Rewrite `frontend/main.js`**

Keep every audio function listed above verbatim. Add the element handles (`reqEl`, `prodEl`, `enqEl`, `companyEl`), the three renderers, the new `onmessage` routing, and change `addLine` so the role prefix reads `you` / `assistant` with `agent` styled in the accent colour. In `go()`, replace `await loadTracks()` with:

```javascript
  try {
    const c = await (await fetch("/api/company")).json();
    companyEl.textContent = c.company_name;
    document.title = `${c.product_name} · ${c.company_name}`;
  } catch { companyEl.textContent = "—"; }
```

Move that fetch to page load rather than mic-start so the branding is correct before anyone taps.

- [ ] **Step 3: Verify in the browser**

Run: `uv run uvicorn backend.raw_server:app --port 8000`, open <http://localhost:8000>.
Expected without touching the mic: header reads `MERCIL Voice Sales Agent` / `Currently representing: Kittichet SPR`, the demo badge is visible, both panels show their empty states, the enquiry card is hidden, and the console is clean.

- [ ] **Step 4: Checkpoint commit**

```bash
git add frontend/index.html frontend/main.js
git commit -m "feat: sales UI with requirements, recommendations, and enquiry panels"
```

---

### Task 5: Demo rehearsal, docs, and squash

The acceptance criteria in spec §16 are conversational, so this task is a scripted live run, not an assertion. Budget the full remaining time here — this is what gets presented.

**Files:**
- Create: `docs/DEMO_SCRIPT.md`
- Modify: `README.md`

- [ ] **Step 1: Run the full test suite and the server**

Run: `uv run pytest -q` → all pass. Then start the server, headphones on.

- [ ] **Step 2: Walk the acceptance criteria live**

Play the purchasing manager from spec §6 (80-room hotel in Khao Yai). Speak Thai. Tick each:

| # | Criterion (spec §16) | Pass = |
|---|---|---|
| 1 | Voice round-trip | the assistant answers in ~1s |
| 2 | Natural Thai | Thai in, Thai out, no English drift |
| 3 | Barge-in | talk over it mid-sentence → it stops instantly |
| 4 | ≥3 qualification questions | count them |
| 5 | Adaptive | say "restaurant" instead of "hotel" once and the next question changes |
| 6 | Grounded recommendations | every product named appears in `products.json` |
| 7 | Explains why | it paraphrases the `why` line |
| 8-9 | Summarises before submitting | it reads the requirement summary back |
| 10 | Explicit confirmation | it asks; say no once and confirm it does **not** create the enquiry |
| 11 | Structured result in UI | `KT-POC-001` card appears |
| 12 | 90 s – 3 min | time it |

Any criterion that fails is a persona fix in `company-configs/kittichet/persona.md` or a tool-description fix in `backend/tools.py` — not a change to the live loop.

- [ ] **Step 3: Write `docs/DEMO_SCRIPT.md`**

The 90-second path with the exact Thai lines to say, the planned interruption point (spec §8: interrupt while it's mid-recommendation), the one off-script question, and typed fallback prompts to paste if speech recognition misfires (spec §18). Include the criteria table from Step 2 as a pre-flight checklist.

- [ ] **Step 4: Update `README.md`**

Reframe the top as MERCIL Voice Sales Agent — what it is, the config-vs-product split, how to switch `COMPANY_PROFILE`, how to run, what's mock. **Keep the upstream credit**: state plainly that the real-time voice foundation is derived from `cuppibla/live-dj` and that the `session.receive()` per-turn gotcha and `raw_minimal.py` come from there (spec §19). Keep the "Run it" and gotcha sections.

- [ ] **Step 5: Record the backup video** (spec §15) — one clean successful run, in case the network or the Live API misbehaves during the presentation.

- [ ] **Step 6: Squash to two commits and verify nothing was lost**

```bash
git branch backup/pre-squash-sales-agent-2026-08-30 HEAD
git log --oneline
# squash by materializing trees (see the user's commit rules), targeting:
#   1. "feat: configurable voice sales agent (MERCIL) with Kittichet demo profile"
#   2. "docs: demo script and README for the sales-agent POC"
git diff backup/pre-squash-sales-agent-2026-08-30 HEAD   # must be empty
git log --format='%h | %an <%ae> | %cn <%ce>' <base>..HEAD
git log <base>..HEAD --format='%B' | grep -i 'co-authored\|claude'   # expect no hits
```

Do not force-push. Do not push at all without asking.

---

## Self-Review

**Spec coverage.** §5 reusable/configurable split → Task 1 (`company-configs/` + `config.py`), proved by the `default` profile in Task 3 Step 7. §6 Kittichet identity and hotel scenario → Task 1 configs, Task 5 rehearsal. §7 behaviour principles and the draft system prompt → `persona.md` + `build_instruction`. §10 minimum tools → Task 2 (spec named three; `capture_requirements` is added because §12 requires a live requirements panel and nothing else feeds it). §11 mock data, 15-20 products with the given schema and demo labels → Task 1, 18 entries, enforced by `test_every_product_is_demo_labelled`. §12 UI elements → Task 4. §14 must-haves → all tasks; nice-to-haves: config switch ✅, recommendation cards ✅, human handoff = the `handoff_line` in the prompt (no separate button — a spoken offer demos better than a button nobody clicks); saved transcript and English conversation are **not** built, and are the first things to cut further if time runs short. §16 acceptance → Task 5 Step 2. §19 attribution → global constraints + Task 5 Step 4.

**Deliberate deviations, flagged rather than hidden:**
- `request_human_consultant` as a *tool* is deferred (spec §10 lists it under "preferred set after the POC"); handoff is prompt-level for now.
- The music assets stay on disk unreferenced — deleting them is cleanup noise in the demo diff.
- Full TDD applies to `config.py`/`catalog.py`/`tools.py` only. The live loop and the UI get scripted manual verification, because the deliverable is an audio conversation and there is no test framework in this repo to mock a Live session against. This is a real gap: a regression in `raw_server.py` will only be caught by running the demo.

**Placeholder scan.** No TBDs. The one instruction that is generative rather than literal is "write a plausible `name_th`, use_cases and benefits for each of the 18 products" — the schema, the fixed fields, the exact id/name/category/customer_types table, and a worked example are all given, so the shape is fully determined.

**Type consistency.** `dispatch_tool` returns `(list, dict)` in Task 2 and is consumed as `events, result` in Task 3 — matches, and differs deliberately from the old `(cmd, result)`. `_slim()` keys match the card fields Task 4 reads (`name`, `name_th`, `category`, `benefits`, `why`). Requirement field names are one list (`_REQUIREMENT_FIELDS`) used by the tool declaration, the dispatcher, and `FIELD_LABELS` in the UI. `CONFIG.enquiry_prefix` produces `KT-POC-001`, which is what the tests assert and what spec §8 shows on screen.
