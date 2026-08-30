"""Pure catalogue lookups. No model, no I/O, no network — these run inside a live
function call, and every millisecond here is a gap in the assistant's voice.
"""
import re


def _token_matches(token: str, hay: str) -> bool:
    """Match a search token against a product's text.

    Plain substring matching was quietly catastrophic: "ice" is inside "office",
    "service" and "price", so searching for an ice machine returned tissue dispensers
    and hand soap — and not the ice machine. ASCII tokens therefore have to start at a
    word boundary. Thai is written without spaces, so Thai tokens keep substring
    matching; there is no word boundary to anchor to.
    """
    if token.isascii():
        return re.search(r"\b" + re.escape(token), hay) is not None
    return token in hay


def _haystack(p: dict) -> str:
    parts = [p.get("name", ""), p.get("name_th", ""), p.get("category", "")]
    parts += p.get("use_cases", []) + p.get("benefits", []) + p.get("customer_types", [])
    return " ".join(parts).lower()


def search(products: list, query: str = "", category: str = "", customer_type: str = "") -> list:
    """Filter the catalogue. Empty filters match everything; all filters are AND-ed."""
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()
    ctype = (customer_type or "").strip().lower()
    tokens = q.split()
    scored = []
    for p in products:
        if cat and p.get("category", "").lower() != cat:
            continue
        if ctype and ctype not in [c.lower() for c in p.get("customer_types", [])]:
            continue
        hits = 0
        if tokens:
            hay = _haystack(p)
            hits = sum(1 for t in tokens if _token_matches(t, hay))
            if hits == 0:
                continue
        scored.append((hits, p))
    # Rank by how many query tokens matched, so "ice machine" puts the ice machine first
    # instead of burying it behind everything that merely matched "machine". Python's
    # sort is stable, so equal scores keep catalogue order.
    scored.sort(key=lambda s: -s[0])
    return [p for _, p in scored]


MAX_RECOMMENDATIONS = 4


def segment_covered(products: list, business_type: str) -> bool:
    """Does the catalogue actually serve this segment? The assistant needs to know,
    because the honest answer to an uncovered segment is to say so — not to quietly
    recommend the nearest thing and let the customer assume it was chosen for them.
    """
    bt = (business_type or "").strip().lower()
    if not bt:
        return False
    return any(bt in [c.lower() for c in p.get("customer_types", [])] for p in products)


def _listed_for(p: dict, bt: str) -> list:
    """The segments to name, caller's own first — but ONLY when the record really lists it.

    Truncating to three otherwise hid the customer's own segment behind three others: a
    pharmacy read "listed for hotel, hospital, office" about a product that does serve
    pharmacies, and reasonably concluded it wasn't meant for them.
    """
    types = p.get("customer_types", [])
    if bt and bt in [c.lower() for c in types]:
        first = [c for c in types if c.lower() == bt]
        return first + [c for c in types if c.lower() != bt][:2]
    return types[:3]


def _why(p: dict, matched: list, bt: str = "") -> str:
    """Build the spoken reason from the product's OWN catalogue entry.

    It must never repeat the caller's business_type back as an assertion. The model has
    to map an unlisted business onto some segment just to search, and echoing that guess
    produced the demo's worst moment: a pharmacy told that every product was "suited to
    office operations" — a claim about the customer's business that nobody had made.
    What the catalogue lists is true regardless of how the model mapped the customer.
    """
    reasons = []
    if matched:
        reasons.append("matches the stated need for " + ", ".join(matched))
    listed = _listed_for(p, bt)
    if listed:
        reasons.append("catalogue lists it for " + ", ".join(listed))
    if p.get("benefits"):
        reasons.append("; ".join(p["benefits"][:2]))
    return " — ".join(reasons)


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
        matched = [n for n in needs if any(_token_matches(tok, hay) for tok in n.split())]
        score += len(matched)
        if score == 0:
            continue
        scored.append((score, {**p, "why": _why(p, matched, bt)}))
    scored.sort(key=lambda s: -s[0])
    hits = [p for _, p in scored[:MAX_RECOMMENDATIONS]]
    if hits:
        return hits
    # Nothing matched: fall back to the broadest entries rather than returning
    # nothing, so the assistant always has grounded data instead of improvising.
    return [{**p, "why": _why(p, [], bt) + " — general-purpose option, confirm with a specialist"}
            for p in pool[:3]]
