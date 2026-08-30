"""The Live config can only be proven wrong by connecting, and a bad key fails at
session open — mid-demo. These checks validate it against the SDK's own model offline.
"""
from google.genai import types

from backend.raw_server import LIVE_CONFIG


def test_live_config_validates_against_the_sdk():
    """A typo in a config key is silently accepted by the dict and rejected by the API."""
    cfg = types.LiveConnectConfig(**LIVE_CONFIG)
    assert cfg.system_instruction
    assert cfg.response_modalities == ["AUDIO"]


def test_context_window_compression_is_configured():
    cfg = types.LiveConnectConfig(**LIVE_CONFIG)
    cwc = cfg.context_window_compression
    assert cwc is not None
    assert cwc.sliding_window is not None
    assert cwc.sliding_window.target_tokens < cwc.trigger_tokens


def test_compression_triggers_well_above_a_demo_conversation():
    """It must not fire during a 90-second to 3-minute presentation."""
    cfg = types.LiveConnectConfig(**LIVE_CONFIG)
    assert cfg.context_window_compression.trigger_tokens >= 16000


def test_every_tool_declaration_survives_serialisation():
    cfg = types.LiveConnectConfig(**LIVE_CONFIG)
    names = {d.name for d in cfg.tools[0].function_declarations}
    assert names == {"search_products", "recommend_products", "capture_requirements",
                     "record_customer_interest", "create_sales_enquiry"}
