"""Real HTTP regression for MCP requests crossing process boundaries."""

import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest


@contextmanager
def _live_server(tmp_path):
    """Yield a real single-worker server URL and reap its process on teardown."""
    tmp_path.mkdir()
    wrapper = tmp_path / "runtime_probe.py"
    wrapper.write_text("""
import os
from app.main import app
@app.middleware("http")
async def worker_pid(request, call_next):
    response = await call_next(request)
    response.headers["x-worker-pid"] = str(os.getpid())
    return response
""")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "EPYDEMIX_WARM_CACHE_ON_STARTUP": "false",
    }
    log = (tmp_path / "uvicorn.log").open("w+")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "runtime_probe:app",
            "--app-dir",
            str(tmp_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
        ],
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                if httpx.get(url + "/api/v1/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            log.seek(0)
            pytest.fail(log.read())
        yield url
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        log.close()


@pytest.fixture
def live_servers(tmp_path):
    """Provide servers A and B, each with its own process and port."""
    with (
        _live_server(tmp_path / "server_a") as server_a,
        _live_server(tmp_path / "server_b") as server_b,
    ):
        yield server_a, server_b


def test_mcp_requests_succeed_on_server_b_after_initializing_server_a(live_servers):
    """Start a connection on A, then use tools on B without initializing B.

    In epistorm/epydemix#24, B rejected these requests with "Session not found"
    because only A knew the session. Stateless MCP must accept them on B.
    """
    # Prepare two servers and accept MCP's JSON or event-stream responses.
    server_a, server_b = live_servers
    headers = {"Accept": "application/json, text/event-stream"}

    # Initialize on A; expect success without a session ID.
    initialize_response = httpx.post(
        server_a + "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert initialize_response.status_code == 200, initialize_response.text
    assert "error" not in initialize_response.json()
    assert initialize_response.json()["id"] == 1
    assert "mcp-session-id" not in initialize_response.headers
    server_a_pid = initialize_response.headers["x-worker-pid"]

    # Notify B that initialization is complete; expect an empty 202 response.
    # B never received initialize, and the PID check proves it is a different process.
    notification_response = httpx.post(
        server_b + "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )
    assert notification_response.status_code == 202, notification_response.text
    assert notification_response.content == b""
    assert "mcp-session-id" not in notification_response.headers
    server_b_pid = notification_response.headers["x-worker-pid"]
    assert server_b_pid != server_a_pid

    # Ask B for its tools without a session ID; expect health_check in the list.
    tools_response = httpx.post(
        server_b + "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert tools_response.status_code == 200, tools_response.text
    assert "error" not in tools_response.json()
    assert tools_response.json()["id"] == 2
    assert "mcp-session-id" not in tools_response.headers
    assert tools_response.headers["x-worker-pid"] == server_b_pid
    tool_names = {tool["name"] for tool in tools_response.json()["result"]["tools"]}
    assert "health_check" in tool_names

    # Run health_check on B; expect a successful tool result from the same B process.
    health_response = httpx.post(
        server_b + "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "health_check", "arguments": {}},
        },
    )
    assert health_response.status_code == 200, health_response.text
    assert "error" not in health_response.json()
    assert health_response.json()["id"] == 3
    assert "mcp-session-id" not in health_response.headers
    assert health_response.headers["x-worker-pid"] == server_b_pid
    assert health_response.json()["result"]["isError"] is False
