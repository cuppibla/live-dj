"""Sales tools for the voice consultant.

The lesson from the DJ build still holds: in a live session, function calls are
SYNCHRONOUS — the model's voice pauses until the tool returns. Every handler here does
the minimum (filter a list, update a dict) and returns INSTANTLY.

Each returns (ui_events, result): the events go to the browser panels, the result goes
back to the model.
"""
import re

from backend import catalog
from backend.config import CONFIG

# Fields worth putting on screen. Anything else the model volunteers lands in notes.
_REQUIREMENT_FIELDS = [
    "contact_name", "company_name", "phone", "email_or_line",
    "business_type", "location", "scale", "priority", "timeline", "notes",
]

# How many products the panel carries. The customer is looking at this while they talk,
# so it is a shortlist, not a catalogue dump.
MAX_SHORTLIST = 8

_requirements: dict = {}
_shortlist: list = []
_enquiry_count = 0


def reset_state() -> None:
    """Fresh conversation — a new browser session starts from an empty sheet."""
    global _requirements, _shortlist, _enquiry_count
    _requirements = {}
    _shortlist = []
    _enquiry_count = 0


def _trim() -> None:
    """Cap the panel — but never drop something the customer said they want.

    The shortlist is capped so browsing doesn't turn it into a catalogue dump. What the
    customer actually asked for is not browsing, and losing it off the bottom of the list
    would lose the one thing the sales team needs.
    """
    global _shortlist
    keep, budget = [], MAX_SHORTLIST
    for e in _shortlist:
        if e.get("interest") == "wanted":
            keep.append(e)
        elif budget > 0:
            keep.append(e)
            budget -= 1
    _shortlist = keep


# Above STRONG we act; between MIN and STRONG we ask; below MIN we say we don't have it.
# There is no threshold that separates a real match from a wrong one by score alone —
# "สเปรย์ปรับอากาศแบบพ่นอัตโนมัติ" (a product we carry) scores 0.317 and
# "เครื่องซักผ้าอบแห้ง" (one we do not) scores 0.320, because Thai compounds share
# morphemes with everything. So a weak match becomes a question, not a guess.
_MIN_SIMILARITY = 0.3
_STRONG_SIMILARITY = 0.6


def _trigrams(text: str) -> set:
    t = "".join((text or "").lower().split())
    return {t[i:i + 3] for i in range(max(0, len(t) - 2))}


def _similarity(a: str, b: str) -> float:
    """Dice overlap on character trigrams.

    Thai is written without spaces, so there is nothing to tokenise on and no stemming to
    apply — comparing character runs is what actually works across "สเปรย์ปรับอากาศ"
    and "เครื่องจ่ายน้ำหอมปรับอากาศ".
    """
    A, B = _trigrams(a), _trigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


def _resolve(token: str):
    """Resolve however the assistant described a product aloud -> (product|None, confident).

    This used to require the phrase to be a SUBSTRING of the catalogue name, so the
    assistant only ever succeeded by quoting the catalogue back verbatim. Saying "the
    neutral floor cleaner from Ecolab", or calling the programmable air freshener
    dispenser an "automatic air freshener spray" the way the customer had, resolved to
    nothing — and the customer was told it had been saved anyway.
    """
    t = (token or "").strip().lower()
    if not t:
        return None, False
    for p in CONFIG.products:
        if p["id"].lower() == t:
            return p, True
    # Containment either way: the phrase may be longer than the catalogue name or shorter.
    for p in CONFIG.products:
        for field in (p["name"], p.get("name_th") or ""):
            f = field.lower()
            if f and (t in f or f in t):
                return p, True
    best, best_score = None, 0.0
    for p in CONFIG.products:
        score = max(_similarity(t, p["name"]), _similarity(t, p.get("name_th") or ""))
        if score > best_score:
            best, best_score = p, score
    if best is None or best_score < _MIN_SIMILARITY:
        return None, False
    # Character overlap alone is thin — "a helicopter" scores 0.296 against "Janitorial
    # Cleaning Cart" on letter runs that mean nothing. Where the query has words to check,
    # insist on a real shared word too. Thai has none, so similarity stands alone there.
    words = set(re.findall(r"[a-z]{3,}", t)) - catalog._STOPWORDS
    if words and not (words & set(re.findall(r"[a-z]{3,}", best["name"].lower()))):
        return None, False
    return best, best_score >= _STRONG_SIMILARITY


def _remember(items: list, source: str) -> list:
    """Add a batch to the running shortlist and return the whole thing, newest first.

    The panel has to survive the whole conversation. Emitting only the latest tool call
    meant one incidental lookup ("do you have ice machines?") wiped the recommendations
    built up over the previous five minutes — the assistant still remembered them, the
    screen didn't, and the customer saw the screen.

    `source` is carried per item so a card never implies the assistant recommended
    something it merely looked up.
    """
    global _shortlist
    prior = {e["id"]: e.get("interest") for e in _shortlist}
    ids = {i["id"] for i in items}
    kept = [e for e in _shortlist if e["id"] not in ids]
    _shortlist = [{**i, "source": source, "interest": prior.get(i["id"])}
                  for i in items] + kept
    _trim()
    return list(_shortlist)


def _brief(p: dict) -> dict:
    """The handoff view of a product — what a salesperson needs to act on it."""
    return {"id": p["id"], "name": p["name"], "name_th": p.get("name_th", ""),
            "category": p["category"], "brands": p.get("brands", []),
            "interest": p.get("interest")}


def _slim(p: dict) -> dict:
    """What the model and the UI actually need — never the whole record."""
    out = {
        "id": p["id"], "name": p["name"], "name_th": p.get("name_th", ""),
        "category": p["category"], "brands": p.get("brands", []),
        "benefits": p.get("benefits", []),
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
                "business_type": {"type": "string", "description": (
                    "The customer's business. Configured segments: "
                    + ", ".join(CONFIG.rules["customer_segments"])
                    + ". If the customer's business is not one of these, pass their own "
                      "words rather than forcing it into the closest segment — the result "
                      "tells you whether the catalogue covers it, and an honest 'we don't "
                      "have products specific to that' beats a confident wrong answer.")},
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
        "name": "record_customer_interest",
        "description": (
            "Record that the customer has said they DO want something, or that they have "
            "ruled it out. Call this the moment they express a decision — 'yes, we'd want "
            "that', 'add that one', 'not the roll type'. This is what separates what you "
            "merely discussed from what they are actually asking for, and it is what the "
            "sales team acts on. Pass product names as you said them aloud, or their ids."),
        "parameters": {
            "type": "object",
            "properties": {
                "products": {"type": "array", "items": {"type": "string"},
                             "description": "product names or ids the customer decided on"},
                "interest": {"type": "string", "enum": ["wanted", "declined"],
                             "description": "wanted if they want it, declined if they ruled it out"},
            },
            "required": ["products", "interest"],
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
        )][:catalog.MAX_RECOMMENDATIONS]
        events = [{"type": "products", "items": _remember(hits, "looked_up")}] if hits else []
        return events, {"count": len(hits), "products": hits,
                        "note": "demonstration catalogue data; price and availability require a human"}

    if name == "recommend_products":
        business_type = args.get("business_type", "")
        hits = [_slim(p) for p in catalog.recommend(
            CONFIG.products, business_type, args.get("needs") or [])]
        covered = catalog.segment_covered(CONFIG.products, business_type)
        if covered:
            note = "explain why each fits what the customer told you"
        else:
            # Say so rather than letting the customer assume these were chosen for their
            # industry. Silently substituting the nearest segment is how a pharmacy ended
            # up being shown products picked for offices.
            note = (f"The catalogue does not cover '{business_type}'. These are "
                    f"general-purpose options, not chosen for that industry — tell the "
                    f"customer plainly and offer a specialist. Configured segments: "
                    f"{', '.join(CONFIG.rules['customer_segments'])}.")
        return [{"type": "products", "items": _remember(hits, "recommended")}], {
            "count": len(hits), "recommendations": hits,
            "segment_in_catalogue": covered, "note": note}

    if name == "capture_requirements":
        for field in _REQUIREMENT_FIELDS:
            value = args.get(field)
            if isinstance(value, str) and value.strip():
                _requirements[field] = value.strip()
        return ([{"type": "requirements", "requirements": dict(_requirements)}],
                {"result": "ok", "captured": dict(_requirements)})

    if name == "record_customer_interest":
        interest = args.get("interest") or "wanted"
        if interest not in ("wanted", "declined"):
            interest = "wanted"
        resolved, unsure, not_found = [], [], []
        for token in args.get("products") or []:
            found, confident = _resolve(token)
            if found and confident:
                resolved.append(found)
            elif found:
                unsure.append((token, found))
            else:
                not_found.append(token)
        if resolved:
            # Put them on the panel if they aren't already, then mark them. A customer can
            # ask for something by name before it was ever recommended or searched.
            _remember([_slim(p) for p in resolved], "recommended")
            ids = {p["id"] for p in resolved}
            for entry in _shortlist:
                if entry["id"] in ids:
                    entry["interest"] = interest
            _trim()
        on_the_list = [e["name"] for e in _shortlist if e.get("interest") == "wanted"]
        ask = "; ".join(f'"{tok}" -> {p["name"]} ({p.get("name_th", "")})'
                        for tok, p in unsure)
        if not resolved and unsure:
            # Recording the near-miss silently is how the wrong product would reach the
            # sales team. Asking is what a salesperson does anyway.
            return [], {"result": "needs_confirmation", "closest": ask,
                        "on_the_list": on_the_list,
                        "instruction": "NOT recorded yet — do not say it was saved. Ask the "
                                       "customer to confirm you have the right product: "
                                       + ask + ". If they say yes, call this again using "
                                       "that exact catalogue name."}
        if not resolved:
            # Returning "ok" for a total failure got the customer told "บันทึกไว้เรียบร้อยแล้ว"
            # — recorded successfully — while nothing had been recorded at all.
            return [], {"result": "not_found", "not_found": not_found,
                        "on_the_list": on_the_list,
                        "instruction": "NOTHING was recorded — do not tell the customer it "
                                       "was saved. Say you are not sure which product they "
                                       "mean, name the closest ones from the catalogue, and "
                                       "ask them to pick."}
        out = {"result": "ok" if not not_found else "partial",
               interest: [p["name"] for p in resolved],
               "not_found": not_found,
               # The whole list, every time. Its closing summary named three products when
               # only one had been recorded, because it was summarising from memory.
               "on_the_list": on_the_list}
        notes = []
        if not_found:
            notes.append("NOT recorded, we do not appear to carry these: "
                         + ", ".join(not_found))
        if unsure:
            notes.append("NOT recorded, confirm the product first: " + ask)
        if notes:
            out["result"] = "partial"
            out["instruction"] = ("; ".join(notes)
                                  + ". Tell the customer which ones did not go on before "
                                    "you move on.")
        return [{"type": "products", "items": list(_shortlist)}], out

    if name == "create_sales_enquiry":
        # A lead nobody can answer is not a lead. Checked BEFORE confirmation, so the
        # assistant never asks for a yes and then refuses — it submitted an enquiry with
        # no name, phone or email and the customer had to ask if it could reach them.
        if not (_requirements.get("phone") or _requirements.get("email_or_line")):
            missing = ["phone number", "email or LINE"]
            if not _requirements.get("contact_name"):
                missing.insert(0, "the customer's name")
            return [], {"result": "missing_contact",
                        "instruction": "Do not submit yet. You still need a way for the sales "
                                       "team to reach this customer: ask for " + ", or ".join(missing)
                                       + ". Record it with capture_requirements, then read the "
                                         "summary back including the contact details and ask "
                                         "for confirmation."}
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
            "products_wanted": [_brief(p) for p in _shortlist
                                if p.get("interest") == "wanted"],
            "products_discussed": [_brief(p) for p in _shortlist
                                   if p.get("interest") != "wanted"],
            "status": "prepared_for_sales_team",
            "demo_only": True,
        }
        return [enquiry], {k: v for k, v in enquiry.items() if k != "type"}

    return [], {"result": f"unknown tool: {name}"}
