"""Tests for Phase C: SendMessage handler and tool dispatch."""

from __future__ import annotations

import pytest

from nodus_a2a.codec import decode_message, encode_send_message_response
from nodus_a2a.errors import ToolNotFoundError, ValidationError
from nodus_a2a.handler import extract_tool_call, handle_send_message, make_error_message
from nodus_a2a.message import (
    DataPart,
    Message,
    RawPart,
    Role,
    SendMessageRequest,
    TextPart,
    UrlPart,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request(parts, tool_names=None) -> tuple[SendMessageRequest, list[str]]:
    """Build a SendMessageRequest from parts and a tool-names list."""
    msg = Message(
        message_id="test-msg-001",
        role=Role.USER,
        parts=tuple(parts),
        context_id="ctx-001",
    )
    req = SendMessageRequest(message=msg)
    return req, (tool_names or [])


def _invoke_echo(name: str, args: dict) -> object:
    """Dummy invoker: echoes tool name and args as a dict."""
    return {"tool": name, "args": args}


def _invoke_str(name: str, args: dict) -> str:
    """Dummy invoker: returns a plain string."""
    return f"result from {name}"


def _invoke_bytes(name: str, args: dict) -> bytes:
    return b"\x00\x01\x02"


def _invoke_raise(exc: Exception):
    def _inv(name: str, args: dict):
        raise exc
    return _inv


# ---------------------------------------------------------------------------
# extract_tool_call
# ---------------------------------------------------------------------------

class TestExtractToolCall:
    def test_envelope_in_datapart(self):
        parts = (DataPart(data={"tool": "myapp.foo", "args": {"x": 1}}),)
        name, args = extract_tool_call(parts, ["myapp.foo"])
        assert name == "myapp.foo"
        assert args == {"x": 1}

    def test_envelope_tool_not_in_registry(self):
        parts = (DataPart(data={"tool": "myapp.unknown", "args": {}}),)
        with pytest.raises(ToolNotFoundError, match="not registered"):
            extract_tool_call(parts, ["myapp.other"])

    def test_envelope_args_default_to_empty(self):
        parts = (DataPart(data={"tool": "myapp.t"}),)
        _, args = extract_tool_call(parts, ["myapp.t"])
        assert args == {}

    def test_envelope_non_dict_args_coerced_to_empty(self):
        parts = (DataPart(data={"tool": "myapp.t", "args": "wrong_type"}),)
        _, args = extract_tool_call(parts, ["myapp.t"])
        assert args == {}

    def test_text_part_skipped_in_primary_scan(self):
        """TextParts are not tool envelopes; should trigger single-tool fallback."""
        parts = (TextPart(text="hello"),)
        name, args = extract_tool_call(parts, ["myapp.sole"])
        assert name == "myapp.sole"
        assert args == {}

    def test_datapart_without_tool_key_skipped(self):
        """DataPart without 'tool' key should not trigger primary dispatch."""
        parts = (DataPart(data={"foo": "bar"}),)
        name, args = extract_tool_call(parts, ["myapp.sole"])
        assert name == "myapp.sole"

    def test_url_part_skipped(self):
        parts = (UrlPart(url="https://example.com"),)
        name, args = extract_tool_call(parts, ["myapp.sole"])
        assert name == "myapp.sole"

    def test_single_tool_fallback(self):
        name, args = extract_tool_call((), ["myapp.only"])
        assert name == "myapp.only"
        assert args == {}

    def test_zero_tools_raises(self):
        with pytest.raises(ToolNotFoundError, match="No tools"):
            extract_tool_call((), [])

    def test_multiple_tools_no_envelope_raises(self):
        parts = (TextPart(text="hi"),)
        with pytest.raises(ToolNotFoundError, match="2 tools"):
            extract_tool_call(parts, ["myapp.a", "myapp.b"])

    def test_first_matching_envelope_wins(self):
        """Only the first DataPart with a 'tool' key is used."""
        parts = (
            DataPart(data={"tool": "myapp.first", "args": {"n": 1}}),
            DataPart(data={"tool": "myapp.second", "args": {"n": 2}}),
        )
        name, args = extract_tool_call(parts, ["myapp.first", "myapp.second"])
        assert name == "myapp.first"
        assert args == {"n": 1}

    def test_non_dict_datapart_skipped(self):
        """DataPart with non-dict data (e.g. a list) is not an envelope."""
        parts = (DataPart(data=[1, 2, 3]),)
        name, args = extract_tool_call(parts, ["myapp.sole"])
        assert name == "myapp.sole"


# ---------------------------------------------------------------------------
# make_error_message
# ---------------------------------------------------------------------------

class TestMakeErrorMessage:
    def test_error_datapart_format(self):
        inbound = Message(
            message_id="m1", role=Role.USER,
            parts=(TextPart(text="hi"),), context_id="ctx-1",
        )
        exc = ValueError("something went wrong")
        response = make_error_message(inbound, exc)

        assert response.role == Role.AGENT
        assert len(response.parts) == 1
        part = response.parts[0]
        assert isinstance(part, DataPart)
        assert part.data["error"] == "something went wrong"
        assert part.data["type"] == "ValueError"
        assert part.media_type == "application/json"

    def test_context_propagated(self):
        inbound = Message(
            message_id="m1", role=Role.USER,
            parts=(TextPart(text="x"),), context_id="ctx-42",
        )
        response = make_error_message(inbound, RuntimeError("oops"))
        assert response.context_id == "ctx-42"

    def test_task_id_always_empty(self):
        inbound = Message(
            message_id="m1", role=Role.USER,
            parts=(TextPart(text="x"),),
        )
        response = make_error_message(inbound, RuntimeError("x"))
        assert response.task_id == ""

    def test_no_task_in_wire(self):
        inbound = Message(
            message_id="m1", role=Role.USER,
            parts=(TextPart(text="x"),),
        )
        response = make_error_message(inbound, RuntimeError("x"))
        wire = encode_send_message_response(response)
        assert "task" not in wire
        assert "message" in wire


# ---------------------------------------------------------------------------
# handle_send_message
# ---------------------------------------------------------------------------

class TestHandleSendMessage:
    def test_str_result_becomes_text_part(self):
        req, names = _request(
            [DataPart(data={"tool": "myapp.greet", "args": {}})],
            ["myapp.greet"],
        )
        response = handle_send_message(req, _invoke_str, names)
        assert response.role == Role.AGENT
        assert len(response.parts) == 1
        assert isinstance(response.parts[0], TextPart)
        assert "myapp.greet" in response.parts[0].text

    def test_dict_result_becomes_data_part(self):
        req, names = _request(
            [DataPart(data={"tool": "myapp.echo", "args": {"x": 1}})],
            ["myapp.echo"],
        )
        response = handle_send_message(req, _invoke_echo, names)
        assert isinstance(response.parts[0], DataPart)
        data = response.parts[0].data
        assert data["tool"] == "myapp.echo"
        assert data["args"] == {"x": 1}

    def test_bytes_result_becomes_raw_part(self):
        req, names = _request(
            [DataPart(data={"tool": "myapp.bin"})],
            ["myapp.bin"],
        )
        response = handle_send_message(req, _invoke_bytes, names)
        assert isinstance(response.parts[0], RawPart)
        assert response.parts[0].raw == b"\x00\x01\x02"

    def test_single_tool_fallback_invoked(self):
        req, names = _request([TextPart(text="anything")], ["myapp.sole"])
        response = handle_send_message(req, _invoke_str, names)
        assert isinstance(response.parts[0], TextPart)

    def test_tool_not_found_returns_error_message(self):
        req, names = _request(
            [DataPart(data={"tool": "myapp.ghost"})],
            ["myapp.other"],
        )
        response = handle_send_message(req, _invoke_echo, names)
        part = response.parts[0]
        assert isinstance(part, DataPart)
        assert "not registered" in part.data["error"]
        assert part.data["type"] == "ToolNotFoundError"

    def test_tool_raises_returns_error_message(self):
        req, names = _request(
            [DataPart(data={"tool": "myapp.boom"})],
            ["myapp.boom"],
        )
        response = handle_send_message(
            req, _invoke_raise(RuntimeError("kaboom")), names
        )
        part = response.parts[0]
        assert isinstance(part, DataPart)
        assert part.data["error"] == "kaboom"
        assert part.data["type"] == "RuntimeError"

    def test_invoke_key_error_returns_error_message(self):
        """invoke() raising KeyError (tool disappeared) → error Message, not exception."""
        req, names = _request(
            [DataPart(data={"tool": "myapp.t"})],
            ["myapp.t"],
        )
        response = handle_send_message(
            req, _invoke_raise(KeyError("myapp.t")), names
        )
        part = response.parts[0]
        assert isinstance(part, DataPart)
        assert "disappeared" in part.data["error"] or "ToolNotFoundError" == part.data["type"]

    def test_validation_error_propagates(self):
        """Malformed inbound message raises ValidationError, not error Message."""
        bad_msg = Message(
            message_id="",       # empty — required
            role=Role.USER,
            parts=(TextPart(text="hi"),),
        )
        req = SendMessageRequest(message=bad_msg)
        with pytest.raises(ValidationError, match="message_id"):
            handle_send_message(req, _invoke_echo, ["myapp.t"])

    def test_context_propagated_to_response(self):
        req, names = _request(
            [DataPart(data={"tool": "myapp.t"})], ["myapp.t"]
        )
        response = handle_send_message(req, _invoke_str, names)
        assert response.context_id == "ctx-001"

    def test_response_task_id_always_empty(self):
        """D5: task_id must be empty in all v0.1 responses."""
        req, names = _request(
            [DataPart(data={"tool": "myapp.t"})], ["myapp.t"]
        )
        response = handle_send_message(req, _invoke_str, names)
        assert response.task_id == ""

    def test_no_task_in_wire_response(self):
        """D5: wire response must have 'message' key, never 'task'."""
        req, names = _request(
            [DataPart(data={"tool": "myapp.t"})], ["myapp.t"]
        )
        response = handle_send_message(req, _invoke_str, names)
        wire = encode_send_message_response(response)
        assert "task" not in wire
        assert "message" in wire

    def test_no_kind_in_error_response(self):
        """Error response must not have 'kind' field (D4b)."""
        # Valid parts but no tools registered → error DataPart in response
        req, names = _request([TextPart(text="hello")], [])
        response = handle_send_message(req, _invoke_echo, names)
        wire = encode_send_message_response(response)
        import json
        assert '"kind"' not in json.dumps(wire)

    def test_zero_tools_returns_error_message(self):
        req, names = _request([TextPart(text="hello")], [])
        response = handle_send_message(req, _invoke_echo, names)
        part = response.parts[0]
        assert isinstance(part, DataPart)
        assert "No tools" in part.data["error"]

    def test_multiple_tools_no_envelope_returns_error(self):
        req, names = _request([TextPart(text="hello")], ["myapp.a", "myapp.b"])
        response = handle_send_message(req, _invoke_echo, names)
        part = response.parts[0]
        assert isinstance(part, DataPart)
        assert "2 tools" in part.data["error"]
