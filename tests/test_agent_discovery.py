"""Agent-discovery endpoints: /robots.txt, /.well-known/api-catalog, and Link headers."""


def test_robots_txt_serves(client):
    """`/robots.txt` returns 200 text/plain with the open policy and Content-Signal."""
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Content-Signal: ai-train=yes, search=yes, ai-input=yes" in body
    # Spot-check the major AI crawlers are listed.
    for ua in ["GPTBot", "ClaudeBot", "Google-Extended", "PerplexityBot", "CCBot"]:
        assert f"User-agent: {ua}" in body


def test_api_catalog_serves(client):
    """`/.well-known/api-catalog` returns linkset+json with the right shape."""
    response = client.get("/.well-known/api-catalog")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/linkset+json"

    body = response.json()
    assert "linkset" in body
    assert len(body["linkset"]) >= 1

    entry = body["linkset"][0]
    assert "anchor" in entry
    # The three relations advertised by RFC 9727 for an API.
    for rel in ["service-desc", "service-doc", "status"]:
        assert rel in entry
        assert isinstance(entry[rel], list) and len(entry[rel]) >= 1
        assert "href" in entry[rel][0]


def test_root_link_header_advertises_resources(client):
    """Root response carries an RFC 8288 `Link` header pointing at the catalog and OpenAPI spec."""
    response = client.get("/")
    assert response.status_code == 200
    link = response.headers.get("link", "")
    assert 'rel="api-catalog"' in link
    assert 'rel="service-desc"' in link
    assert 'rel="service-doc"' in link
    assert 'rel="status"' in link
    assert "/.well-known/api-catalog" in link
    # llms.txt rels (extension URI rels per llmstxt.org convention)
    assert 'rel="https://llmstxt.org/"' in link
    assert 'rel="https://llmstxt.org/full"' in link
    # MCP server rel — only present when the MCP mount is enabled (default)
    assert 'rel="mcp-server"' in link
    assert 'rel="mcp-server-card"' in link


def test_mcp_server_card_serves(client):
    """`/.well-known/mcp/server-card.json` returns the MCP Server Card (SEP-1649)."""
    response = client.get("/.well-known/mcp/server-card.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"

    card = response.json()
    assert "serverInfo" in card
    assert card["serverInfo"]["name"] == "epydemix-webapi"
    assert "version" in card["serverInfo"]
    assert "transport" in card
    assert card["transport"]["url"].endswith("/mcp")
    assert "capabilities" in card
    assert "tools" in card["capabilities"]


def test_api_catalog_includes_llms_and_mcp_entries(client):
    """The catalog advertises llms.txt, llms-full.txt, and the MCP server."""
    response = client.get("/.well-known/api-catalog")
    assert response.status_code == 200
    entry = response.json()["linkset"][0]

    # llms.txt long-form rels
    assert "https://llmstxt.org/" in entry
    assert entry["https://llmstxt.org/"][0]["href"].endswith("/llms.txt")
    assert "https://llmstxt.org/full" in entry
    assert entry["https://llmstxt.org/full"][0]["href"].endswith("/llms-full.txt")

    # MCP server (gated by mcp_enabled, which defaults to True)
    assert "mcp-server" in entry
    assert entry["mcp-server"][0]["href"].endswith("/mcp")

    # MCP Server Card (SEP-1649) is registered alongside the MCP endpoint.
    assert "mcp-server-card" in entry
    assert entry["mcp-server-card"][0]["href"].endswith("/server-card.json")
