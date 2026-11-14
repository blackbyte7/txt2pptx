"""MCP server tests using the SDK's in-process client."""

import base64

import pytest
from mcp import Client
from pydantic import SecretStr

from txt2pptx import pipeline as pipeline_module
from txt2pptx.mcp_server import _transport_security, create_server
from txt2pptx.pipeline import PresentationService
from txt2pptx.schemas import PresentationOutline

pytestmark = pytest.mark.anyio


async def test_tools_listed_without_llm_tool(service):
    async with Client(create_server(service)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"list_templates", "create_presentation", "analyze_outline", "export_presentation"}
    assert tools["list_templates"].annotations.read_only_hint is True
    assert "outline" in tools["create_presentation"].input_schema["properties"]


async def test_llm_tool_registered_when_key_configured(settings):
    settings.anthropic_api_key = SecretStr("ak-test")
    async with Client(create_server(PresentationService(settings))) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "generate_presentation" in names


async def test_create_presentation_and_read_resource(service, sample_outline):
    async with Client(create_server(service)) as client:
        result = await client.call_tool(
            "create_presentation",
            {"outline": sample_outline, "template": "creative", "export_formats": ["html"]},
        )
        assert not result.is_error, result.content
        data = result.structured_content
        assert data["slide_count"] == 5
        assert data["template"] == "creative"
        assert data["exports"]["html"]
        resource = await client.read_resource(data["resource_uri"])
    blob = resource.contents[0].blob
    assert base64.b64decode(blob)[:2] == b"PK"  # .pptx is a zip


async def test_create_presentation_errors(service, sample_outline):
    async with Client(create_server(service)) as client:
        bad_template = await client.call_tool(
            "create_presentation", {"outline": sample_outline, "template": "x"}
        )
        bad_outline = await client.call_tool("create_presentation", {"outline": {"slides": []}})
    assert bad_template.is_error and "Unknown template" in bad_template.content[0].text
    assert bad_outline.is_error


async def test_list_templates_and_analyze(service, sample_outline):
    async with Client(create_server(service)) as client:
        templates = await client.call_tool("list_templates", {})
        sample_outline["slides"].pop(0)
        analysis = await client.call_tool("analyze_outline", {"outline": sample_outline})
    names = {t["name"] for t in templates.structured_content["result"]}
    assert {"professional", "dark"} <= names
    assert any("title slide" in s for s in analysis.structured_content["suggestions"])


async def test_export_presentation_rejects_foreign_files(service, tmp_path):
    outside = tmp_path / "elsewhere.pptx"
    outside.write_bytes(b"PK")
    async with Client(create_server(service)) as client:
        result = await client.call_tool("export_presentation", {"file": str(outside), "formats": ["html"]})
    assert result.is_error


async def test_schema_and_template_resources(service):
    async with Client(create_server(service)) as client:
        schema = await client.read_resource("txt2pptx://schema/outline")
        template = await client.read_resource("txt2pptx://templates/dark")
        prompts = await client.list_prompts()
    assert '"slides"' in schema.contents[0].text
    assert '"#111827"' in template.contents[0].text
    assert [p.name for p in prompts.prompts] == ["create_deck"]


async def test_generate_presentation_tool(settings, monkeypatch, fake_llm_factory, sample_outline):
    settings.openai_api_key = SecretStr("sk-test")
    fake = fake_llm_factory({PresentationOutline: PresentationOutline.model_validate(sample_outline)})
    monkeypatch.setattr(pipeline_module, "create_chat_model", lambda *a, **k: fake)
    async with Client(create_server(PresentationService(settings))) as client:
        result = await client.call_tool(
            "generate_presentation", {"content": "Notes about AI testing", "max_slides": 5}
        )
    assert not result.is_error, result.content
    assert result.structured_content["slide_count"] == 5


def test_transport_security(settings):
    assert _transport_security(settings, "127.0.0.1") is None
    sec = _transport_security(settings, "0.0.0.0")
    assert sec.enable_dns_rebinding_protection and "localhost:*" in sec.allowed_hosts
    settings.mcp_allowed_hosts = ["decks.example.com"]
    assert "decks.example.com" in _transport_security(settings, "0.0.0.0").allowed_hosts
    settings.mcp_allowed_hosts = ["*"]
    assert _transport_security(settings, "0.0.0.0").enable_dns_rebinding_protection is False
