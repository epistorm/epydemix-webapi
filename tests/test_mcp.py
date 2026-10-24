"""Tests for the Model Context Protocol (MCP) server mounted at /mcp.

The streamable HTTP session manager is initialized in the FastAPI lifespan,
so tests must drive a ``TestClient`` opened as a context manager. We use a
module-scoped fixture so the lifespan starts once and the session manager
stays valid across all MCP tests in this file.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

EXPECTED_TOOLS = {
    "run_simulation",
    "list_populations",
    "get_population",
    "get_population_contacts",
    "list_model_presets",
    "health_check",
}


@pytest.fixture(scope="module")
def mcp_client():
    """Start the MCP transport once and close it after this module's tests."""
    with TestClient(app) as c:
        yield c


def _initialize(client: TestClient) -> None:
    """Complete a session-free handshake and require an empty 202 notification response."""
    r = client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "epydemix-tests", "version": "0"},
            },
        },
    )
    assert r.status_code == 200, r.text
    assert "mcp-session-id" not in r.headers
    notification = client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notification.status_code == 202
    assert notification.content == b""


def test_mcp_lists_expected_tools_and_excludes_cache_status(mcp_client):
    """Tool discovery exposes the public API tools and hides the internal cache endpoint."""
    _initialize(mcp_client)
    r = mcp_client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert r.status_code == 200
    tools = {t["name"] for t in r.json()["result"]["tools"]}
    assert tools == EXPECTED_TOOLS
    assert "get_population_cache_status" not in tools


def test_mcp_health_check_round_trip(mcp_client):
    """A tools/call for health_check via MCP returns the same payload as GET /health."""
    http_health = mcp_client.get("/api/v1/health").json()

    _initialize(mcp_client)
    r = mcp_client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "health_check", "arguments": {}},
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    mcp_health = json.loads(result["content"][0]["text"])
    assert mcp_health == http_health


def test_root_link_header_advertises_mcp(client):
    """The root response advertises /mcp so clients can discover the tool endpoint."""
    r = client.get("/")
    assert r.status_code == 200
    link = r.headers.get("Link", "")
    assert '</mcp>; rel="mcp-server"' in link


def test_mcp_requests_do_not_retain_sessions(mcp_client):
    """Repeated handshakes retain no sessions, and tool discovery needs no session ID."""
    from app.main import mcp_http

    for _ in range(5):
        _initialize(mcp_client)
    assert mcp_http._server_instances == {}
    response = mcp_client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/list",
        },
    )
    assert response.status_code == 200
