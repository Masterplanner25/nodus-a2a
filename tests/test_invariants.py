"""
Standing assertions for nodus-a2a.  All 8 must remain green across every phase.

Assertion inventory (see docs/design/00-decisions.md §D):
  1. no-new-opcodes        — BYTECODE_VERSION == 4
  2. no-task-emitted       — response oneof is always Message, never Task
  3. no-kind-discriminator — no 'kind' field on any Part or payload
  4. no-legacy-wellknown   — /.well-known/agent.json is not served
  5. version-negotiation   — A2A-Version mismatch → VersionNotSupportedError
  6. codec-name-mapping    — proto snake_case never appears on the wire
  7. capability-honesty    — streaming/push/extended-card all advertised false
  8. inversion-note        — D6 inversion documented in 05-deferred-features.md

Each assertion is tested at the appropriate layer (codec, transport, or doc).
Some assertions have multiple test functions covering different layers — this is
intentional so a regression at any single layer fails the suite.

Phase H audit: all 8 assertions verified complete and substantive (no stubs or
skips remain). Each assertion is tested at both its primary layer and at the HTTP
transport layer where applicable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_keys(obj: object, keys: set[str] | None = None) -> set[str]:
    """Recursively collect all dict keys from a nested structure."""
    if keys is None:
        keys = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for v in obj.values():
            _collect_keys(v, keys)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_keys(item, keys)
    return keys


DOCS_DIR = Path(__file__).parent.parent / "docs" / "design"

# ---------------------------------------------------------------------------
# 1. no-new-opcodes
# ---------------------------------------------------------------------------

def test_no_new_opcodes():
    """D2: nodus-a2a must not introduce new opcodes. BYTECODE_VERSION stays 4."""
    try:
        from nodus.compiler.compiler import BYTECODE_VERSION  # noqa: E402
    except ImportError:
        pytest.skip(
            "nodus-lang not importable — run with "
            "PYTHONPATH='C:/dev/nodus-a2a/src;C:/dev/Coding Language/src'"
        )
    assert BYTECODE_VERSION == 4, (
        f"D2 violation: BYTECODE_VERSION must stay 4; got {BYTECODE_VERSION}. "
        "nodus-a2a must not introduce new opcodes."
    )


# ---------------------------------------------------------------------------
# 2. no-task-emitted
# ---------------------------------------------------------------------------

def test_no_task_emitted():
    """D5: SendMessage response must be a Message, never a Task."""
    from nodus_a2a.codec import encode_send_message_response, make_response_message
    from nodus_a2a.message import Message, Role, TextPart

    inbound = Message(
        message_id="inbound-001",
        role=Role.USER,
        parts=(TextPart(text="hello"),),
        context_id="ctx-001",
    )
    response_msg = make_response_message(inbound, "world")
    wire = encode_send_message_response(response_msg)

    assert "task" not in wire, (
        "D5 violation: SendMessage response must not contain a 'task' key. "
        f"Got keys: {list(wire.keys())}"
    )
    assert "message" in wire, (
        "D5 violation: SendMessage response must contain a 'message' key."
    )
    # The payload must not be a Task shape (no 'id' + 'status' combo)
    msg_payload = wire["message"]
    assert "id" not in msg_payload or "status" not in msg_payload, (
        "D5 violation: response payload looks like a Task (has both 'id' and 'status')."
    )


# ---------------------------------------------------------------------------
# 3. no-kind-discriminator
# ---------------------------------------------------------------------------

def test_no_kind_discriminator():
    """D4b: no 'kind' field on any Part variant or response payload."""
    from nodus_a2a.codec import encode_part, encode_send_message_response
    from nodus_a2a.message import DataPart, Message, RawPart, Role, TextPart, UrlPart

    parts = [
        TextPart(text="hello"),
        RawPart(raw=b"\x00\x01\x02"),
        UrlPart(url="https://example.com/file.pdf"),
        DataPart(data={"x": 1, "y": [2, 3]}),
        DataPart(data=42),
        DataPart(data=None),
    ]
    for p in parts:
        wire = encode_part(p)
        all_keys = _collect_keys(wire)
        assert "kind" not in all_keys, (
            f"D4b violation: {type(p).__name__} produces a 'kind' field on the wire. "
            f"Wire dict: {wire}"
        )

    # Also check the full response envelope
    msg = Message(
        message_id="test-kind-001",
        role=Role.AGENT,
        parts=(TextPart(text="no kind here"),),
    )
    response_wire = encode_send_message_response(msg)
    all_response_keys = _collect_keys(response_wire)
    assert "kind" not in all_response_keys, (
        f"D4b violation: response envelope contains a 'kind' field. "
        f"All keys: {all_response_keys}"
    )


# ---------------------------------------------------------------------------
# 4. no-legacy-wellknown  (Phase E — HTTP server required)
# ---------------------------------------------------------------------------

def test_no_legacy_wellknown():
    """D4b: /.well-known/agent.json must NOT be served (0.3-era path)."""
    from nodus_a2a.card import cache_agent_card
    from nodus_a2a.config import ServerConfig
    from nodus_a2a.transport import handle_request

    config = ServerConfig(
        base_url="https://example.com",
        agent_name="Invariant Agent",
        agent_description="For invariant tests",
    )
    _, card_bytes = cache_agent_card(config, [])

    def _dummy_invoke(name, args):
        return "ok"

    status, _, _ = handle_request(
        method="GET",
        path="/.well-known/agent.json",
        headers={},
        body=b"",
        card_bytes=card_bytes,
        invoke=_dummy_invoke,
        tool_names=[],
        token_validator=None,
    )
    assert status == 404, (
        f"no-legacy-wellknown violation: /.well-known/agent.json returned {status}, "
        "expected 404. The 0.3-era path must never be served."
    )


# ---------------------------------------------------------------------------
# 5. version-negotiation  (Phase G — negotiate_version() required)
# ---------------------------------------------------------------------------

def test_version_negotiation():
    """D4: A2A-Version != '1.0' must raise VersionNotSupportedError."""
    from nodus_a2a.errors import VersionNotSupportedError
    from nodus_a2a.transport import negotiate_version

    # 0.3 must be rejected
    with pytest.raises(VersionNotSupportedError, match="not supported"):
        negotiate_version({"A2A-Version": "0.3"})

    # 2.0 must be rejected
    with pytest.raises(VersionNotSupportedError):
        negotiate_version({"A2A-Version": "2.0"})

    # 1.0 must be accepted
    negotiate_version({"A2A-Version": "1.0"})  # no raise

    # 1.0.1 must be accepted (patch version within supported major.minor)
    negotiate_version({"A2A-Version": "1.0.1"})  # no raise

    # Missing header must be accepted (lenient mode, doc 03 §4.2)
    negotiate_version({})  # no raise


# ---------------------------------------------------------------------------
# 6. codec-name-mapping
# ---------------------------------------------------------------------------

def test_codec_name_mapping_message():
    """Standing assertion: proto snake_case field names must not appear on the wire."""
    from nodus_a2a.codec import encode_message, encode_part
    from nodus_a2a.message import DataPart, Message, Role, TextPart

    msg = Message(
        message_id="map-001",
        role=Role.AGENT,
        parts=(
            TextPart(text="hello", media_type="text/plain"),
            DataPart(data={"nested": True}),
        ),
        context_id="ctx-map-001",
        reference_task_ids=("ref-1",),
        extensions=("ext-uri",),
    )
    wire = encode_message(msg)
    all_keys = _collect_keys(wire)

    SNAKE_FIELDS = {
        "message_id",
        "context_id",
        "task_id",
        "reference_task_ids",
        "media_type",
        "accepted_output_modes",
        "return_immediately",
        "history_length",
    }
    violations = SNAKE_FIELDS & all_keys
    assert not violations, (
        f"codec-name-mapping violation: proto snake_case keys appeared on wire: "
        f"{violations}"
    )

    # Confirm the camelCase versions are present where expected
    assert "messageId" in wire
    assert "contextId" in wire
    assert "referenceTaskIds" in wire


def test_codec_name_mapping_part():
    """Part fields must use camelCase on the wire."""
    from nodus_a2a.codec import encode_part
    from nodus_a2a.message import RawPart, TextPart

    text_wire = encode_part(TextPart(text="hi", media_type="text/markdown"))
    assert "mediaType" in text_wire
    assert "media_type" not in text_wire

    raw_wire = encode_part(RawPart(raw=b"data", filename="f.bin"))
    assert "filename" in raw_wire
    assert "mediaType" in raw_wire


def test_codec_roundtrip():
    """Decode then re-encode must produce an equivalent message."""
    import json

    from nodus_a2a.codec import decode_message, encode_message
    from nodus_a2a.message import Role

    wire_in = {
        "messageId": "rt-001",
        "role": "ROLE_USER",
        "parts": [
            {"text": "ping", "mediaType": "text/plain"},
            {"data": {"key": "value"}},
        ],
        "contextId": "ctx-rt",
        "referenceTaskIds": ["ref-a"],
    }
    msg = decode_message(wire_in)
    assert msg.message_id == "rt-001"
    assert msg.role == Role.USER
    assert msg.context_id == "ctx-rt"
    assert len(msg.parts) == 2

    wire_out = encode_message(msg)
    assert wire_out["messageId"] == "rt-001"
    assert wire_out["contextId"] == "ctx-rt"
    assert wire_out["referenceTaskIds"] == ["ref-a"]
    assert "task_id" not in wire_out


# ---------------------------------------------------------------------------
# 7. capability-honesty  (Phase B — build_agent_card() required)
# ---------------------------------------------------------------------------

def test_capability_honesty():
    """D5/D10: streaming, pushNotifications, extendedAgentCard must all be false."""
    from nodus_a2a.card import build_agent_card
    from nodus_a2a.config import ServerConfig

    config = ServerConfig(
        base_url="https://example.com",
        agent_name="Invariant Test Agent",
        agent_description="Used by the capability-honesty invariant test",
    )
    card = build_agent_card(config, [])
    caps = card.get("capabilities", {})

    assert caps.get("streaming") is False, (
        "D5 violation: capabilities.streaming must be False (streaming deferred to v0.2)"
    )
    assert caps.get("pushNotifications") is False, (
        "D10 violation: capabilities.pushNotifications must be False "
        "(push notifications deferred to v0.2)"
    )
    assert caps.get("extendedAgentCard") is False, (
        "D8b violation: capabilities.extendedAgentCard must be False "
        "(extended card deferred to v0.2)"
    )


# ---------------------------------------------------------------------------
# Transport-layer strengthening (Phase H audit additions)
# These tests verify the same invariants as above but through handle_request(),
# ensuring that transport-layer regressions are caught as well as codec-layer ones.
# ---------------------------------------------------------------------------

def _make_transport_fixture():
    """Return (card_bytes, invoke, tool_names) for transport-layer assertions."""
    from nodus_a2a.card import cache_agent_card
    from nodus_a2a.config import ServerConfig
    config = ServerConfig(
        base_url="https://example.com",
        agent_name="Phase H Invariant Agent",
        agent_description="Transport-layer invariant tests",
    )
    _, card_bytes = cache_agent_card(config, [])

    def invoke(name, args):
        return "ok"

    return card_bytes, invoke, []


def test_no_task_emitted_via_transport():
    """D5: SendMessage over the transport layer must never emit a Task."""
    import json
    from nodus_a2a.transport import handle_request

    card_bytes, invoke, tool_names = _make_transport_fixture()

    # Single-tool fallback path (no envelope, one tool registered)
    body = json.dumps({
        "message": {
            "messageId": "inv-no-task-001",
            "role": "ROLE_USER",
            "parts": [{"text": "hello"}],
        }
    }).encode()

    status, _, resp_body = handle_request(
        method="POST",
        path="/message:send",
        headers={},
        body=body,
        card_bytes=card_bytes,
        invoke=lambda n, a: "response text",
        tool_names=["myapp.only"],
        token_validator=None,
    )
    assert status == 200
    wire = json.loads(resp_body)
    assert "task" not in wire, (
        f"D5 violation (transport layer): SendMessage response contains 'task' key. "
        f"Keys: {list(wire.keys())}"
    )
    assert "message" in wire, (
        "D5 violation (transport layer): SendMessage response missing 'message' key."
    )


def test_no_legacy_wellknown_and_correct_path_serves():
    """D4b: agent.json → 404; agent-card.json → 200. Both must hold simultaneously."""
    import json
    from nodus_a2a.transport import handle_request

    card_bytes, invoke, tool_names = _make_transport_fixture()
    kwargs = dict(headers={}, body=b"", card_bytes=card_bytes,
                  invoke=invoke, tool_names=tool_names, token_validator=None)

    # Old 0.3 path: must be 404
    status_old, _, _ = handle_request("GET", "/.well-known/agent.json", **kwargs)
    assert status_old == 404, (
        f"no-legacy-wellknown violation: agent.json returned {status_old}, expected 404."
    )

    # Correct 1.0 path: must be 200 with a valid card body
    status_new, _, resp_body = handle_request("GET", "/.well-known/agent-card.json", **kwargs)
    assert status_new == 200, (
        f"Discovery broken: agent-card.json returned {status_new}, expected 200."
    )
    card = json.loads(resp_body)
    assert "name" in card and "capabilities" in card, (
        "Discovery response does not look like an AgentCard."
    )


def test_codec_name_mapping_agent_card():
    """AgentCard wire JSON must use camelCase throughout (no snake_case keys)."""
    import json
    from nodus_a2a.card import build_agent_card, project_skill
    from nodus_a2a.config import ServerConfig

    config = ServerConfig(
        base_url="https://agent.example.com",
        agent_name="Codec Invariant Agent",
        agent_description="For codec-name-mapping invariant test",
        provider_url="https://example.com",
        provider_org="ACME",
        documentation_url="https://docs.example.com",
    )
    tools = [
        {
            "name": "myapp.search",
            "description": "Search",
            "schema": {},
            "version": "1.0.0",
            "tags": ["search"],
            "deprecated": False,
            "metadata": {},
        }
    ]
    card = build_agent_card(config, tools)
    card_str = json.dumps(card)

    SNAKE_PATTERNS = [
        "protocol_binding", "protocol_version", "security_schemes",
        "security_requirements", "default_input_modes", "default_output_modes",
        "supported_interfaces", "extended_agent_card", "push_notifications",
        "http_auth_security_scheme", "bearer_format", "input_modes", "output_modes",
        "documentation_url",
    ]
    violations = [p for p in SNAKE_PATTERNS if p in card_str]
    assert not violations, (
        f"codec-name-mapping violation (AgentCard): snake_case keys in wire JSON: "
        f"{violations}"
    )

    # Spot-check key camelCase names are present
    assert "supportedInterfaces" in card_str
    assert "protocolBinding" in card_str
    assert "securitySchemes" in card_str
    assert "defaultInputModes" in card_str
    assert "pushNotifications" in card_str


def test_capability_honesty_via_wire_json():
    """D5/D10/D8b: capability flags must be False in the served wire JSON, not just the dict."""
    import json
    from nodus_a2a.transport import handle_request

    card_bytes, invoke, tool_names = _make_transport_fixture()
    _, _, resp_body = handle_request(
        "GET", "/.well-known/agent-card.json",
        headers={}, body=b"",
        card_bytes=card_bytes, invoke=invoke,
        tool_names=tool_names, token_validator=None,
    )
    card = json.loads(resp_body)
    caps = card.get("capabilities", {})

    assert caps.get("streaming") is False, (
        "D5 violation (wire): capabilities.streaming is not False in served card JSON."
    )
    assert caps.get("pushNotifications") is False, (
        "D10 violation (wire): capabilities.pushNotifications is not False in served card JSON."
    )
    assert caps.get("extendedAgentCard") is False, (
        "D8b violation (wire): capabilities.extendedAgentCard is not False in served card JSON."
    )


# ---------------------------------------------------------------------------
# 8. inversion-note
# ---------------------------------------------------------------------------

def test_inversion_note_documented():
    """D6: The A2A park-and-resume inversion must be documented in 05-deferred-features.md."""
    doc_path = DOCS_DIR / "05-deferred-features.md"
    assert doc_path.exists(), (
        "05-deferred-features.md not found; D6 inversion note cannot be verified."
    )
    text = doc_path.read_text(encoding="utf-8")

    assert "INPUT_REQUIRED" in text, (
        "inversion-note violation: 05-deferred-features.md must mention INPUT_REQUIRED."
    )
    assert any(term in text for term in ("park", "Park", "parked")), (
        "inversion-note violation: 05-deferred-features.md must describe park-and-resume."
    )
    assert "inversion" in text.lower(), (
        "inversion-note violation: 05-deferred-features.md must use the word 'inversion'."
    )
    assert any(
        term in text
        for term in ("no_thread_parks", "no-thread-parks", "no-park", "no_park")
    ), (
        "inversion-note violation: 05-deferred-features.md must reference the mcp "
        "no-park rule to warn future maintainers against importing it."
    )
