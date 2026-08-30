import pytest

from backend.config import CONFIG, load_config


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


from backend import catalog, tools


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
    assert names == {"search_products", "recommend_products", "capture_requirements",
                     "record_customer_interest", "create_sales_enquiry"}
    for d in tools.TOOL_DECLARATIONS:
        assert d["parameters"]["type"] == "object"
        assert d["description"]


# --- grounding fixes: the "why" line must never assert the caller's guess as fact ---

def test_recommend_never_asserts_the_callers_business_type():
    """The model must map an unlisted business onto some segment to search at all.
    Echoing that guess back as 'suited to <x> operations' shows the customer a claim
    about their own business that nobody made. Regression: a pharmacy was told every
    product was 'suited to office operations'."""
    recs = catalog.recommend(CONFIG.products, "office", ["hand hygiene"])
    for r in recs:
        assert "suited to office operations" not in r["why"]
        assert "office operations" not in r["why"]


def test_why_is_grounded_in_the_products_own_catalogue_entry():
    recs = catalog.recommend(CONFIG.products, "hotel", ["washroom"])
    for r in recs:
        assert "catalogue lists it for" in r["why"]
        # every segment named in the reason is genuinely on the product record
        named = r["why"].split("catalogue lists it for ")[1].split(" — ")[0]
        for seg in named.split(", "):
            assert seg in r["customer_types"]


def test_segment_covered_reports_catalogue_reality():
    assert catalog.segment_covered(CONFIG.products, "hotel") is True
    assert catalog.segment_covered(CONFIG.products, "spaceport") is False
    assert catalog.segment_covered(CONFIG.products, "") is False


def test_pharmacy_is_a_covered_segment():
    """A pharmacy walked into the demo and the catalogue had nowhere to put it."""
    assert catalog.segment_covered(CONFIG.products, "pharmacy") is True
    assert "pharmacy" in CONFIG.rules["customer_segments"]


def test_dispatch_recommend_flags_an_uncovered_segment_instead_of_substituting():
    events, result = tools.dispatch_tool(
        "recommend_products", {"business_type": "spaceport", "needs": ["cleaning"]})
    assert result["segment_in_catalogue"] is False
    assert "spaceport" in result["note"]
    assert result["recommendations"]


def test_dispatch_recommend_confirms_a_covered_segment():
    _, result = tools.dispatch_tool(
        "recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    assert result["segment_in_catalogue"] is True


def test_recommend_returns_a_consultative_number_of_cards():
    """Eight cards is a wall of product, not a consultation."""
    recs = catalog.recommend(CONFIG.products, "hotel", ["washroom", "cleaning", "restaurant"])
    assert len(recs) <= 4


def test_capture_requirements_corrects_a_wrong_value():
    """An early mis-hear must be fixable — the panel showed 'ร้านอาหาร' for a pharmacy
    long after the assistant had understood otherwise."""
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"business_type": "ร้านอาหาร"})
    events, _ = tools.dispatch_tool("capture_requirements", {"business_type": "ร้านขายยา"})
    assert events[0]["requirements"]["business_type"] == "ร้านขายยา"


def test_recommend_products_declaration_lists_the_real_segments():
    d = next(d for d in tools.TOOL_DECLARATIONS if d["name"] == "recommend_products")
    desc = d["parameters"]["properties"]["business_type"]["description"]
    for seg in CONFIG.rules["customer_segments"]:
        assert seg in desc


# --- the shortlist: the panel must reflect the whole conversation, not the last tool call ---

def test_shortlist_accumulates_across_calls():
    """The agent carries the whole conversation; the panel used to show only the most
    recent catalogue call, so one incidental lookup wiped the recommendations."""
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    events, _ = tools.dispatch_tool("search_products", {"query": "ice machine"})
    names = [i["name"] for i in events[0]["items"]]
    assert any("Ice Machine" in n for n in names)
    assert any("Dispenser" in n or "Tissue" in n or "Towel" in n for n in names)


def test_shortlist_puts_the_newest_batch_first():
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    events, _ = tools.dispatch_tool("search_products", {"query": "ice machine"})
    assert "Ice Machine" in events[0]["items"][0]["name"]


def test_shortlist_deduplicates_by_id():
    tools.reset_state()
    tools.dispatch_tool("search_products", {"query": "ice machine"})
    events, _ = tools.dispatch_tool("search_products", {"query": "ice machine"})
    ids = [i["id"] for i in events[0]["items"]]
    assert len(ids) == len(set(ids))


def test_shortlist_marks_where_each_item_came_from():
    """A card must never imply the assistant recommended something it merely looked up."""
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    events, _ = tools.dispatch_tool("search_products", {"query": "ice machine"})
    by_name = {i["name"]: i["source"] for i in events[0]["items"]}
    assert by_name["Demo Modular Ice Machine"] == "looked_up"
    assert "recommended" in by_name.values()


def test_shortlist_is_capped():
    tools.reset_state()
    for q in ["dispenser", "tissue", "towel", "cleaner", "floor", "glass"]:
        events, _ = tools.dispatch_tool("search_products", {"query": q})
    assert len(events[0]["items"]) <= tools.MAX_SHORTLIST


def test_shortlist_resets_with_the_session():
    tools.dispatch_tool("search_products", {"query": "ice machine"})
    tools.reset_state()
    events, _ = tools.dispatch_tool("capture_requirements", {"business_type": "hotel"})
    assert events[0]["type"] == "requirements"
    events, _ = tools.dispatch_tool("search_products", {"query": "glassware"})
    assert all("Glassware" in i["name"] for i in events[0]["items"])


def test_enquiry_carries_the_products_actually_discussed():
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel washrooms", "confirmed": True})
    assert result["products_discussed"]
    assert events[0]["products_discussed"][0]["name"]


def test_search_does_not_match_a_token_inside_another_word():
    """"ice" is inside "office", "service" and "price". Searching for an ice machine
    returned tissue dispensers and hand soap, with the ice machine nowhere in sight."""
    hits = catalog.search(CONFIG.products, query="ice machine")
    assert hits[0]["category"] == "ice_machine"
    assert not any(h["category"] in ("toilet_tissue", "hand_hygiene") for h in hits)


def test_search_ranks_by_how_many_tokens_matched():
    hits = catalog.search(CONFIG.products, query="ice machine")
    assert "Ice Machine" in hits[0]["name"]


def test_search_still_matches_word_prefixes():
    assert catalog.search(CONFIG.products, query="dispens")
    assert catalog.search(CONFIG.products, query="clean")


# --- what the customer actually asked for, as opposed to what merely came up ---

def test_customer_interest_marks_a_product_wanted():
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    events, result = tools.dispatch_tool(
        "record_customer_interest",
        {"products": ["demo-product-001"], "interest": "wanted"})
    wanted = [i for i in events[0]["items"] if i["interest"] == "wanted"]
    assert [w["id"] for w in wanted] == ["demo-product-001"]
    assert result["wanted"] == ["Demo Controlled Tissue Dispenser"]


def test_customer_interest_resolves_a_product_by_name():
    """The model works from what it said aloud, not from ids it may not have kept."""
    tools.reset_state()
    events, result = tools.dispatch_tool(
        "record_customer_interest", {"products": ["Modular Ice Machine"], "interest": "wanted"})
    assert result["wanted"] == ["Demo Modular Ice Machine"]
    assert events[0]["items"][0]["interest"] == "wanted"


def test_customer_interest_adds_a_product_not_yet_on_the_panel():
    tools.reset_state()
    events, _ = tools.dispatch_tool(
        "record_customer_interest", {"products": ["demo-product-018"], "interest": "wanted"})
    assert any(i["id"] == "demo-product-018" for i in events[0]["items"])


def test_customer_interest_can_be_withdrawn():
    tools.reset_state()
    tools.dispatch_tool("record_customer_interest",
                        {"products": ["demo-product-018"], "interest": "wanted"})
    events, _ = tools.dispatch_tool("record_customer_interest",
                                    {"products": ["demo-product-018"], "interest": "declined"})
    item = next(i for i in events[0]["items"] if i["id"] == "demo-product-018")
    assert item["interest"] == "declined"


def test_customer_interest_reports_what_it_could_not_resolve():
    tools.reset_state()
    _, result = tools.dispatch_tool(
        "record_customer_interest", {"products": ["a flying car"], "interest": "wanted"})
    assert result["not_found"] == ["a flying car"]


def test_wanted_products_survive_a_later_search():
    """What the customer asked for must not be pushed off the panel by browsing."""
    tools.reset_state()
    tools.dispatch_tool("record_customer_interest",
                        {"products": ["demo-product-018"], "interest": "wanted"})
    for q in ["dispenser", "tissue", "towel", "cleaner", "floor", "glass", "soap"]:
        events, _ = tools.dispatch_tool("search_products", {"query": q})
    assert any(i["id"] == "demo-product-018" and i["interest"] == "wanted"
               for i in events[0]["items"])


def test_enquiry_separates_wanted_from_merely_discussed():
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    tools.dispatch_tool("record_customer_interest",
                        {"products": ["demo-product-001"], "interest": "wanted"})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel washrooms", "confirmed": True})
    assert [p["name"] for p in result["products_wanted"]] == ["Demo Controlled Tissue Dispenser"]
    assert result["products_discussed"]
    assert "demo-product-001" not in [p["id"] for p in result["products_discussed"]]
    assert events[0]["products_wanted"]
