"""
Standing assertions for nodus-a2a.  All 8 must remain green across every phase.

Assertion inventory (see docs/design/00-decisions.md §D):
  1. no-new-opcodes       — BYTECODE_VERSION == 4
  2. no-task-emitted      — response oneof is always Message, never Task
  3. no-kind-discriminator — no 'kind' field on any Part or payload
  4. no-legacy-wellknown  — /.well-known/agent.json is not served  (Phase E)
  5. version-negotiation  — A2A-Version mismatch → VersionNotSupportedError  (Phase G)
  6. codec-name-mapping   — proto snake_case never appears on the wire
  7. capability-honesty   — streaming/push/extended-card all advertised false  (Phase B)
  8. inversion-note       — D6 inversion documented in 05-deferred-features.md
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
    pytest.skip("Phase E not yet implemented — HTTP server required")


# ---------------------------------------------------------------------------
# 5. version-negotiation  (Phase G — negotiate_version() required)
# ---------------------------------------------------------------------------

def test_version_negotiation():
    """D4: A2A-Version != '1.0' must raise VersionNotSupportedError."""
    pytest.skip("Phase G not yet implemented — negotiate_version() required")


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
    pytest.skip("Phase B not yet implemented — build_agent_card() required")


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
