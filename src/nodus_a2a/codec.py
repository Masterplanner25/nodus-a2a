from __future__ import annotations

import base64
import re
import uuid

from .errors import ParseError, ValidationError
from .message import (
    DataPart,
    Message,
    Part,
    RawPart,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    TextPart,
    UrlPart,
)

# ---------------------------------------------------------------------------
# Name conversion: proto snake_case <-> wire camelCase
# ---------------------------------------------------------------------------

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _camel_to_snake(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


# ---------------------------------------------------------------------------
# Part encoding / decoding
# ---------------------------------------------------------------------------

def encode_part(p: Part) -> dict:
    if isinstance(p, TextPart):
        d: dict = {"text": p.text}
    elif isinstance(p, RawPart):
        d = {"raw": base64.b64encode(p.raw).decode("ascii")}
    elif isinstance(p, UrlPart):
        d = {"url": p.url}
    elif isinstance(p, DataPart):
        d = {"data": p.data}
    else:
        raise TypeError(f"Unknown Part type: {type(p)}")
    if p.media_type:
        d["mediaType"] = p.media_type
    if p.filename:
        d["filename"] = p.filename
    if p.metadata:
        d["metadata"] = p.metadata
    return d


def decode_part(d: dict) -> Part:
    if not isinstance(d, dict):
        raise ParseError(f"Part must be a JSON object; got {type(d).__name__}")
    meta = d.get("metadata", {})
    media_type = d.get("mediaType", "")
    filename = d.get("filename", "")
    if "text" in d:
        return TextPart(
            text=d["text"],
            media_type=media_type or "text/plain",
            filename=filename,
            metadata=meta,
        )
    if "raw" in d:
        try:
            raw_bytes = base64.b64decode(d["raw"])
        except Exception as exc:
            raise ParseError(f"Part.raw is not valid base64: {exc}") from exc
        return RawPart(
            raw=raw_bytes,
            media_type=media_type or "application/octet-stream",
            filename=filename,
            metadata=meta,
        )
    if "url" in d:
        return UrlPart(
            url=d["url"],
            media_type=media_type,
            filename=filename,
            metadata=meta,
        )
    if "data" in d:
        return DataPart(
            data=d["data"],
            media_type=media_type or "application/json",
            filename=filename,
            metadata=meta,
        )
    raise ParseError(
        "Part has no content field; expected one of: text, raw, url, data"
    )


# ---------------------------------------------------------------------------
# Message encoding / decoding
# ---------------------------------------------------------------------------

def encode_message(m: Message) -> dict:
    d: dict = {
        "messageId": m.message_id,
        "role": m.role.value if isinstance(m.role, Role) else m.role,
        "parts": [encode_part(p) for p in m.parts],
    }
    if m.context_id:
        d["contextId"] = m.context_id
    if m.task_id:
        d["taskId"] = m.task_id
    if m.metadata:
        d["metadata"] = m.metadata
    if m.extensions:
        d["extensions"] = list(m.extensions)
    if m.reference_task_ids:
        d["referenceTaskIds"] = list(m.reference_task_ids)
    return d


def decode_message(d: dict) -> Message:
    if not isinstance(d, dict):
        raise ParseError(f"Message must be a JSON object; got {type(d).__name__}")
    message_id = d.get("messageId", "")
    role_str = d.get("role", "ROLE_UNSPECIFIED")
    parts_raw = d.get("parts", [])
    if not isinstance(parts_raw, list):
        raise ParseError("Message.parts must be a JSON array")
    parts = tuple(decode_part(p) for p in parts_raw)
    try:
        role = Role(role_str)
    except ValueError:
        role = Role.UNSPECIFIED
    return Message(
        message_id=message_id,
        role=role,
        parts=parts,
        context_id=d.get("contextId", ""),
        task_id=d.get("taskId", ""),
        metadata=d.get("metadata", {}),
        extensions=tuple(d.get("extensions", [])),
        reference_task_ids=tuple(d.get("referenceTaskIds", [])),
    )


def validate_message(m: Message) -> None:
    if not m.message_id:
        raise ValidationError("message_id is required")
    if m.role == Role.UNSPECIFIED:
        raise ValidationError("role is required and must not be ROLE_UNSPECIFIED")
    if not m.parts:
        raise ValidationError("parts must contain at least one element")


# ---------------------------------------------------------------------------
# SendMessageRequest decoding
# ---------------------------------------------------------------------------

def decode_send_message_request(d: dict) -> SendMessageRequest:
    if not isinstance(d, dict):
        raise ParseError(
            f"SendMessageRequest must be a JSON object; got {type(d).__name__}"
        )
    message_raw = d.get("message")
    if message_raw is None:
        raise ParseError("SendMessageRequest.message is required")
    message = decode_message(message_raw)
    conf_raw = d.get("configuration", {})
    configuration = _decode_configuration(conf_raw)
    return SendMessageRequest(
        message=message,
        configuration=configuration,
        tenant=d.get("tenant", ""),
        metadata=d.get("metadata", {}),
    )


def _decode_configuration(d: dict) -> SendMessageConfiguration:
    if not isinstance(d, dict):
        return SendMessageConfiguration()
    modes_raw = d.get("acceptedOutputModes", [])
    accepted_output_modes = tuple(modes_raw) if isinstance(modes_raw, list) else ()
    return SendMessageConfiguration(
        accepted_output_modes=accepted_output_modes,
        return_immediately=bool(d.get("returnImmediately", False)),
        history_length=d.get("historyLength"),
    )


# ---------------------------------------------------------------------------
# SendMessageResponse encoding (message-only — D5)
# ---------------------------------------------------------------------------

def encode_send_message_response(m: Message) -> dict:
    return {"message": encode_message(m)}


# ---------------------------------------------------------------------------
# Tool-result → Part dispatch (doc 02 §3.1)
# ---------------------------------------------------------------------------

def result_to_part(result: object) -> Part:
    if isinstance(result, str):
        return TextPart(text=result)
    if isinstance(result, bytes):
        return RawPart(raw=result)
    return DataPart(data=result)


# ---------------------------------------------------------------------------
# Response Message construction (doc 02 §4)
# ---------------------------------------------------------------------------

def make_response_message(inbound: Message, tool_result: object) -> Message:
    part = result_to_part(tool_result)
    return Message(
        message_id=str(uuid.uuid4()),
        role=Role.AGENT,
        parts=(part,),
        context_id=inbound.context_id or str(uuid.uuid4()),
        task_id="",
        metadata={},
        extensions=(),
        reference_task_ids=(),
    )
