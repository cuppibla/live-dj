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
    tools.dispatch_tool("capture_requirements", {"phone": "0651049961"})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "80-room hotel", "confirmed": False})
    assert events == []
    assert result["result"] == "not_confirmed"


def test_enquiry_creates_numbered_reference_when_confirmed():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements",
                        {"business_type": "hotel", "contact_name": "Khun A",
                         "phone": "0651049961"})
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
    cats = [i["category"] for i in events[0]["items"]]
    assert "ice_machine" in cats
    assert any(c in ("washroom_dispenser", "toilet_tissue", "paper_towel") for c in cats)


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
    by_id = {i["id"]: i["source"] for i in events[0]["items"]}
    assert by_id["kt-ice-machine-modular"] == "looked_up"
    assert "recommended" in by_id.values()


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
    assert events[0]["items"][0]["category"] == "glassware"


def test_enquiry_carries_the_products_actually_discussed():
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    tools.dispatch_tool("capture_requirements", {"phone": "0651049961"})
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
        {"products": ["kt-tissue-dispenser-controlled"], "interest": "wanted"})
    wanted = [i for i in events[0]["items"] if i["interest"] == "wanted"]
    assert [w["id"] for w in wanted] == ["kt-tissue-dispenser-controlled"]
    assert result["wanted"] == ["Controlled Tissue Dispenser System"]


def test_customer_interest_resolves_a_product_by_name():
    """The model works from what it said aloud, not from ids it may not have kept."""
    tools.reset_state()
    events, result = tools.dispatch_tool(
        "record_customer_interest", {"products": ["Modular Ice Machine"], "interest": "wanted"})
    assert result["wanted"] == ["Modular Ice Machine"]
    assert events[0]["items"][0]["interest"] == "wanted"


def test_customer_interest_adds_a_product_not_yet_on_the_panel():
    tools.reset_state()
    events, _ = tools.dispatch_tool(
        "record_customer_interest", {"products": ["kt-ice-machine-modular"], "interest": "wanted"})
    assert any(i["id"] == "kt-ice-machine-modular" for i in events[0]["items"])


def test_customer_interest_can_be_withdrawn():
    tools.reset_state()
    tools.dispatch_tool("record_customer_interest",
                        {"products": ["kt-ice-machine-modular"], "interest": "wanted"})
    events, _ = tools.dispatch_tool("record_customer_interest",
                                    {"products": ["kt-ice-machine-modular"], "interest": "declined"})
    item = next(i for i in events[0]["items"] if i["id"] == "kt-ice-machine-modular")
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
                        {"products": ["kt-ice-machine-modular"], "interest": "wanted"})
    for q in ["dispenser", "tissue", "towel", "cleaner", "floor", "glass", "soap"]:
        events, _ = tools.dispatch_tool("search_products", {"query": q})
    assert any(i["id"] == "kt-ice-machine-modular" and i["interest"] == "wanted"
               for i in events[0]["items"])


def test_enquiry_separates_wanted_from_merely_discussed():
    tools.reset_state()
    tools.dispatch_tool("recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    tools.dispatch_tool("record_customer_interest",
                        {"products": ["kt-tissue-dispenser-controlled"], "interest": "wanted"})
    tools.dispatch_tool("capture_requirements", {"phone": "0651049961"})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel washrooms", "confirmed": True})
    assert [p["name"] for p in result["products_wanted"]] == ["Controlled Tissue Dispenser System"]
    assert result["products_discussed"]
    assert "kt-tissue-dispenser-controlled" not in [p["id"] for p in result["products_discussed"]]
    assert events[0]["products_wanted"]


# --- real brands, portfolio level only ---

def test_catalogue_is_broad_and_well_differentiated():
    prods = CONFIG.products
    assert len(prods) >= 50
    assert len({p["category"] for p in prods}) >= 20
    # every segment must have real coverage, so nothing gets mapped onto a near-miss
    for seg in CONFIG.rules["customer_segments"]:
        assert catalog.segment_covered(prods, seg), seg


def test_no_product_carries_a_fabricated_specification():
    """Invented detail that looks precise is more dangerous than detail that looks vague:
    nobody questions a number. Specs come from Kittichet or they do not exist."""
    for p in CONFIG.products:
        assert p["specifications"] == {}
        assert p["price_status"] == "contact_sales"
        assert p["availability_status"] == "confirmation_required"


def test_brands_are_real_and_declared():
    declared = set(CONFIG.rules["authorized_brands"])
    used = {b for p in CONFIG.products for b in p.get("brands", [])}
    assert used <= declared, f"undeclared brand: {used - declared}"
    assert "Kimberly-Clark" in declared and "Ecolab" in declared


def test_no_product_name_claims_a_model():
    """A real brand attached to an invented model number misrepresents that brand.
    Names stay at category/family level."""
    import re
    for p in CONFIG.products:
        assert not re.search(r"\b[A-Z]{1,4}[-\s]?\d{2,}\b", p["name"]), p["name"]
        for b in p.get("brands", []):
            assert b not in p["name"], f"{p['name']} presents itself as a {b} SKU"


def test_search_finds_products_by_brand():
    hits = catalog.search(CONFIG.products, query="Ecolab")
    assert hits and all("Ecolab" in h["brands"] for h in hits)


def test_brands_reach_the_model_and_the_ui():
    _, result = tools.dispatch_tool(
        "recommend_products", {"business_type": "hotel", "needs": ["washroom"]})
    assert any(r["brands"] for r in result["recommendations"])


def test_instruction_names_the_brands_and_forbids_model_detail():
    from backend.config import SYSTEM_INSTRUCTION
    assert "Kimberly-Clark" in SYSTEM_INSTRUCTION
    assert "authorized distributor" in SYSTEM_INSTRUCTION
    assert "model number" in SYSTEM_INSTRUCTION


# --- ranking at scale: the failure mode a bigger catalogue introduces ---

def test_recommendations_lead_with_the_right_category():
    """At 18 products almost everything tied and catalogue file order decided the
    ranking. At 55 that meant a restaurant asking about kitchen degreasing was shown
    hand towel dispensers. Ranking has to hold as the catalogue grows."""
    cases = [
        ("restaurant", ["kitchen degreasing", "dishwasher"], "degreaser"),
        ("factory", ["floor cleaning machine"], "floor_machine"),
        ("pharmacy", ["hand hygiene"], "hand_hygiene"),
        ("hotel", ["laundry", "linen"], "laundry_chemical"),
        ("restaurant", ["takeaway packaging"], "food_packaging"),
        ("hotel", ["glassware for the restaurant"], "glassware"),
        ("hotel", ["ice machine"], "ice_machine"),
    ]
    for business, needs, expected in cases:
        top = catalog.recommend(CONFIG.products, business, needs)[0]
        assert top["category"] == expected, f"{business}/{needs} -> {top['name']}"


def test_an_exact_word_outranks_a_stem_match():
    hits = catalog.search(CONFIG.products, query="glassware")
    assert hits[0]["category"] == "glassware"


def test_stemming_reaches_across_english_word_endings():
    """A customer says "degreasing"; the catalogue says "degreaser"."""
    assert catalog.search(CONFIG.products, query="degreasing")[0]["category"] == "degreaser"
    assert catalog.search(CONFIG.products, query="polishing")


def test_a_short_token_does_not_prefix_match_a_longer_word():
    hits = catalog.search(CONFIG.products, query="Ecolab")
    assert all("Ecolab" in h["brands"] for h in hits)


# --- an enquiry nobody can answer is not a lead ---

def test_enquiry_refuses_without_any_way_to_contact_the_customer():
    """It submitted KT-POC-001 with no name, phone or email, and the customer had to ask
    whether it could even reach them. The whole product promise is a qualified lead."""
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"business_type": "hotel", "scale": "80 rooms"})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "80-room hotel", "confirmed": True})
    assert events == []
    assert result["result"] == "missing_contact"
    assert "phone" in result["instruction"] and "email" in result["instruction"]


def test_enquiry_accepts_a_phone_alone():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"phone": "0651049961"})
    _, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel", "confirmed": True})
    assert result["enquiry_id"].endswith("-001")


def test_enquiry_accepts_an_email_alone():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"email_or_line": "taro@mercil.co.th"})
    _, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel", "confirmed": True})
    assert result["enquiry_id"].endswith("-001")


def test_a_name_alone_is_not_a_contact_channel():
    """A name with no phone or email cannot be followed up."""
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"contact_name": "คุณธนวัฒน์"})
    events, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel", "confirmed": True})
    assert events == []
    assert result["result"] == "missing_contact"


def test_missing_contact_is_checked_before_confirmation():
    """Asking for a yes and then refusing would make the assistant look broken."""
    tools.reset_state()
    _, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel", "confirmed": False})
    assert result["result"] == "missing_contact"


def test_the_instruction_names_what_is_still_missing():
    tools.reset_state()
    tools.dispatch_tool("capture_requirements", {"phone": "0651049961"})
    _, result = tools.dispatch_tool(
        "create_sales_enquiry", {"summary": "hotel", "confirmed": False})
    assert result["result"] == "not_confirmed"      # contact is satisfied, so confirm next


# --- a need must match a product substantially, not on one incidental word ---

def test_a_single_generic_word_does_not_carry_a_recommendation():
    """The demo showed "Modular Ice Machine — matches the stated need for scrubbing
    machines to replace manual scrubbing". It matched on the word "machines"."""
    recs = catalog.recommend(CONFIG.products, "hotel",
                             ["scrubbing machines to replace manual scrubbing"])
    assert "ice_machine" not in [r["category"] for r in recs]
    assert recs[0]["category"] in ("floor_machine", "scrubbing_pad")


def test_a_partly_matching_need_is_not_claimed_as_a_match():
    recs = catalog.recommend(CONFIG.products, "hotel",
                             ["scrubbing machines to replace manual scrubbing"])
    unrelated = {"ice_machine", "rice", "glassware", "tableware", "food_packaging",
                 "facial_tissue", "toilet_tissue"}
    for r in recs:
        if "matches the stated need" in r["why"]:
            assert r["category"] not in unrelated, r["name"]


def test_every_profile_pins_its_transcription_languages():
    for profile in ("kittichet", "default"):
        cfg = load_config(profile)
        assert cfg.transcription_languages, profile
        for code in cfg.transcription_languages:
            assert "-" in code, f"{profile}: {code} is not a BCP-47 code"


# --- spoken brevity, without turning the assistant terse ---

def test_delivery_rules_are_in_the_instruction():
    from backend.config import SYSTEM_INSTRUCTION

    for rule in ["One or two short sentences",
                 "Never re-read a list",
                 "Do not repeat details back",
                 "at most three products"]:
        assert rule in SYSTEM_INSTRUCTION, rule


def test_brevity_never_applies_to_the_confirmation_summary():
    """"Detailed summary only when requested" would quietly kill the read-back before
    submitting — which is acceptance criteria 8 to 10 and the mechanical guard's whole
    point. The exception has to be explicit."""
    from backend.config import SYSTEM_INSTRUCTION

    assert "brevity never applies to it" in SYSTEM_INSTRUCTION
    assert "confirming the" in SYSTEM_INSTRUCTION


def test_brevity_is_bounded_so_the_assistant_does_not_go_terse():
    """A model told only to be short becomes unhelpful. It needs explicit permission to
    answer properly when the customer actually wants detail."""
    from backend.config import SYSTEM_INSTRUCTION

    assert "Being brief is not being unhelpful" in SYSTEM_INSTRUCTION


# --- resolving what the customer agreed to, from what the assistant said out loud ---

def test_resolve_handles_a_name_with_the_brand_appended():
    """The assistant says the product the way it said it aloud, not the catalogue's exact
    string. Requiring containment lost "the neutral floor cleaner from Ecolab"."""
    p, confident = tools._resolve("น้ำยาถูพื้นสูตรเป็นกลางของ Ecolab")
    assert p["id"] == "kt-floor-cleaner-neutral" and confident


def test_resolve_asks_rather_than_guesses_on_a_loose_match():
    """A customer's own wording lands close to the right product but not close enough to
    act on: "สเปรย์ปรับอากาศแบบพ่นอัตโนมัติ" scores 0.317 and the washer-dryer we do NOT
    sell scores 0.320. No threshold separates them, so a weak match becomes a question."""
    p, confident = tools._resolve("สเปรย์ปรับอากาศแบบพ่นอัตโนมัติ")
    assert p["id"] == "kt-air-freshener-dispenser"
    assert not confident

    p, confident = tools._resolve("automatic air freshener spray")
    assert p["id"] == "kt-air-freshener-dispenser" and not confident


def test_resolve_is_certain_about_exact_names_and_ids():
    for token, pid in [("เครื่องขัดพื้นแบบเดินตาม", "kt-floor-scrubber-walkbehind"),
                       ("Neutral Floor Cleaner", "kt-floor-cleaner-neutral"),
                       ("kt-ice-machine-modular", "kt-ice-machine-modular"),
                       ("เครื่องทำน้ำแข็ง", "kt-ice-machine-modular")]:
        p, confident = tools._resolve(token)
        assert p["id"] == pid and confident, token


def test_resolve_returns_nothing_for_something_unrelated():
    assert tools._resolve("a helicopter") == (None, False)
    assert tools._resolve("รถยนต์ไฟฟ้า") == (None, False)


def test_a_product_we_do_not_carry_is_never_silently_recorded():
    """A washer-dryer scores as highly as a real product. It must not go on the list."""
    tools.reset_state()
    events, result = tools.dispatch_tool(
        "record_customer_interest",
        {"products": ["เครื่องซักผ้าอบแห้ง 20 กิโล"], "interest": "wanted"})
    assert result["result"] == "needs_confirmation"
    assert result["on_the_list"] == []
    assert events == []


def test_interest_reports_failure_instead_of_claiming_success():
    """It answered "บันทึกไว้เรียบร้อยแล้ว" — recorded successfully — while recording
    nothing at all. A tool that returns ok for a total failure will be believed."""
    tools.reset_state()
    events, result = tools.dispatch_tool(
        "record_customer_interest", {"products": ["a helicopter"], "interest": "wanted"})
    assert result["result"] == "not_found"
    assert "not" in result["instruction"].lower()
    assert events == []


def test_interest_flags_a_partial_failure():
    tools.reset_state()
    _, result = tools.dispatch_tool(
        "record_customer_interest",
        {"products": ["Neutral Floor Cleaner", "a helicopter"], "interest": "wanted"})
    assert result["result"] == "partial"
    assert result["not_found"] == ["a helicopter"]


def test_interest_returns_the_whole_list_so_the_summary_is_grounded():
    """Its closing summary listed three products when only one had been recorded, because
    it was summarising from memory. Every call now returns what is actually on the list."""
    tools.reset_state()
    tools.dispatch_tool("record_customer_interest",
                        {"products": ["Neutral Floor Cleaner"], "interest": "wanted"})
    _, result = tools.dispatch_tool(
        "record_customer_interest",
        {"products": ["Programmable Air Freshener Dispenser"], "interest": "wanted"})
    assert set(result["on_the_list"]) == {"Neutral Floor Cleaner",
                                          "Programmable Air Freshener Dispenser"}


def test_the_products_from_the_failed_demo_reach_the_list():
    """Two of these three silently vanished; only the floor scrubber made the panel."""
    tools.reset_state()
    _, result = tools.dispatch_tool("record_customer_interest", {
        "products": ["น้ำยาถูพื้นสูตรเป็นกลางของ Ecolab",
                     "เครื่องจ่ายน้ำหอมปรับอากาศ",
                     "เครื่องขัดพื้นแบบเดินตาม"],
        "interest": "wanted"})
    assert result["result"] == "ok", result
    assert len(result["on_the_list"]) == 3
