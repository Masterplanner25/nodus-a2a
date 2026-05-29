"""Phase C: SendMessage handler — tool dispatch, invocation, error packaging.

See docs/design/02-message-model.md §3-4 and docs/design/03-transport-http.md §7.

Dispatch strategy (resolving doc 02 §10 open question):
  Primary:  scan inbound parts for a DataPart containing {"tool": "<name>", "args": {…}}
  Fallback: if exactly one tool is registered, use it with {} args
  Failure:  error DataPart in the response Message (not an HTTP error code)

Tool invocation errors (unknown tool, exception) also return error DataPart
responses so the HTTP layer always emits 200 for a well-formed request.
Only ValidationError escapes to the transport layer (→ HTTP 400).
"""

from __future__ import annotations

import uuid
from typing import Callable

from .codec import make_response_message, validate_message
from .errors import ToolNotFoundError
from .message import DataPart, Message, Role, SendMessageRequest, TextPart


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def extract_tool_call(
    parts: tuple, tool_names: list[str]
) -> tuple[str, dict]:
    """Determine which tool to call and with what args from the inbound parts.

    Primary path: first DataPart whose ``.data`` is a dict with a ``"tool"`` key.
    Fallback path: exactly one tool registered → use it with empty args.

    Args:
        parts:      Inbound message parts (tuple of Part variants).
        tool_names: Names of available (non-deprecated) tools in registration order.

    Returns:
        (tool_name, args_dict)

    Raises:
        ToolNotFoundError: if dispatch fails (caller converts to error Message).
    """
    # Primary: explicit tool-call envelope in DataPart
    for part in parts:
        if isinstance(part, DataPart) and isinstance(part.data, dict):
            tool_key = part.data.get("tool")
            if tool_key is not None:
                tool_name = str(tool_key)
                if tool_name not in tool_names:
                    raise ToolNotFoundError(
                        f"Tool '{tool_name}' is not registered on this agent. "
                        f"Available tools: {tool_names or ['(none)']}"
                    )
                raw_args = part.data.get("args", {})
                args = raw_args if isinstance(raw_args, dict) else {}
                return tool_name, args

    # Fallback: single-tool agent — tool is unambiguous
    if len(tool_names) == 1:
        return tool_names[0], {}

    if len(tool_names) == 0:
        raise ToolNotFoundError("No tools are registered on this agent.")

    raise ToolNotFoundError(
        f"This agent has {len(tool_names)} tools. "
        "Send a DataPart with {\"tool\": \"<name>\", \"args\": {...}} "
        "to specify which tool to call."
    )


# ---------------------------------------------------------------------------
# Error packaging
# ---------------------------------------------------------------------------

def make_error_message(inbound: Message, exc: Exception) -> Message:
    """Wrap an exception as an error DataPart in a response Message.

    Error format (doc 02 §10):
        DataPart(data={"error": str(exc), "type": ExcClassName})
    """
    error_part = DataPart(
        data={"error": str(exc), "type": type(exc).__name__},
        media_type="application/json",
    )
    return Message(
        message_id=str(uuid.uuid4()),
        role=Role.AGENT,
        parts=(error_part,),
        context_id=inbound.context_id or str(uuid.uuid4()),
        task_id="",
    )


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handle_send_message(
    request: SendMessageRequest,
    invoke: Callable[[str, dict], object],
    tool_names: list[str],
) -> Message:
    """Core SendMessage handler.

    Args:
        request:    Decoded SendMessageRequest (already parsed from wire JSON).
        invoke:     Tool execution callable: ``invoke(name, args) -> result``.
                    Raises KeyError if the tool name is not found.
                    The A2A server wires this to ToolRegistry.invoke().
        tool_names: Ordered list of non-deprecated tool names available on
                    this agent (used for dispatch and single-tool fallback).

    Returns:
        A response Message — always. Success results in a TextPart, DataPart,
        or RawPart. Dispatch or invocation errors produce an error DataPart.
        The HTTP transport always returns 200 for a response from this function.

    Raises:
        ValidationError: if the inbound message is malformed (transport → HTTP 400).
    """
    validate_message(request.message)

    # Dispatch: may raise ToolNotFoundError (converted to error Message below)
    try:
        tool_name, args = extract_tool_call(request.message.parts, tool_names)
    except ToolNotFoundError as exc:
        return make_error_message(request.message, exc)

    # Invocation: any exception → error Message (not HTTP 500)
    try:
        result = invoke(tool_name, args)
    except KeyError:
        return make_error_message(
            request.message,
            ToolNotFoundError(f"Tool '{tool_name}' disappeared during invocation."),
        )
    except Exception as exc:  # noqa: BLE001
        return make_error_message(request.message, exc)

    return make_response_message(request.message, result)
