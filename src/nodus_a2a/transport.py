"""Phases D-G: HTTP+JSON/REST transport, bearer auth, A2A-Version negotiation.

Architecture: handle_request() is a pure function (method/path/headers/body →
status/headers/body). A2AHttpServer wraps stdlib ThreadingHTTPServer and closes
over handle_request(). This separation makes the transport logic testable without
a running HTTP server.

See docs/design/03-transport-http.md and docs/design/04-discovery.md.
"""

from __future__ import annotations

import http.server
import json
import logging
import threading
from typing import Callable

from .card import cache_agent_card
from .codec import (
    decode_send_message_request,
    encode_send_message_response,
)
from .config import ServerConfig
from .errors import (
    A2AError,
    AuthError,
    ParseError,
    UnsupportedOperationError,
    ValidationError,
    VersionNotSupportedError,
)
from .handler import handle_send_message

logger = logging.getLogger(__name__)

SUPPORTED_VERSION = "1.0"
CONTENT_TYPE = "application/a2a+json"


# ---------------------------------------------------------------------------
# Phase F: bearer auth
# ---------------------------------------------------------------------------

def extract_bearer_token(headers) -> str | None:
    """Extract the token from 'Authorization: Bearer <token>' header."""
    auth = headers.get("Authorization") or headers.get("authorization")
    if isinstance(auth, str) and auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return None


def validate_auth(
    token: str | None,
    validator: Callable[[str], bool] | None,
) -> None:
    """Enforce bearer auth if a validator is configured.

    No validator → dev mode, all requests allowed.
    Raises AuthError (→ HTTP 401) on missing or invalid token.
    """
    if validator is None:
        return
    if token is None:
        raise AuthError("Authorization header with Bearer token required")
    if not validator(token):
        raise AuthError("Invalid or expired bearer token")


# ---------------------------------------------------------------------------
# Phase G: A2A-Version negotiation
# ---------------------------------------------------------------------------

def negotiate_version(headers) -> None:
    """Enforce A2A-Version compatibility.

    Lenient on missing header (log warning, accept — doc 03 §4.2).
    Strict on mismatch: raise VersionNotSupportedError (→ HTTP 400).
    Match on Major.Minor only; patch differences accepted.
    """
    version = headers.get("A2A-Version") or headers.get("a2a-version")
    if version is None:
        logger.warning(
            "Request missing A2A-Version header; accepting in lenient mode. "
            "Clients should send A2A-Version: %s",
            SUPPORTED_VERSION,
        )
        return
    major_minor = ".".join(str(version).split(".")[:2])
    if major_minor != SUPPORTED_VERSION:
        raise VersionNotSupportedError(
            f"A2A version '{version}' is not supported. "
            f"This server supports {SUPPORTED_VERSION}."
        )


# ---------------------------------------------------------------------------
# Phase D/E: core request dispatcher (pure function — no HTTP server needed)
# ---------------------------------------------------------------------------

def handle_request(
    method: str,
    path: str,
    headers,
    body: bytes,
    *,
    card_bytes: bytes,
    invoke: Callable[[str, dict], object],
    tool_names: list[str],
    token_validator: Callable[[str], bool] | None,
) -> tuple[int, dict, bytes]:
    """Map one HTTP request to (status_code, response_headers, response_body).

    Pure function: no side effects beyond logging. Tests call this directly
    without starting an HTTP server.

    Routing table:
      GET  /.well-known/agent-card.json → 200 Agent Card (Phase E)
      GET  /.well-known/agent.json      → 404 (0.3-era path; no-legacy-wellknown)
      POST /message:send                → 200 SendMessage response (Phase D)
      *                                 → 501 UnsupportedOperationError (Phase D)
    """
    # Phase E: public Agent Card — no auth, no version check (pre-negotiation step)
    if method == "GET" and path == "/.well-known/agent-card.json":
        resp_headers = {
            "Content-Type": CONTENT_TYPE,
            "Cache-Control": "public, max-age=3600",
        }
        return 200, resp_headers, card_bytes

    # no-legacy-wellknown: 0.3-era path explicitly rejected (D4b assertion)
    if method == "GET" and path == "/.well-known/agent.json":
        err_body = json.dumps(
            {"error": {"code": "NOT_FOUND", "message": "Not found", "details": []}}
        ).encode("utf-8")
        return 404, {"Content-Type": CONTENT_TYPE}, err_body

    # Phase D: SendMessage
    if method == "POST" and path == "/message:send":
        try:
            negotiate_version(headers)
            token = extract_bearer_token(headers)
            validate_auth(token, token_validator)
            try:
                body_dict = json.loads(body) if body else {}
            except (json.JSONDecodeError, ValueError) as exc:
                raise ParseError(f"Invalid JSON body: {exc}") from exc
            request = decode_send_message_request(body_dict)
            response_msg = handle_send_message(request, invoke, tool_names)
            wire = encode_send_message_response(response_msg)
            resp_body = json.dumps(wire, ensure_ascii=False).encode("utf-8")
            return 200, {"Content-Type": CONTENT_TYPE}, resp_body
        except A2AError as exc:
            resp_body = json.dumps(exc.to_wire(), ensure_ascii=False).encode("utf-8")
            resp_headers: dict = {"Content-Type": CONTENT_TYPE}
            if exc.http_status == 401:
                resp_headers["WWW-Authenticate"] = "Bearer"
            return exc.http_status, resp_headers, resp_body

    # Phase D: catch-all — deferred operations return 501
    err = UnsupportedOperationError(
        f"Operation '{method} {path}' is not supported in nodus-a2a v0.1. "
        "See docs/design/05-deferred-features.md for the full deferral inventory."
    )
    resp_body = json.dumps(err.to_wire(), ensure_ascii=False).encode("utf-8")
    return 501, {"Content-Type": CONTENT_TYPE}, resp_body


# ---------------------------------------------------------------------------
# Phase D: HTTP server
# ---------------------------------------------------------------------------

class A2AHttpServer:
    """A2A server over stdlib ThreadingHTTPServer.

    Construction assembles the Agent Card cache and captures the tool invoker.
    Call serve() to block, or serve_in_thread() for background operation.
    Use close() to stop a running server.

    Args:
        config:      Server configuration (base_url, agent_name, port, auth, …).
        invoke:      Tool execution callable: invoke(name, args) → result.
                     Wired to ToolRegistry.invoke() in production use.
        tool_names:  Ordered list of non-deprecated tool names (for dispatch).
        tools:       Raw tool entry dicts from ToolRegistry.list_tools()
                     (used to build the AgentCard).
    """

    def __init__(
        self,
        config: ServerConfig,
        invoke: Callable[[str, dict], object],
        tool_names: list[str],
        tools: list[dict],
    ) -> None:
        self._config = config
        self._invoke = invoke
        self._tool_names = tool_names
        _, self._card_bytes = cache_agent_card(config, tools)
        self._httpd: http.server.HTTPServer | None = None
        self._closed = False

    @property
    def port(self) -> int:
        """Actual bound port (available after serve() has started)."""
        if self._httpd is not None:
            return self._httpd.server_address[1]
        return self._config.port

    @property
    def host(self) -> str:
        if self._httpd is not None:
            return self._httpd.server_address[0]
        return self._config.host

    def serve(self) -> None:
        """Bind the port and serve requests until close() is called. Blocks."""
        srv = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def _dispatch(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b""
                status, resp_headers, resp_body = handle_request(
                    method=method,
                    path=self.path,
                    headers=self.headers,
                    body=body,
                    card_bytes=srv._card_bytes,
                    invoke=srv._invoke,
                    tool_names=srv._tool_names,
                    token_validator=srv._config.token_validator,
                )
                self.send_response(status)
                for k, v in resp_headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            def do_POST(self) -> None:
                self._dispatch("POST")

            def do_GET(self) -> None:
                self._dispatch("GET")

            def log_message(self, fmt: str, *args) -> None:
                pass  # suppress per-request logs; use logger above for warnings

        self._httpd = http.server.ThreadingHTTPServer(
            (self._config.host, self._config.port), _Handler
        )
        self._httpd.serve_forever()

    def serve_in_thread(self) -> threading.Thread:
        """Start the server in a daemon thread. Returns the started thread."""
        t = threading.Thread(target=self.serve, daemon=True, name="nodus-a2a-http")
        t.start()
        return t

    def close(self) -> None:
        """Stop the server. Safe to call from any thread."""
        if not self._closed and self._httpd is not None:
            self._httpd.shutdown()
            self._closed = True
