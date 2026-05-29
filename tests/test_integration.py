"""Phase I: End-to-end integration tests over a real HTTP server on loopback.

Covers round-trips not exercised in test_transport.py's unit/integration tests:
  - Actual Part type and content verification in responses (TextPart, DataPart, RawPart)
  - Tool-call-envelope dispatch (multi-tool agents)
  - Single-tool fallback dispatch
  - Context propagation (contextId echo)
  - Auth enforcement end-to-end
  - Error paths: tool raises → error DataPart in 200 response
  - Wire format correctness: camelCase throughout, no snake_case, no 'kind'
  - Agent Card field completeness in the served JSON
  - Validation errors (malformed message → 400)
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from urllib.error import HTTPError

import pytest

from nodus_a2a.config import ServerConfig
from nodus_a2a.transport import A2AHttpServer


# ---------------------------------------------------------------------------
# Shared invoker and config helpers
# ---------------------------------------------------------------------------

TOOLS = {
    "myapp.greet": lambda args: f"Hello, {args.get('name', 'world')}!",
    "myapp.echo": lambda args: {"echoed": args},
    "myapp.binary": lambda args: b"\xde\xad\xbe\xef",
    "myapp.boom": lambda args: (_ for _ in ()).throw(RuntimeError("tool exploded")),
    "myapp.null": lambda args: None,
    "myapp.number": lambda args: 42,
    "myapp.nested": lambda args: {"list": [1, 2, 3], "flag": True},
}

TOOL_ENTRIES = [
    {"name": n, "description": f"Tool {n}", "schema": {}, "version": "1.0.0",
     "tags": [], "deprecated": False, "metadata": {}}
    for n in TOOLS
]

TOOL_NAMES = [e["name"] for e in TOOL_ENTRIES]


def _invoke(name: str, args: dict) -> object:
    if name not in TOOLS:
        raise KeyError(f"Tool '{name}' not found")
    return TOOLS[name](args)


def _make_server(token_validator=None) -> A2AHttpServer:
    config = ServerConfig(
        base_url="https://example.com",
        agent_name="Phase I Test Agent",
        agent_description="Integration test agent with multiple tools",
        agent_version="0.1.0",
        host="127.0.0.1",
        port=0,
        token_validator=token_validator,
    )
    return A2AHttpServer(
        config=config,
        invoke=_invoke,
        tool_names=TOOL_NAMES,
        tools=TOOL_ENTRIES,
    )


def _wait_for_port(server: A2AHttpServer, retries: int = 50) -> str:
    for _ in range(retries):
        if server.port != 0:
            return f"http://127.0.0.1:{server.port}"
        time.sleep(0.05)
    raise RuntimeError("Server did not bind in time")


def _post(url: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
    raw = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/a2a+json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=raw, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


def _get(url: str, headers: dict | None = None) -> tuple[int, dict | bytes]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body
    except HTTPError as e:
        return e.code, json.loads(e.read())


def _tool_req(tool_name: str, args: dict | None = None) -> dict:
    """Build a minimal SendMessageRequest using the tool-call-envelope."""
    return {
        "message": {
            "messageId": f"int-{tool_name}-001",
            "role": "ROLE_USER",
            "parts": [{"data": {"tool": tool_name, "args": args or {}}}],
            "contextId": "ctx-integration",
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server_url():
    """Start a multi-tool server; yield base URL; stop after module."""
    srv = _make_server()
    srv.serve_in_thread()
    base = _wait_for_port(srv)
    yield base
    srv.close()


@pytest.fixture(scope="module")
def auth_server_url():
    """Start a server requiring bearer token 'secret'."""
    srv = _make_server(token_validator=lambda t: t == "secret")
    srv.serve_in_thread()
    base = _wait_for_port(srv)
    yield base
    srv.close()


# ---------------------------------------------------------------------------
# Agent Card round-trip (Phase E integration)
# ---------------------------------------------------------------------------

class TestAgentCardIntegration:
    def test_card_has_all_required_fields(self, server_url):
        status, card = _get(f"{server_url}/.well-known/agent-card.json")
        assert status == 200
        required = [
            "name", "description", "version", "supportedInterfaces",
            "capabilities", "defaultInputModes", "defaultOutputModes",
            "skills", "securitySchemes", "securityRequirements",
        ]
        for f in required:
            assert f in card, f"Required AgentCard field '{f}' missing"

    def test_card_skills_match_registered_tools(self, server_url):
        _, card = _get(f"{server_url}/.well-known/agent-card.json")
        skill_ids = {s["id"] for s in card["skills"]}
        assert skill_ids == set(TOOL_NAMES)

    def test_card_capabilities_all_false(self, server_url):
        _, card = _get(f"{server_url}/.well-known/agent-card.json")
        caps = card["capabilities"]
        assert caps["streaming"] is False
        assert caps["pushNotifications"] is False
        assert caps["extendedAgentCard"] is False

    def test_card_no_snake_case_keys(self, server_url):
        _, card = _get(f"{server_url}/.well-known/agent-card.json")
        card_str = json.dumps(card)
        for snake in [
            "supported_interfaces", "default_input_modes", "security_schemes",
            "protocol_binding", "protocol_version", "push_notifications",
            "extended_agent_card", "http_auth_security_scheme",
        ]:
            assert snake not in card_str, f"Snake_case key '{snake}' in card JSON"

    def test_card_no_kind_field(self, server_url):
        _, card = _get(f"{server_url}/.well-known/agent-card.json")
        assert "kind" not in json.dumps(card)

    def test_card_protocol_binding_is_http_json(self, server_url):
        _, card = _get(f"{server_url}/.well-known/agent-card.json")
        iface = card["supportedInterfaces"][0]
        assert iface["protocolBinding"] == "HTTP+JSON"
        assert iface["protocolVersion"] == "1.0"

    def test_card_bearer_security_scheme(self, server_url):
        _, card = _get(f"{server_url}/.well-known/agent-card.json")
        schemes = card["securitySchemes"]
        assert "bearer" in schemes
        bearer_scheme = schemes["bearer"]
        assert "httpAuthSecurityScheme" in bearer_scheme
        assert bearer_scheme["httpAuthSecurityScheme"]["scheme"] == "Bearer"


# ---------------------------------------------------------------------------
# SendMessage: TextPart result
# ---------------------------------------------------------------------------

class TestSendMessageTextPart:
    def test_str_tool_returns_text_part(self, server_url):
        status, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet", {"name": "Alice"}),
        )
        assert status == 200
        msg = body["message"]
        part = msg["parts"][0]
        assert "text" in part
        assert "Alice" in part["text"]
        assert part.get("mediaType", "text/plain") == "text/plain"

    def test_text_response_has_role_agent(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
        )
        assert body["message"]["role"] == "ROLE_AGENT"

    def test_text_response_has_message_id(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
        )
        msg = body["message"]
        assert "messageId" in msg
        assert msg["messageId"]  # non-empty

    def test_text_response_echoes_context_id(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
        )
        assert body["message"].get("contextId") == "ctx-integration"

    def test_text_response_no_task_id(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
        )
        assert body["message"].get("taskId", "") == ""

    def test_null_result_becomes_data_part(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.null"),
        )
        part = body["message"]["parts"][0]
        assert "data" in part
        assert part["data"] is None

    def test_number_result_becomes_data_part(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.number"),
        )
        part = body["message"]["parts"][0]
        assert "data" in part
        assert part["data"] == 42


# ---------------------------------------------------------------------------
# SendMessage: DataPart result
# ---------------------------------------------------------------------------

class TestSendMessageDataPart:
    def test_dict_result_is_data_part(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.echo", {"x": 1, "y": "hello"}),
        )
        part = body["message"]["parts"][0]
        assert "data" in part
        data = part["data"]
        assert data["echoed"] == {"x": 1, "y": "hello"}

    def test_nested_dict_preserved(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.nested"),
        )
        part = body["message"]["parts"][0]
        data = part["data"]
        assert data["list"] == [1, 2, 3]
        assert data["flag"] is True

    def test_data_part_has_application_json_media_type(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.echo", {"q": "test"}),
        )
        part = body["message"]["parts"][0]
        assert part.get("mediaType") == "application/json"

    def test_data_part_no_kind_field(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.echo"),
        )
        assert "kind" not in json.dumps(body)

    def test_data_part_no_task_in_response(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.echo"),
        )
        assert "task" not in body
        assert "message" in body


# ---------------------------------------------------------------------------
# SendMessage: RawPart result (bytes)
# ---------------------------------------------------------------------------

class TestSendMessageRawPart:
    def test_bytes_result_is_raw_part(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.binary"),
        )
        part = body["message"]["parts"][0]
        assert "raw" in part, f"Expected 'raw' key, got: {list(part.keys())}"

    def test_raw_part_is_valid_base64(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.binary"),
        )
        raw_b64 = body["message"]["parts"][0]["raw"]
        decoded = base64.b64decode(raw_b64)
        assert decoded == b"\xde\xad\xbe\xef"

    def test_raw_part_has_octet_stream_media_type(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.binary"),
        )
        part = body["message"]["parts"][0]
        assert part.get("mediaType") == "application/octet-stream"


# ---------------------------------------------------------------------------
# Dispatch: tool-call-envelope vs. single-tool fallback
# ---------------------------------------------------------------------------

class TestToolDispatch:
    def test_envelope_selects_specific_tool(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet", {"name": "Bob"}),
        )
        assert "Bob" in body["message"]["parts"][0]["text"]

    def test_envelope_passes_args(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.echo", {"key": "value", "num": 99}),
        )
        data = body["message"]["parts"][0]["data"]
        assert data["echoed"]["key"] == "value"
        assert data["echoed"]["num"] == 99

    def test_unknown_tool_returns_error_in_200_response(self, server_url):
        req = {
            "message": {
                "messageId": "dispatch-unknown-001",
                "role": "ROLE_USER",
                "parts": [{"data": {"tool": "myapp.doesnotexist", "args": {}}}],
            }
        }
        status, body = _post(f"{server_url}/message:send", req)
        assert status == 200  # application error, not HTTP error
        part = body["message"]["parts"][0]
        assert "data" in part
        assert "error" in part["data"]
        assert part["data"]["type"] == "ToolNotFoundError"

    def test_single_tool_fallback_via_text_part(self):
        """Single-tool agent: TextPart input dispatches to the sole registered tool."""
        config = ServerConfig(
            base_url="https://example.com",
            agent_name="Single Tool Agent",
            agent_description="One tool only",
            host="127.0.0.1", port=0,
        )
        single_tool_entry = [{
            "name": "myapp.sole", "description": "sole tool",
            "schema": {}, "version": "1.0.0",
            "tags": [], "deprecated": False, "metadata": {},
        }]
        srv = A2AHttpServer(
            config=config,
            invoke=lambda n, a: "sole result",
            tool_names=["myapp.sole"],
            tools=single_tool_entry,
        )
        srv.serve_in_thread()
        base = _wait_for_port(srv)
        try:
            req = {
                "message": {
                    "messageId": "single-001",
                    "role": "ROLE_USER",
                    "parts": [{"text": "any text"}],  # no envelope
                }
            }
            status, body = _post(f"{base}/message:send", req)
            assert status == 200
            part = body["message"]["parts"][0]
            assert "text" in part
            assert part["text"] == "sole result"
        finally:
            srv.close()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_tool_raises_returns_200_with_error_datapart(self, server_url):
        status, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.boom"),
        )
        assert status == 200  # application error → 200, not 500
        part = body["message"]["parts"][0]
        assert "data" in part
        assert "error" in part["data"]
        assert part["data"]["type"] == "RuntimeError"
        assert "tool exploded" in part["data"]["error"]

    def test_error_response_has_role_agent(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.boom"),
        )
        assert body["message"]["role"] == "ROLE_AGENT"

    def test_error_response_has_message_id(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.boom"),
        )
        assert body["message"]["messageId"]

    def test_error_response_no_task(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.boom"),
        )
        assert "task" not in body

    def test_invalid_json_body_returns_400(self, server_url):
        req = urllib.request.Request(
            f"{server_url}/message:send",
            data=b"not valid json }{",
            headers={"Content-Type": "application/a2a+json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            pytest.fail("Expected 400")
        except HTTPError as e:
            assert e.code == 400
            body = json.loads(e.read())
            assert body["error"]["code"] == "INVALID_ARGUMENT"

    def test_missing_message_field_400(self, server_url):
        status, body = _post(f"{server_url}/message:send", {"configuration": {}})
        assert status == 400
        assert body["error"]["code"] == "INVALID_ARGUMENT"

    def test_empty_parts_400(self, server_url):
        req = {
            "message": {
                "messageId": "empty-parts-001",
                "role": "ROLE_USER",
                "parts": [],
            }
        }
        status, body = _post(f"{server_url}/message:send", req)
        assert status == 400

    def test_error_part_has_application_json_media_type(self, server_url):
        _, body = _post(f"{server_url}/message:send", _tool_req("myapp.boom"))
        part = body["message"]["parts"][0]
        assert part.get("mediaType") == "application/json"

    def test_error_part_no_kind_field(self, server_url):
        _, body = _post(f"{server_url}/message:send", _tool_req("myapp.boom"))
        assert "kind" not in json.dumps(body)


# ---------------------------------------------------------------------------
# Auth enforcement (Phase F integration)
# ---------------------------------------------------------------------------

class TestAuthEnforcement:
    def test_valid_token_succeeds(self, auth_server_url):
        status, body = _post(
            f"{auth_server_url}/message:send",
            _tool_req("myapp.greet"),
            headers={"Authorization": "Bearer secret"},
        )
        assert status == 200
        assert "message" in body

    def test_missing_token_401(self, auth_server_url):
        status, body = _post(
            f"{auth_server_url}/message:send",
            _tool_req("myapp.greet"),
        )
        assert status == 401
        assert body["error"]["code"] == "AUTHENTICATION_REQUIRED"

    def test_wrong_token_401(self, auth_server_url):
        status, body = _post(
            f"{auth_server_url}/message:send",
            _tool_req("myapp.greet"),
            headers={"Authorization": "Bearer wrongtoken"},
        )
        assert status == 401

    def test_card_endpoint_no_auth_needed(self, auth_server_url):
        """Well-known endpoint must not require auth even on an auth-configured server."""
        status, card = _get(f"{auth_server_url}/.well-known/agent-card.json")
        assert status == 200
        assert "capabilities" in card


# ---------------------------------------------------------------------------
# Version negotiation (Phase G integration)
# ---------------------------------------------------------------------------

class TestVersionNegotiation:
    def test_correct_version_succeeds(self, server_url):
        status, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
            headers={"A2A-Version": "1.0"},
        )
        assert status == 200

    def test_patch_version_succeeds(self, server_url):
        status, _ = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
            headers={"A2A-Version": "1.0.1"},
        )
        assert status == 200

    def test_missing_version_succeeds(self, server_url):
        status, _ = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
        )
        assert status == 200

    def test_old_version_400(self, server_url):
        status, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
            headers={"A2A-Version": "0.3"},
        )
        assert status == 400
        assert body["error"]["code"] == "VERSION_NOT_SUPPORTED"

    def test_future_major_400(self, server_url):
        status, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.greet"),
            headers={"A2A-Version": "2.0"},
        )
        assert status == 400
        assert body["error"]["code"] == "VERSION_NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# Wire format correctness (end-to-end codec assertions)
# ---------------------------------------------------------------------------

class TestWireFormat:
    def test_response_uses_camel_case_throughout(self, server_url):
        _, body = _post(
            f"{server_url}/message:send",
            _tool_req("myapp.echo", {"sample": True}),
        )
        body_str = json.dumps(body)
        for snake in [
            "message_id", "context_id", "task_id", "reference_task_ids",
            "media_type", "return_immediately",
        ]:
            assert snake not in body_str, (
                f"Snake_case key '{snake}' in response wire JSON"
            )

    def test_response_has_message_id(self, server_url):
        _, body = _post(f"{server_url}/message:send", _tool_req("myapp.greet"))
        assert "messageId" in body["message"]

    def test_response_has_context_id(self, server_url):
        _, body = _post(f"{server_url}/message:send", _tool_req("myapp.greet"))
        assert "contextId" in body["message"]

    def test_content_type_is_a2a_json(self, server_url):
        req = urllib.request.Request(
            f"{server_url}/message:send",
            data=json.dumps(_tool_req("myapp.greet")).encode(),
            headers={"Content-Type": "application/a2a+json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            ct = r.headers.get("Content-Type", "")
            assert "application/a2a+json" in ct

    def test_no_task_key_in_any_successful_response(self, server_url):
        for tool in ["myapp.greet", "myapp.echo", "myapp.binary", "myapp.null"]:
            _, body = _post(f"{server_url}/message:send", _tool_req(tool))
            assert "task" not in body, (
                f"D5 violation: tool '{tool}' response contains 'task' key"
            )

    def test_no_kind_in_any_response(self, server_url):
        for tool in ["myapp.greet", "myapp.echo", "myapp.binary", "myapp.boom"]:
            _, body = _post(f"{server_url}/message:send", _tool_req(tool))
            assert '"kind"' not in json.dumps(body), (
                f"D4b violation: tool '{tool}' response contains 'kind' field"
            )
