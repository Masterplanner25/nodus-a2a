"""Tests for Phase B: AgentCard assembly and AgentSkill projection."""

from __future__ import annotations

import json

import pytest

from nodus_a2a.card import build_agent_card, cache_agent_card, project_skill
from nodus_a2a.config import ServerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_config(**overrides) -> ServerConfig:
    defaults = dict(
        base_url="https://example.com",
        agent_name="Test Agent",
        agent_description="An agent for testing",
        agent_version="0.1.0",
    )
    defaults.update(overrides)
    return ServerConfig(**defaults)


def _tool(name="myapp.search", desc="Search the web", **kw) -> dict:
    entry = {
        "name": name,
        "description": desc,
        "schema": {},
        "version": "1.0.0",
        "tags": kw.pop("tags", []),
        "deprecated": kw.pop("deprecated", False),
        "metadata": kw.pop("metadata", {}),
    }
    entry.update(kw)
    return entry


# ---------------------------------------------------------------------------
# project_skill
# ---------------------------------------------------------------------------

class TestProjectSkill:
    def test_basic_projection(self):
        entry = _tool("myapp.search", "Search the web", tags=["search", "web"])
        skill = project_skill(entry)
        assert skill["id"] == "myapp.search"
        assert skill["name"] == "myapp.search"
        assert skill["description"] == "Search the web"
        assert skill["tags"] == ["search", "web"]

    def test_fallback_tags_when_empty(self):
        entry = _tool("myapp.calc", "Calculate things", tags=[])
        skill = project_skill(entry)
        assert skill["tags"] == ["myapp.calc"]

    def test_fallback_tags_when_missing(self):
        entry = {"name": "myapp.x", "description": "Desc"}
        skill = project_skill(entry)
        assert skill["tags"] == ["myapp.x"]

    def test_examples_from_metadata(self):
        entry = _tool(
            metadata={"examples": ["example one", "example two"]}
        )
        skill = project_skill(entry)
        assert skill["examples"] == ["example one", "example two"]

    def test_no_examples_when_absent(self):
        skill = project_skill(_tool())
        assert "examples" not in skill

    def test_no_input_output_modes(self):
        # inputModes / outputModes must be absent; they inherit from AgentCard
        skill = project_skill(_tool())
        assert "inputModes" not in skill
        assert "outputModes" not in skill

    def test_no_kind_field(self):
        skill = project_skill(_tool())
        assert "kind" not in skill

    def test_no_schema_or_handler_leaked(self):
        entry = _tool()
        entry["handler"] = lambda x: x
        skill = project_skill(entry)
        assert "handler" not in skill
        assert "schema" not in skill


# ---------------------------------------------------------------------------
# build_agent_card
# ---------------------------------------------------------------------------

class TestBuildAgentCard:
    def test_required_fields_present(self):
        card = build_agent_card(_minimal_config(), [])
        for field in (
            "name", "description", "version", "supportedInterfaces",
            "capabilities", "defaultInputModes", "defaultOutputModes",
            "skills", "securitySchemes", "securityRequirements",
        ):
            assert field in card, f"Required field '{field}' missing from card"

    def test_name_description_version(self):
        config = _minimal_config(
            agent_name="My Agent",
            agent_description="Does stuff",
            agent_version="0.2.0",
        )
        card = build_agent_card(config, [])
        assert card["name"] == "My Agent"
        assert card["description"] == "Does stuff"
        assert card["version"] == "0.2.0"

    def test_supported_interface_shape(self):
        config = _minimal_config(base_url="https://agent.example.com")
        card = build_agent_card(config, [])
        ifaces = card["supportedInterfaces"]
        assert len(ifaces) == 1
        iface = ifaces[0]
        assert iface["url"] == "https://agent.example.com"
        assert iface["protocolBinding"] == "HTTP+JSON"
        assert iface["protocolVersion"] == "1.0"
        assert iface["tenant"] == ""

    def test_capabilities_all_false(self):
        card = build_agent_card(_minimal_config(), [])
        caps = card["capabilities"]
        assert caps["streaming"] is False
        assert caps["pushNotifications"] is False
        assert caps["extendedAgentCard"] is False

    def test_bearer_security_scheme(self):
        card = build_agent_card(_minimal_config(), [])
        schemes = card["securitySchemes"]
        assert "bearer" in schemes
        bearer = schemes["bearer"]
        assert "httpAuthSecurityScheme" in bearer
        assert bearer["httpAuthSecurityScheme"]["scheme"] == "Bearer"

    def test_security_requirements(self):
        card = build_agent_card(_minimal_config(), [])
        reqs = card["securityRequirements"]
        assert reqs == [{"bearer": []}]

    def test_default_modes(self):
        card = build_agent_card(_minimal_config(), [])
        assert "text/plain" in card["defaultInputModes"]
        assert "application/json" in card["defaultInputModes"]
        assert "text/plain" in card["defaultOutputModes"]
        assert "application/json" in card["defaultOutputModes"]

    def test_skills_projected_from_tools(self):
        tools = [
            _tool("myapp.a", "Tool A", tags=["alpha"]),
            _tool("myapp.b", "Tool B", tags=["beta"]),
        ]
        card = build_agent_card(_minimal_config(), tools)
        assert len(card["skills"]) == 2
        ids = {s["id"] for s in card["skills"]}
        assert ids == {"myapp.a", "myapp.b"}

    def test_deprecated_tools_excluded(self):
        tools = [
            _tool("myapp.active", "Active tool"),
            _tool("myapp.old", "Old tool", deprecated=True),
        ]
        card = build_agent_card(_minimal_config(), tools)
        ids = {s["id"] for s in card["skills"]}
        assert "myapp.active" in ids
        assert "myapp.old" not in ids

    def test_signatures_empty_list(self):
        card = build_agent_card(_minimal_config(), [])
        assert card["signatures"] == []

    def test_provider_included_when_set(self):
        config = _minimal_config(
            provider_url="https://example.com", provider_org="ACME Corp"
        )
        card = build_agent_card(config, [])
        assert "provider" in card
        assert card["provider"]["url"] == "https://example.com"
        assert card["provider"]["organization"] == "ACME Corp"

    def test_provider_omitted_when_absent(self):
        card = build_agent_card(_minimal_config(), [])
        assert "provider" not in card

    def test_documentation_url_included(self):
        config = _minimal_config(documentation_url="https://docs.example.com")
        card = build_agent_card(config, [])
        assert card["documentationUrl"] == "https://docs.example.com"

    def test_documentation_url_omitted_when_absent(self):
        card = build_agent_card(_minimal_config(), [])
        assert "documentationUrl" not in card

    def test_no_snake_case_keys(self):
        tools = [_tool("myapp.x", "X", tags=["x"])]
        card = build_agent_card(_minimal_config(), tools)
        card_str = json.dumps(card)
        SNAKE_PATTERNS = [
            "protocol_binding", "protocol_version", "security_schemes",
            "security_requirements", "default_input_modes", "default_output_modes",
            "supported_interfaces", "extended_agent_card", "push_notifications",
            "http_auth_security_scheme", "input_modes", "output_modes",
        ]
        for pattern in SNAKE_PATTERNS:
            assert pattern not in card_str, (
                f"Snake_case key '{pattern}' found in serialised card"
            )

    def test_no_kind_field(self):
        card_str = json.dumps(build_agent_card(_minimal_config(), [_tool()]))
        assert '"kind"' not in card_str


# ---------------------------------------------------------------------------
# cache_agent_card
# ---------------------------------------------------------------------------

class TestCacheAgentCard:
    def test_returns_dict_and_bytes(self):
        card_dict, card_bytes = cache_agent_card(_minimal_config(), [])
        assert isinstance(card_dict, dict)
        assert isinstance(card_bytes, bytes)

    def test_bytes_is_valid_json(self):
        _, card_bytes = cache_agent_card(_minimal_config(), [])
        parsed = json.loads(card_bytes.decode("utf-8"))
        assert "name" in parsed
        assert "capabilities" in parsed

    def test_dict_and_bytes_consistent(self):
        card_dict, card_bytes = cache_agent_card(_minimal_config(), [_tool()])
        from_bytes = json.loads(card_bytes.decode("utf-8"))
        assert card_dict == from_bytes
