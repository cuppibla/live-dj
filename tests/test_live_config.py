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


def test_live_config_survives_the_real_backend_conversion():
    """Pydantic validation is NOT enough, and trusting it cost a working demo.

    types.LiveConnectConfig happily accepted input_audio_transcription.language_codes;
    the SDK's Developer-API converter then rejected it at session open with "only
    supported in Gemini Enterprise Agent Platform mode". Every call would have failed.
    This runs the same conversion the SDK runs on connect, so a field that is valid in
    the model but unsupported on this backend fails here instead of mid-demo.
    """
    from google.genai import _live_converters as converters

    from backend.raw_server import MODEL, client

    params = types.LiveConnectParameters(
        model=MODEL, config=types.LiveConnectConfig(**LIVE_CONFIG))
    to_backend = (converters._LiveConnectParameters_to_vertex
                  if client._api_client.vertexai
                  else converters._LiveConnectParameters_to_mldev)
    to_backend(api_client=client._api_client,
               from_object=params.model_dump(exclude_none=True))


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


def test_transcription_languages_are_only_sent_where_they_are_supported():
    """The profile declares Thai and English, but the Developer API rejects language_codes
    outright — so it must be dropped there rather than breaking every session."""
    from backend.config import CONFIG
    from backend.raw_server import USE_VERTEX

    assert "th-TH" in CONFIG.transcription_languages
    assert "en-US" in CONFIG.transcription_languages

    cfg = types.LiveConnectConfig(**LIVE_CONFIG)
    sent = cfg.input_audio_transcription.language_codes
    assert sent == (CONFIG.transcription_languages if USE_VERTEX else None)


def test_the_spoken_language_is_not_forced():
    """Pinning speech_config.language_code would stop the assistant following a customer
    who switches language — which the demo script relies on as its fallback."""
    cfg = types.LiveConnectConfig(**LIVE_CONFIG)
    assert cfg.speech_config.language_code is None
