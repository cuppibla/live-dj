"""Pure catalogue lookups. No model, no I/O, no network — these run inside a live
function call, and every millisecond here is a gap in the assistant's voice.
"""
import re


_MIN_STEM = 5


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text)


def _token_matches(token: str, hay: str) -> bool:
    """Match a search token against a product's text.

    Plain substring matching was quietly catastrophic: "ice" is inside "office",
    "service" and "price", so searching for an ice machine returned tissue dispensers
    and hand soap — and not the ice machine. ASCII tokens must therefore align to a
    whole word. They also need to survive English word endings — a customer asking about
    "degreasing" has to reach the "degreaser" — so words match on a shared stem, with a
    length floor so short words don't collide. Thai is written without spaces, so Thai
    tokens keep substring matching; there is no word boundary to anchor to.
    """
    if not token.isascii():
        return token in hay
    for w in _words(hay):
        if w == token:
            return True
        # Prefix matching only when the shorter word is substantial. Without the floor,
        # "Ecolab" matched the word "eco" in "Eco Cup and Lid Range" and the brand search
        # returned products from another brand entirely.
        short, long_ = (w, token) if len(w) < len(token) else (token, w)
        if len(short) >= _MIN_STEM and long_.startswith(short):
            return True
        if len(w) >= _MIN_STEM and len(token) >= _MIN_STEM and w[:_MIN_STEM] == token[:_MIN_STEM]:
            return True
    return False


# What a match is worth, by where it lands. A product whose NAME says "degreaser" is a
# better answer than one that merely mentions cleaning somewhere in its benefits. Without
# this weighting every product in the segment scored the same and catalogue file order
# decided the ranking — invisible at 18 products, badly wrong at 55.
_STRONG, _MID, _WEAK = 3, 2, 1

# Function words score points against any product that happens to contain them — "to"
# earned the ice machine two points off "capacity sized to daily consumption".
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "have", "has", "in",
    "is", "it", "its", "my", "need", "needs", "of", "on", "or", "our", "some", "that",
    "the", "there", "this", "to", "want", "wants", "we", "with", "you", "your",
}


def _content_tokens(text: str) -> list:
    seen, out = set(), []
    for t in (text or "").lower().split():
        if len(t) > 1 and t not in _STOPWORDS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _fields(p: dict):
    strong = " ".join([p.get("name", ""), p.get("name_th", ""),
                       p.get("category", "").replace("_", " ")] + p.get("brands", [])).lower()
    mid = " ".join(p.get("use_cases", [])).lower()
    weak = " ".join(p.get("benefits", []) + p.get("customer_types", [])).lower()
    return strong, mid, weak


def _match_rank(token: str, hay: str) -> int:
    """2 for an exact word, 1 for a stem or prefix match, 0 for none.

    An exact hit has to outrank a fuzzy one or ties fall back to catalogue file order:
    searching "glassware" put "Glass and Mirror Cleaner" above the glassware range,
    because both merely counted as a hit in the name.
    """
    if not token.isascii():
        return 2 if token in hay else 0
    if token in _words(hay):
        return 2
    return 1 if _token_matches(token, hay) else 0


def _token_score(token: str, p: dict) -> int:
    for hay, weight in zip(_fields(p), (_STRONG, _MID, _WEAK)):
        rank = _match_rank(token, hay)
        if rank:
            return weight * rank
    return 0


def _haystack(p: dict) -> str:
    parts = [p.get("name", ""), p.get("name_th", ""), p.get("category", "")]
    parts += (p.get("use_cases", []) + p.get("benefits", [])
              + p.get("customer_types", []) + p.get("brands", []))
    return " ".join(parts).lower()


def search(products: list, query: str = "", category: str = "", customer_type: str = "") -> list:
    """Filter the catalogue. Empty filters match everything; all filters are AND-ed."""
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower()
    ctype = (customer_type or "").strip().lower()
    # Same stopword filter as recommend(): without it "a helicopter" matched products on
    # the word "a", and the interest resolver happily returned one of them.
    tokens = _content_tokens(q)
    scored = []
    for p in products:
        if cat and p.get("category", "").lower() != cat:
            continue
        if ctype and ctype not in [c.lower() for c in p.get("customer_types", [])]:
            continue
        score = 0
        if tokens:
            score = sum(_token_score(t, p) for t in tokens)
            if score == 0:
                continue
        scored.append((score, p))
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
        matched = []
        for need in needs:
            toks = _content_tokens(need)
            if not toks:
                continue
            hits = [_token_score(tok, p) for tok in toks]
            n = sum(1 for h in hits if h)
            # A phrase is not satisfied by one incidental word. "scrubbing machines to
            # replace manual scrubbing" matched the Modular Ice Machine on "machines"
            # alone, and the card then claimed it met that need. Longer needs have to
            # match on more than one content word, and the score scales with how much of
            # the phrase actually landed.
            if n < (1 if len(toks) <= 2 else 2):
                continue
            matched.append(need)
            score += sum(hits) * (n / len(toks))
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
