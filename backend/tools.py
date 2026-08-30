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
    ids = {i["id"] for i in items}
    kept = [e for e in _shortlist if e["id"] not in ids]
    _shortlist = [{**i, "source": source} for i in items] + kept
    del _shortlist[MAX_SHORTLIST:]
    return list(_shortlist)


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
            "products_discussed": [{"id": p["id"], "name": p["name"],
                                    "category": p["category"], "source": p["source"]}
                                   for p in _shortlist],
            "status": "prepared_for_sales_team",
            "demo_only": True,
        }
        return [enquiry], {k: v for k, v in enquiry.items() if k != "type"}

    return [], {"result": f"unknown tool: {name}"}
