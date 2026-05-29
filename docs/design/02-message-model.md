# 02 — Message Model: Part Handling, Role, and Tool-Result Mapping

**Phase:** 1 (Design)
**Status:** Complete
**Depends on:** `00-decisions.md` (D1–D10), `01-adapter-mapping.md` (codec table, Part oneof confirmed)
**Bytecode impact:** None — BYTECODE_VERSION stays 4 (D2).

---

## 1. Overview

This doc defines the Python-side message model for nodus-a2a: the internal data
types for `Part`, `Message`, and `Role`; how those types map to and from the 1.0
wire format; and how a `std:tool` call result is packaged into a response `Message`.

The proto structures were fully verified in doc 01 §1.1. No re-audit needed here;
this doc relies on those findings.

---

## 2. Python Internal Types

### 2.1 Part variants

`Part` in proto is a `oneof content` with four named fields. Python represents this
as a proper tagged union — four separate frozen dataclasses with a type alias:

```python
# src/nodus_a2a/message.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Union

@dataclass(frozen=True)
class TextPart:
    text: str
    media_type: str = "text/plain"
    filename: str = ""
    metadata: dict = field(default_factory=dict)

@dataclass(frozen=True)
class RawPart:
    raw: bytes
    media_type: str = "application/octet-stream"
    filename: str = ""
    metadata: dict = field(default_factory=dict)

@dataclass(frozen=True)
class UrlPart:
    url: str
    media_type: str = ""
    filename: str = ""
    metadata: dict = field(default_factory=dict)

@dataclass(frozen=True)
class DataPart:
    data: object   # any JSON-serializable value (dict, list, str, int, float, bool, None)
    media_type: str = "application/json"
    filename: str = ""
    metadata: dict = field(default_factory=dict)

Part = Union[TextPart, RawPart, UrlPart, DataPart]
```

**Design rationale:**
- Four separate types rather than a single class with a discriminator field — Python
  `isinstance` dispatch is then both clear and exhaustive.
- The internal Python types do NOT have a `kind` field — that is the 0.3-era pattern.
  The variant is determined entirely by the Python class. (`no-kind-discriminator`
  standing assertion: this applies to the wire, but the internal model must not
  introduce a `kind` field either, or the codec will accidentally serialize it.)
- `metadata` is `dict` (not `frozen=True`-compatible by default — use
  `field(default_factory=dict)` and accept that the outer dataclass is frozen at
  the reference level, not the dict contents level).
- `data: object` accepts any JSON-serializable value; it maps to
  `google.protobuf.Value` on the wire (ProtoJSON: the value itself, not wrapped).

### 2.2 Role enum

```python
from enum import Enum

class Role(str, Enum):
    USER  = "ROLE_USER"   # client → server: inbound message
    AGENT = "ROLE_AGENT"  # server → client: response message
    UNSPECIFIED = "ROLE_UNSPECIFIED"  # proto default; treat as error on inbound
```

`Role` inherits `str` so it serializes directly with `json.dumps`. On the wire the
value is the proto enum name string: `"ROLE_USER"`, `"ROLE_AGENT"` (ProtoJSON enum
encoding: use the name, not the number).

### 2.3 Message

```python
@dataclass(frozen=True)
class Message:
    message_id: str              # required; UUID; set by message creator
    role: Role                   # required
    parts: tuple[Part, ...]      # required; at least one element
    context_id: str = ""         # optional; propagated from request in responses
    task_id: str = ""            # empty in v0.1 message-only responses (D5)
    metadata: dict = field(default_factory=dict)
    extensions: tuple[str, ...] = ()
    reference_task_ids: tuple[str, ...] = ()
```

**Required field enforcement** (Phase C implementation note): raise a 400-equivalent
error (`UnsupportedOperationError` or a validation error per spec §3.3.2) if inbound
`Message` is missing `message_id`, `role`, or `parts`, or if `parts` is empty.

### 2.4 SendMessageRequest (inbound, partial)

Only the fields the v0.1 handler reads:

```python
@dataclass(frozen=True)
class SendMessageRequest:
    message: Message                          # required
    configuration: SendMessageConfiguration  # optional; defaults apply
    tenant: str = ""                          # ignored in v0.1 (single-agent)
    metadata: dict = field(default_factory=dict)

@dataclass(frozen=True)
class SendMessageConfiguration:
    accepted_output_modes: tuple[str, ...] = ()
    return_immediately: bool = False          # ignored in v0.1 (message-only)
    history_length: int | None = None        # ignored in v0.1 (no task store)
```

`return_immediately` has no effect when the response is a `Message` (spec §3.6,
`SendMessageConfiguration.return_immediately` comment). The field is parsed and
stored but never consulted.

---

## 3. Tool-Result → Part Dispatch

### 3.1 Dispatch table

A `std:tool` call returns a Python value. The server wraps it in a `Part` using this
priority-ordered dispatch:

| Python type of result | Part variant | `media_type` default |
|-----------------------|--------------|----------------------|
| `str` | `TextPart` | `text/plain` |
| `bytes` | `RawPart` | `application/octet-stream` |
| `dict`, `list`, `int`, `float`, `bool`, `None` | `DataPart` | `application/json` |

The `UrlPart` variant is NOT used in automatic dispatch. It is reserved for future
explicit use (e.g., a tool return type sentinel `FileRef` in v0.2+). A tool returning
a URL string as a `str` maps to `TextPart`, not `UrlPart`.

### 3.2 `accepted_output_modes` handling

The client MAY send `configuration.accepted_output_modes` to indicate which MIME types
it can accept. v0.1 behavior: **ignore** the field. The dispatch table in §3.1 is
applied unconditionally. Transcoding based on `accepted_output_modes` is deferred to v0.2.

The field is parsed (not rejected), so the wire remains valid. The doc-05 deferral
table records this.

### 3.3 `DataPart.data` value encoding

`google.protobuf.Value` in ProtoJSON is the JSON value itself — no wrapper. So
`DataPart(data={"x": 1})` serializes to `{"data": {"x": 1}}` on the wire (after
camelCase key mapping). `DataPart(data=42)` → `{"data": 42}`. `DataPart(data=None)`
→ `{"data": null}`. The codec must use `json.dumps` value semantics, not wrap in
`{"value": ...}`.

### 3.4 `RawPart` base64 encoding

`bytes` in ProtoJSON are base64-encoded strings (standard base64 / RFC 4648 §4,
not URL-safe). The codec uses `base64.b64encode(raw).decode("ascii")` on serialization
and `base64.b64decode(s)` on deserialization.

---

## 4. Message Construction for Responses (Role = AGENT)

### 4.1 Algorithm

When a `SendMessage` request arrives, the handler:

1. Deserializes the inbound `Message` (role=USER, from the client).
2. Invokes the appropriate `std:tool` based on message content (Phase C detail).
3. Receives a Python result value.
4. Constructs the response `Message`:

```python
import uuid

def make_response_message(
    inbound: Message,
    tool_result: object,
) -> Message:
    part = dispatch_to_part(tool_result)   # §3.1 dispatch
    return Message(
        message_id=str(uuid.uuid4()),
        role=Role.AGENT,
        parts=(part,),
        context_id=inbound.context_id or str(uuid.uuid4()),
        task_id="",       # message-only: never set (D5)
        metadata={},
        extensions=(),
        reference_task_ids=(),
    )
```

### 4.2 Context propagation rules

- If inbound `Message.context_id` is non-empty: echo it in the response.
- If inbound `Message.context_id` is empty: generate a new UUID and use it.
  This is the first message of a new conversation context.
- `task_id` is ALWAYS empty in v0.1 responses. Setting it would imply a task was
  created, which contradicts D5. The `no-task-emitted` standing assertion covers
  this at the wire level; the `task_id=""` constraint here covers it at the
  Python level.

### 4.3 Multi-part responses

v0.1 always emits exactly one Part per response. Multi-part is legal per spec but
deferred. The `parts=(part,)` tuple enforces single-part for v0.1.

---

## 5. Message Parsing for Requests (Role = USER)

### 5.1 Wire → Python deserialization

The inbound body is a JSON object (`SendMessageRequest` shape, camelCase). The codec
(doc 01 §4) translates to snake_case and constructs Python objects.

Part deserialization: inspect the dict for exactly one of `text`, `raw`, `url`, `data`.

```python
def decode_part(d: dict) -> Part:
    if "text" in d:
        return TextPart(
            text=d["text"],
            media_type=d.get("mediaType", "text/plain"),
            filename=d.get("filename", ""),
            metadata=d.get("metadata", {}),
        )
    elif "raw" in d:
        return RawPart(
            raw=base64.b64decode(d["raw"]),
            media_type=d.get("mediaType", "application/octet-stream"),
            filename=d.get("filename", ""),
            metadata=d.get("metadata", {}),
        )
    elif "url" in d:
        return UrlPart(
            url=d["url"],
            media_type=d.get("mediaType", ""),
            filename=d.get("filename", ""),
            metadata=d.get("metadata", {}),
        )
    elif "data" in d:
        return DataPart(
            data=d["data"],
            media_type=d.get("mediaType", "application/json"),
            filename=d.get("filename", ""),
            metadata=d.get("metadata", {}),
        )
    else:
        raise ValueError("Part has no content field (expected text, raw, url, or data)")
```

**If multiple content fields are present:** take the first match in priority order
(text → raw → url → data) and ignore the rest. The spec does not address this case;
being lenient on input is correct here.

**If no content fields are present:** raise a validation error → HTTP 400.

### 5.2 Required field validation

```python
def validate_message(m: Message) -> None:
    if not m.message_id:
        raise ValidationError("message_id is required")
    if m.role == Role.UNSPECIFIED:
        raise ValidationError("role is required and must not be ROLE_UNSPECIFIED")
    if not m.parts:
        raise ValidationError("parts must contain at least one element")
```

`ValidationError` maps to an HTTP 400 with a JSON error body (doc 03 §3 defines the
error response format).

---

## 6. Wire Serialization (Python → JSON)

### 6.1 Message serialization

```python
def encode_message(m: Message) -> dict:
    d = {
        "messageId": m.message_id,
        "role": m.role.value,
        "parts": [encode_part(p) for p in m.parts],
    }
    if m.context_id:
        d["contextId"] = m.context_id
    if m.task_id:
        d["taskId"] = m.task_id          # always empty in v0.1 (D5)
    if m.metadata:
        d["metadata"] = m.metadata
    if m.extensions:
        d["extensions"] = list(m.extensions)
    if m.reference_task_ids:
        d["referenceTaskIds"] = list(m.reference_task_ids)
    return d
```

Optional fields are omitted when empty/falsy rather than set to null/empty-list.
ProtoJSON allows omitting optional fields; this keeps responses compact.

### 6.2 Part serialization

```python
def encode_part(p: Part) -> dict:
    if isinstance(p, TextPart):
        d = {"text": p.text}
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
```

### 6.3 SendMessageResponse serialization

Message-only: always use the `message` key of the `payload` oneof.

```python
def encode_response(m: Message) -> dict:
    return {"message": encode_message(m)}
```

The `task` key is NEVER set in v0.1. Any code path that would set `"task"` in the
response dict is a violation of the `no-task-emitted` standing assertion. The
assertion test checks that the serialized response never contains a top-level `"task"`
key.

---

## 7. Codec Name Mapping (Message/Part Supplement)

Doc 01 §4.2 has the canonical table. Message/Part-specific mappings repeated here for
clarity:

| Proto (snake_case) | Wire JSON (camelCase) | Notes |
|--------------------|-----------------------|-------|
| `message_id` | `messageId` | Required |
| `context_id` | `contextId` | Omit if empty |
| `task_id` | `taskId` | Always empty / omit in v0.1 |
| `reference_task_ids` | `referenceTaskIds` | Omit if empty |
| `media_type` | `mediaType` | On Part |
| `return_immediately` | `returnImmediately` | In SendMessageConfiguration |
| `accepted_output_modes` | `acceptedOutputModes` | In SendMessageConfiguration |
| `history_length` | `historyLength` | In SendMessageConfiguration |

ProtoJSON enum names: `role` on wire is the string enum name (`"ROLE_USER"`,
`"ROLE_AGENT"`), not an integer. Do not serialize as integer.

---

## 8. Bytecode Impact

None. All message handling runs in Python host code. No Nodus VM involvement in
Part dispatch, Message construction, or codec translation. BYTECODE_VERSION stays 4.

---

## 9. Standing Assertions Touched by This Doc

| Assertion | How this doc satisfies it |
|-----------|--------------------------|
| `no-task-emitted` | §6.3: response encodes only `{"message": ...}`; `"task"` key never set |
| `no-kind-discriminator` | §2.1: Python types have no `kind` field; §6.2: codec emits oneof key only |
| `codec-name-mapping` | §7: all Message/Part fields mapped through camelCase codec |

---

## 10. Open Questions for Phase C

- **Tool dispatch from Message content:** Phase C must decide how to determine *which*
  `std:tool` to invoke from a free-form inbound `Message`. The most tractable v0.1
  approach: require the client to send a `DataPart` whose `data` value is
  `{"tool": "<name>", "args": {...}}` — i.e., the message carries an explicit tool
  call envelope. Alternative: single-tool agents (registry has exactly one tool),
  which sidesteps dispatch entirely. Resolve in Phase C design before implementation.
- **Error Part format:** when a tool call raises an exception, what Part does the
  response `Message` contain? Propose: `DataPart(data={"error": str(exc)},
  media_type="application/json")` — structured, not a `TextPart`. Confirm in Phase C.
