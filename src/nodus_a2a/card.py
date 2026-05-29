"""Phase B: std:tool → AgentSkill / AgentCard projection.

See docs/design/01-adapter-mapping.md §2-3 and docs/design/04-discovery.md §2.
"""

from __future__ import annotations

import json

from .config import ServerConfig


def project_skill(entry: dict) -> dict:
    """Project one std:tool registry entry to an AgentSkill wire dict.

    Args:
        entry: Raw tool entry dict from ToolRegistry.list_tools(), with fields
               name, description, tags, deprecated, metadata, etc.
    Returns:
        camelCase AgentSkill wire dict ready for JSON serialisation.
    """
    name = entry["name"]
    tags: list[str] = entry.get("tags") or []
    if not tags:
        tags = [name]

    d: dict = {
        "id": name,
        "name": name,
        "description": entry["description"],
        "tags": tags,
    }

    # examples live in the tool's metadata dict (convention, not proto field)
    examples: list = (entry.get("metadata") or {}).get("examples", [])
    if examples:
        d["examples"] = list(examples)

    # inputModes / outputModes intentionally absent → inherit from AgentCard defaults
    return d


def build_agent_card(config: ServerConfig, tools: list[dict]) -> dict:
    """Assemble the AgentCard wire dict from server config and tool list.

    Deprecated tools are excluded from the skill list.
    Returns a camelCase wire-ready dict (not yet JSON-serialised).
    See docs/design/04-discovery.md §2.1 for the authoritative field mapping.
    """
    skills = [
        project_skill(t)
        for t in tools
        if not t.get("deprecated", False)
    ]

    card: dict = {
        "name": config.agent_name,
        "description": config.agent_description,
        "version": config.agent_version,
        "supportedInterfaces": [
            {
                "url": config.base_url,
                "protocolBinding": "HTTP+JSON",
                "tenant": "",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "securitySchemes": {
            "bearer": {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer",
                    "description": "Bearer token authentication",
                }
            }
        },
        "securityRequirements": [{"bearer": []}],
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": skills,
        "signatures": [],  # D8a: unsigned for v0.1
    }

    if config.provider_url or config.provider_org:
        card["provider"] = {
            "url": config.provider_url,
            "organization": config.provider_org,
        }
    if config.documentation_url:
        card["documentationUrl"] = config.documentation_url
    if config.icon_url:
        card["iconUrl"] = config.icon_url

    return card


def cache_agent_card(
    config: ServerConfig, tools: list[dict]
) -> tuple[dict, bytes]:
    """Build and serialise the Agent Card once at startup.

    Returns:
        (card_dict, card_bytes) — the dict for in-process use and the UTF-8
        JSON bytes for direct serving (no re-serialisation per request).
    """
    card = build_agent_card(config, tools)
    card_bytes = json.dumps(card, ensure_ascii=False).encode("utf-8")
    return card, card_bytes
