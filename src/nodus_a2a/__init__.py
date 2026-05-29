"""nodus-a2a: A2A 1.0.0 (LF) protocol adapter for the Nodus scripting language.

Public API surface:
    Server:     A2AHttpServer, ServerConfig
    Messages:   Message, Role, TextPart, RawPart, UrlPart, DataPart
    Errors:     A2AError, VersionNotSupportedError, AuthError, UnsupportedOperationError
    Card:       build_agent_card, cache_agent_card, project_skill

All other symbols are internal implementation details and may change.
"""

__version__ = "0.1.0"

from .card import build_agent_card, cache_agent_card, project_skill
from .config import ServerConfig
from .errors import (
    A2AError,
    AuthError,
    ParseError,
    ToolNotFoundError,
    UnsupportedOperationError,
    ValidationError,
    VersionNotSupportedError,
)
from .message import DataPart, Message, Part, RawPart, Role, TextPart, UrlPart
from .transport import A2AHttpServer

__all__ = [
    "__version__",
    # Server
    "A2AHttpServer",
    "ServerConfig",
    # Messages
    "Message",
    "Role",
    "Part",
    "TextPart",
    "RawPart",
    "UrlPart",
    "DataPart",
    # Errors
    "A2AError",
    "VersionNotSupportedError",
    "AuthError",
    "ParseError",
    "ValidationError",
    "UnsupportedOperationError",
    "ToolNotFoundError",
    # Card
    "build_agent_card",
    "cache_agent_card",
    "project_skill",
]
