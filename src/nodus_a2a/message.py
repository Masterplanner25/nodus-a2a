from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class Role(str, Enum):
    UNSPECIFIED = "ROLE_UNSPECIFIED"
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


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
    data: object  # any JSON-serializable value
    media_type: str = "application/json"
    filename: str = ""
    metadata: dict = field(default_factory=dict)


Part = Union[TextPart, RawPart, UrlPart, DataPart]


@dataclass(frozen=True)
class Message:
    message_id: str
    role: Role
    parts: tuple
    context_id: str = ""
    task_id: str = ""
    metadata: dict = field(default_factory=dict)
    extensions: tuple = ()
    reference_task_ids: tuple = ()


@dataclass(frozen=True)
class SendMessageConfiguration:
    accepted_output_modes: tuple = ()
    return_immediately: bool = False
    history_length: int | None = None


@dataclass(frozen=True)
class SendMessageRequest:
    message: Message
    configuration: SendMessageConfiguration = field(
        default_factory=SendMessageConfiguration
    )
    tenant: str = ""
    metadata: dict = field(default_factory=dict)
