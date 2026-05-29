"""Tests for Phases D-G: HTTP transport, bearer auth, A2A-Version negotiation."""

from __future__ import annotations

import json
import time
import urllib.request
from urllib.error import HTTPError

import pytest

from nodus_a2a.card import cache_agent_card
from nodus_a2a.config import ServerConfig
from nodus_a2a.errors import AuthError, VersionNotSupportedError
from nodus_a2a.transport import (
    A2AHttpServer,
    extract_bearer_token,
    handle_request,
    negotiate_version,
    validate_auth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_config(**kw) -> ServerConfig:
    defaults = dict(
        base_url="https://example.com",
        agent_name="Test Agent",
        agent_description="Transport test agent",
        host="127.0.0.1",
        port=0,  # OS-assigned
    )
    defaults.update(kw)
    return ServerConfig(**defaults)


def _card_bytes(config=None, tools=None) -> bytes:
    cfg = config or _minimal_config()
    _, cb = cache_agent_card(cfg, tools or [])
    return cb


def _echo_invoke(name: str, args: dict) -> object:
    return {"tool": name, "args": args}


def _str_invoke(name: str, args: dict) -> str:
    return f"result from {name}"


def _dummy_req(tool_name="myapp.t") -> bytes:
    """Minimal valid SendMessageRequest body."""
    return json.dumps({
        "message": {
            "messageId": "test-001",
            "role": "ROLE_USER",
            "parts": [
                {"data": {"tool": tool_name, "args": {}}}
            ],
            "contextId": "ctx-test",
        }
    }).encode("utf-8")


def _handle(method, path, headers=None, body=b"", invoke=None, tool_names=None,
            token_validator=None, card_bytes=None):
    """Convenience wrapper for handle_request()."""
    cfg = _minimal_config()
    cb = card_bytes if card_bytes is not None else _card_bytes(cfg)
    return handle_request(
        method=method,
        path=path,
        headers=headers or {},
        body=body,
        card_bytes=cb,
        invoke=invoke or _str_invoke,
        tool_names=tool_names or ["myapp.t"],
        token_validator=token_validator,
    )


# ---------------------------------------------------------------------------
# Phase F: extract_bearer_token
# ---------------------------------------------------------------------------

class TestExtractBearerToken:
    def test_well_formed(self):
        headers = {"Authorization": "Bearer mysecrettoken"}
        assert extract_bearer_token(headers) == "mysecrettoken"

    def test_lowercase_header(self):
        headers = {"authorization": "Bearer token123"}
        assert extract_bearer_token(headers) == "token123"

    def test_missing_header_returns_none(self):
        assert extract_bearer_token({}) is None

    def test_wrong_scheme_returns_none(self):
        assert extract_bearer_token({"Authorization": "Basic dXNlcjpwYXNz"}) is None

    def test_bearer_only_no_token_returns_none(self):
        # "Bearer " prefix but nothing after → treated as empty token, not None
        result = extract_bearer_token({"Authorization": "Bearer "})
        assert result == ""  # empty string (falsy but not None)


# ---------------------------------------------------------------------------
# Phase F: validate_auth
# ---------------------------------------------------------------------------

class TestValidateAuth:
    def test_no_validator_allows_all(self):
        validate_auth(None, None)       # no error
        validate_auth("any", None)      # no error

    def test_valid_token_accepted(self):
        validate_auth("good-token", lambda t: t == "good-token")  # no error

    def test_missing_token_raises(self):
        with pytest.raises(AuthError, match="required"):
            validate_auth(None, lambda t: True)

    def test_invalid_token_raises(self):
        with pytest.raises(AuthError, match="Invalid"):
            validate_auth("bad-token", lambda t: t == "correct-token")


# ---------------------------------------------------------------------------
# Phase G: negotiate_version
# ---------------------------------------------------------------------------

class TestNegotiateVersion:
    def test_1_0_accepted(self):
        negotiate_version({"A2A-Version": "1.0"})  # no raise

    def test_1_0_patch_accepted(self):
        negotiate_version({"A2A-Version": "1.0.1"})  # no raise

    def test_0_3_rejected(self):
        with pytest.raises(VersionNotSupportedError, match="0.3"):
            negotiate_version({"A2A-Version": "0.3"})

    def test_2_0_rejected(self):
        with pytest.raises(VersionNotSupportedError):
            negotiate_version({"A2A-Version": "2.0"})

    def test_missing_accepted_lenient(self):
        negotiate_version({})  # no raise (lenient mode)

    def test_case_insensitive_header(self):
        negotiate_version({"a2a-version": "1.0"})  # no raise


# ---------------------------------------------------------------------------
# Phase E: handle_request — Agent Card
# ---------------------------------------------------------------------------

class TestHandleRequestAgentCard:
    def test_get_agent_card_200(self):
        cb = _card_bytes()
        status, headers, body = _handle("GET", "/.well-known/agent-card.json",
                                        card_bytes=cb)
        assert status == 200
        assert headers["Content-Type"] == "application/a2a+json"
        assert headers["Cache-Control"] == "public, max-age=3600"
        parsed = json.loads(body)
        assert "name" in parsed
        assert "capabilities" in parsed

    def test_agent_card_no_auth_required(self):
        """Well-known endpoint requires no auth even when validator is set."""
        cb = _card_bytes()
        status, _, _ = _handle("GET", "/.well-known/agent-card.json",
                                card_bytes=cb,
                                token_validator=lambda t: False)  # would reject
        assert status == 200

    def test_agent_card_no_version_check(self):
        """Well-known endpoint ignores A2A-Version header."""
        cb = _card_bytes()
        status, _, _ = _handle("GET", "/.well-known/agent-card.json",
                                headers={"A2A-Version": "0.3"},  # old version
                                card_bytes=cb)
        assert status == 200

    def test_legacy_wellknown_404(self):
        """0.3-era /.well-known/agent.json must return 404."""
        status, _, body = _handle("GET", "/.well-known/agent.json")
        assert status == 404

    def test_capabilities_honesty_in_card(self):
        cb = _card_bytes()
        _, _, body = _handle("GET", "/.well-known/agent-card.json", card_bytes=cb)
        card = json.loads(body)
        caps = card["capabilities"]
        assert caps["streaming"] is False
        assert caps["pushNotifications"] is False
        assert caps["extendedAgentCard"] is False

    def test_no_kind_in_card(self):
        cb = _card_bytes()
        _, _, body = _handle("GET", "/.well-known/agent-card.json", card_bytes=cb)
        assert b'"kind"' not in body


# ---------------------------------------------------------------------------
# Phase D: handle_request — SendMessage
# ---------------------------------------------------------------------------

class TestHandleRequestSendMessage:
    def test_basic_200_response(self):
        status, headers, body = _handle(
            "POST", "/message:send",
            body=_dummy_req("myapp.t"),
            invoke=_str_invoke,
            tool_names=["myapp.t"],
        )
        assert status == 200
        assert headers["Content-Type"] == "application/a2a+json"
        parsed = json.loads(body)
        assert "message" in parsed
        assert "task" not in parsed

    def test_invalid_json_body_400(self):
        status, _, body = _handle("POST", "/message:send", body=b"not-json")
        assert status == 400
        err = json.loads(body)
        assert err["error"]["code"] == "INVALID_ARGUMENT"

    def test_missing_message_400(self):
        body = json.dumps({}).encode()
        status, _, resp = _handle("POST", "/message:send", body=body)
        assert status == 400

    def test_content_type_on_success(self):
        status, headers, _ = _handle(
            "POST", "/message:send",
            body=_dummy_req("myapp.t"),
        )
        assert headers["Content-Type"] == "application/a2a+json"

    def test_no_task_in_response(self):
        _, _, body = _handle("POST", "/message:send", body=_dummy_req("myapp.t"))
        parsed = json.loads(body)
        assert "task" not in parsed

    def test_no_kind_in_response(self):
        _, _, body = _handle("POST", "/message:send", body=_dummy_req("myapp.t"))
        assert b'"kind"' not in body


# ---------------------------------------------------------------------------
# Phase G: handle_request — version negotiation
# ---------------------------------------------------------------------------

class TestHandleRequestVersionNegotiation:
    def test_valid_version_accepted(self):
        status, _, _ = _handle(
            "POST", "/message:send",
            headers={"A2A-Version": "1.0"},
            body=_dummy_req("myapp.t"),
        )
        assert status == 200

    def test_old_version_rejected_400(self):
        status, _, body = _handle(
            "POST", "/message:send",
            headers={"A2A-Version": "0.3"},
            body=_dummy_req("myapp.t"),
        )
        assert status == 400
        err = json.loads(body)
        assert err["error"]["code"] == "VERSION_NOT_SUPPORTED"

    def test_missing_version_accepted(self):
        status, _, _ = _handle(
            "POST", "/message:send",
            headers={},
            body=_dummy_req("myapp.t"),
        )
        assert status == 200


# ---------------------------------------------------------------------------
# Phase F: handle_request — bearer auth
# ---------------------------------------------------------------------------

class TestHandleRequestAuth:
    def test_no_validator_allows_all(self):
        status, _, _ = _handle(
            "POST", "/message:send",
            body=_dummy_req("myapp.t"),
            token_validator=None,
        )
        assert status == 200

    def test_valid_token_accepted(self):
        status, _, _ = _handle(
            "POST", "/message:send",
            headers={"Authorization": "Bearer correct"},
            body=_dummy_req("myapp.t"),
            token_validator=lambda t: t == "correct",
        )
        assert status == 200

    def test_missing_token_401(self):
        status, resp_headers, body = _handle(
            "POST", "/message:send",
            headers={},
            body=_dummy_req("myapp.t"),
            token_validator=lambda t: True,
        )
        assert status == 401
        assert "WWW-Authenticate" in resp_headers
        err = json.loads(body)
        assert err["error"]["code"] == "AUTHENTICATION_REQUIRED"

    def test_wrong_token_401(self):
        status, _, _ = _handle(
            "POST", "/message:send",
            headers={"Authorization": "Bearer wrong"},
            body=_dummy_req("myapp.t"),
            token_validator=lambda t: t == "correct",
        )
        assert status == 401

    def test_card_endpoint_bypasses_auth(self):
        """Well-known endpoint must not enforce auth."""
        cb = _card_bytes()
        status, _, _ = _handle(
            "GET", "/.well-known/agent-card.json",
            card_bytes=cb,
            token_validator=lambda t: False,  # would reject everything
        )
        assert status == 200


# ---------------------------------------------------------------------------
# Phase D: catch-all unsupported operations
# ---------------------------------------------------------------------------

class TestHandleRequestUnsupported:
    @pytest.mark.parametrize("method,path", [
        ("GET",  "/tasks/abc-123"),
        ("POST", "/tasks/abc-123:cancel"),
        ("GET",  "/tasks"),
        ("GET",  "/extendedAgentCard"),
        ("POST", "/message:stream"),
        ("GET",  "/tasks/abc-123/pushNotificationConfigs"),
    ])
    def test_deferred_operations_return_501(self, method, path):
        status, _, body = _handle(method, path)
        assert status == 501
        err = json.loads(body)
        assert err["error"]["code"] == "UNSUPPORTED_OPERATION"

    def test_unknown_path_501(self):
        status, _, _ = _handle("GET", "/completely/unknown")
        assert status == 501

    def test_unsupported_content_type_is_a2a_json(self):
        status, headers, _ = _handle("GET", "/tasks")
        assert headers["Content-Type"] == "application/a2a+json"


# ---------------------------------------------------------------------------
# A2AHttpServer integration (real HTTP requests over loopback)
# ---------------------------------------------------------------------------

@pytest.fixture
def running_server():
    """Start A2AHttpServer on a random port; yield base URL; stop after test."""
    config = _minimal_config(port=0)  # OS assigns port
    _, card_bytes_val = cache_agent_card(config, [])

    server = A2AHttpServer(
        config=config,
        invoke=_str_invoke,
        tool_names=["myapp.t"],
        tools=[],
    )
    thread = server.serve_in_thread()
    # Wait for the server to bind
    for _ in range(50):
        if server.port != 0:
            break
        time.sleep(0.05)
    base_url = f"http://127.0.0.1:{server.port}"
    yield base_url
    server.close()


class TestA2AHttpServerIntegration:
    def test_agent_card_get(self, running_server):
        with urllib.request.urlopen(f"{running_server}/.well-known/agent-card.json") as r:
            assert r.status == 200
            body = json.loads(r.read())
            assert "name" in body
            assert body["capabilities"]["streaming"] is False

    def test_send_message(self, running_server):
        req_body = _dummy_req("myapp.t")
        req = urllib.request.Request(
            f"{running_server}/message:send",
            data=req_body,
            headers={"Content-Type": "application/a2a+json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            assert r.status == 200
            body = json.loads(r.read())
            assert "message" in body
            assert "task" not in body

    def test_legacy_wellknown_404(self, running_server):
        try:
            urllib.request.urlopen(f"{running_server}/.well-known/agent.json")
            pytest.fail("Expected HTTP 404")
        except HTTPError as e:
            assert e.code == 404

    def test_unsupported_path_501(self, running_server):
        try:
            urllib.request.urlopen(f"{running_server}/tasks/some-id")
            pytest.fail("Expected HTTP 501")
        except HTTPError as e:
            assert e.code == 501

    def test_version_mismatch_400(self, running_server):
        req_body = _dummy_req("myapp.t")
        req = urllib.request.Request(
            f"{running_server}/message:send",
            data=req_body,
            headers={
                "Content-Type": "application/a2a+json",
                "A2A-Version": "0.3",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            pytest.fail("Expected HTTP 400")
        except HTTPError as e:
            assert e.code == 400
            body = json.loads(e.read())
            assert body["error"]["code"] == "VERSION_NOT_SUPPORTED"
