from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ServerConfig:
    base_url: str
    agent_name: str
    agent_description: str
    agent_version: str = "0.1.0"
    token_validator: Callable[[str], bool] | None = None
    provider_url: str = ""
    provider_org: str = ""
    documentation_url: str | None = None
    icon_url: str | None = None
    host: str = "0.0.0.0"
    port: int = 8080
