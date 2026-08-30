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

    # The segment is a FILTER, not a hint. Offering a hotel a product only sold into
    # factories is the kind of ungrounded recommendation this whole design exists to
    # prevent — so if we know the segment and stock anything for it, that is the pool.
    in_segment = [p for p in products
                  if bt and bt in [c.lower() for c in p.get("customer_types", [])]]
    pool = in_segment or products

    scored = []
    for p in pool:
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
            for p in pool[:3]]
