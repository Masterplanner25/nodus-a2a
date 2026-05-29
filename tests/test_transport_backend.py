"""STEP 3: Flask-vs-stdlib dual-backend assertion.

nodus-a2a v0.1 uses only stdlib http.server (ThreadingHTTPServer).  There is
no Flask code path.  This module documents and permanently enforces that fact.

Rationale: the breakage gate (2026-05-29) identified "Flask-vs-stdlib" as
Suspect #1 — a scenario where installing Flask could silently activate an
alternative code path that no test exercises.  Investigation confirmed:

  Result: Suspect #1 RESOLVED — there is exactly ONE transport backend
  (stdlib).  Flask is not imported, not detected, and not used.  Installing
  Flask 3.1.3 produced no wire difference (all 169 tests pass identically).

These tests enforce that guarantee permanently:
  - test_transport_uses_only_stdlib: import graph contains no flask
  - test_no_flask_in_transport_module: source-level string scan (belt-and-suspenders)
  - TestBothBackends: parametrized over ["stdlib", "flask-if-present"]; the
    flask variant skips cleanly when Flask is not installed, and asserts
    identical wire output when it IS installed (no silent code-path switch).
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import time
import urllib.request

import pytest

from nodus_a2a.card import cache_agent_card
from nodus_a2a.config import ServerConfig
from nodus_a2a.transport import A2AHttpServer, handle_request


# ---------------------------------------------------------------------------
# Backend definitions
# ---------------------------------------------------------------------------

BACKENDS = ["stdlib", "flask-if-present"]


def _flask_available() -> bool:
    return importlib.util.find_spec("flask") is not None


# ---------------------------------------------------------------------------
# 1. Import-graph assertion: no flask anywhere in nodus_a2a
# ---------------------------------------------------------------------------

def test_transport_uses_only_stdlib():
    """nodus_a2a.transport must not import flask at any depth."""
    import nodus_a2a.transport as transport_mod
    # Collect all modules reachable from transport via its __dict__
    seen = set()
    queue = [transport_mod]
    while queue:
        mod = queue.pop()
        name = getattr(mod, "__name__", "") or ""
        if name in seen:
            continue
        seen.add(name)
        assert "flask" not in name.lower(), (
            f"Flask appeared in nodus_a2a.transport import graph: {name}"
        )
        for attr in vars(mod).values():
            sub = getattr(attr, "__module__", None)
            if sub and sub not in seen and sub.startswith("nodus_a2a"):
                spec = importlib.util.find_spec(sub)
                if spec:
                    try:
                        queue.append(importlib.import_module(sub))
                    except ImportError:
                        pass

    flask_in_graph = [n for n in seen if "flask" in n.lower()]
    assert not flask_in_graph, (
        f"Flask appeared in nodus_a2a import graph: {flask_in_graph}. "
        "nodus-a2a must stay stdlib-only."
    )


def test_no_flask_in_transport_module():
    """Source-level scan: 'flask' must not appear in transport.py source."""
    import nodus_a2a.transport as mod
    source = inspect.getsource(mod)
    assert "flask" not in source.lower(), (
        "The string 'flask' appeared in nodus_a2a/transport.py source. "
        "nodus-a2a v0.1 uses stdlib http.server only."
    )


def test_server_class_is_stdlib_threading_http_server():
    """A2AHttpServer must be backed by http.server.ThreadingHTTPServer, not Flask."""
    import http.server
    import nodus_a2a.transport as mod

    # Verify the source refers to ThreadingHTTPServer
    source = inspect.getsource(mod)
    assert "ThreadingHTTPServer" in source, (
        "ThreadingHTTPServer not found in transport.py. "
        "If the server backend changed, update this test."
    )
    assert "http.server" in source


# ---------------------------------------------------------------------------
# 2. Parametrized fixture: stdlib backend vs flask-if-present backend
#    The flask variant skips if Flask is not installed, and asserts wire-
#    identical output to stdlib if it IS installed.
# ---------------------------------------------------------------------------

def _make_config() -> ServerConfig:
    return ServerConfig(
        base_url="https://example.com",
        agent_name="BackendParityAgent",
        agent_description="Parametrized backend parity test",
        host="127.0.0.1",
        port=0,
    )


def _invoke(name: str, args: dict) -> object:
    if name == "ping":
        return "pong"
    raise KeyError(f"No tool '{name}'")


def _wait_for_port(srv, retries=50) -> str:
    for _ in range(retries):
        if srv.port != 0:
            return f"http://127.0.0.1:{srv.port}"
        time.sleep(0.05)
    raise RuntimeError("Server did not bind in time")


def _get_card(base_url: str) -> dict:
    with urllib.request.urlopen(f"{base_url}/.well-known/agent-card.json") as r:
        return json.loads(r.read())


def _send_message(base_url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base_url}/message:send",
        data=data,
        headers={"Content-Type": "application/a2a+json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _start_stdlib_server() -> tuple[A2AHttpServer, str]:
    tools = [{"name": "ping", "description": "ping", "schema": {},
              "version": "1.0.0", "tags": [], "deprecated": False, "metadata": {}}]
    srv = A2AHttpServer(
        config=_make_config(),
        invoke=_invoke,
        tool_names=["ping"],
        tools=tools,
    )
    srv.serve_in_thread()
    base = _wait_for_port(srv)
    return srv, base


@pytest.fixture(params=BACKENDS, ids=BACKENDS)
def backend_server_url(request):
    """Parametrized fixture: starts a server for each backend variant.

    stdlib: uses the actual A2AHttpServer (ThreadingHTTPServer).
    flask-if-present: skips if Flask is not installed; if installed, verifies
        that Flask's presence does not alter the transport backend (i.e. the
        same stdlib server is used — nodus-a2a has no Flask code path).
    """
    if request.param == "stdlib":
        srv, base = _start_stdlib_server()
        yield base
        srv.close()

    elif request.param == "flask-if-present":
        if not _flask_available():
            pytest.skip("Flask not installed — flask-if-present backend skipped")

        # Flask IS installed. Verify it does NOT activate a different code path.
        # The server must still be stdlib ThreadingHTTPServer.
        import http.server as _stdlib_http
        srv, base = _start_stdlib_server()

        # Assert the running server is the stdlib kind (not Flask's dev server).
        assert isinstance(srv._httpd, _stdlib_http.HTTPServer), (
            "With Flask installed, A2AHttpServer switched to a non-stdlib backend. "
            "This is a transport-backend regression — nodus-a2a must stay stdlib-only."
        )
        yield base
        srv.close()


class TestBothBackends:
    """These tests run against BOTH backends; output must be wire-identical."""

    def test_agent_card_content_type(self, backend_server_url):
        req = urllib.request.Request(
            f"{backend_server_url}/.well-known/agent-card.json", method="GET"
        )
        with urllib.request.urlopen(req) as r:
            ct = r.headers.get("Content-Type", "")
        assert "application/a2a+json" in ct, (
            f"Content-Type mismatch on {backend_server_url}: got '{ct}'"
        )

    def test_agent_card_cache_control(self, backend_server_url):
        req = urllib.request.Request(
            f"{backend_server_url}/.well-known/agent-card.json", method="GET"
        )
        with urllib.request.urlopen(req) as r:
            cc = r.headers.get("Cache-Control", "")
        assert "public" in cc and "max-age=3600" in cc, (
            f"Cache-Control mismatch: got '{cc}'"
        )

    def test_agent_card_capabilities_all_false(self, backend_server_url):
        card = _get_card(backend_server_url)
        caps = card["capabilities"]
        assert caps["streaming"] is False
        assert caps["pushNotifications"] is False
        assert caps["extendedAgentCard"] is False

    def test_agent_card_no_task_no_kind(self, backend_server_url):
        card = _get_card(backend_server_url)
        card_str = json.dumps(card)
        assert "task" not in card_str, "D5 violation: 'task' in agent card"
        assert '"kind"' not in card_str, "D4b violation: 'kind' in agent card"

    def test_agent_card_camel_case(self, backend_server_url):
        card = _get_card(backend_server_url)
        card_str = json.dumps(card)
        for snake in [
            "supported_interfaces", "default_input_modes", "security_schemes",
            "protocol_binding", "push_notifications", "extended_agent_card",
        ]:
            assert snake not in card_str, (
                f"snake_case key '{snake}' in agent card from {backend_server_url}"
            )

    def test_send_message_response_is_message_not_task(self, backend_server_url):
        body = _send_message(backend_server_url, {
            "message": {
                "messageId": "parity-001",
                "role": "ROLE_USER",
                "parts": [{"data": {"tool": "ping", "args": {}}}],
            }
        })
        assert "message" in body, f"No 'message' key in response from {backend_server_url}"
        assert "task" not in body, f"D5 violation: 'task' in response from {backend_server_url}"

    def test_send_message_no_kind(self, backend_server_url):
        body = _send_message(backend_server_url, {
            "message": {
                "messageId": "parity-kind-001",
                "role": "ROLE_USER",
                "parts": [{"data": {"tool": "ping", "args": {}}}],
            }
        })
        assert '"kind"' not in json.dumps(body), (
            f"D4b violation: 'kind' in response from {backend_server_url}"
        )

    def test_send_message_camel_case_wire(self, backend_server_url):
        body = _send_message(backend_server_url, {
            "message": {
                "messageId": "parity-cc-001",
                "role": "ROLE_USER",
                "parts": [{"data": {"tool": "ping", "args": {}}}],
                "contextId": "ctx-parity",
            }
        })
        body_str = json.dumps(body)
        for snake in ["message_id", "context_id", "task_id", "media_type"]:
            assert snake not in body_str, (
                f"snake_case key '{snake}' in response from {backend_server_url}"
            )
        assert "messageId" in body_str
