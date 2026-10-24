"""Real HTTP checks for responsiveness during simulation execution."""

import os
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def live_server(tmp_path):
    wrapper = tmp_path / "runtime_probe.py"
    wrapper.write_text("""
import os
from app.main import app
from app.services.simulation_runtime import _admission
@app.middleware("http")
async def worker_pid(request, call_next):
    response = await call_next(request)
    response.headers["x-worker-pid"] = str(os.getpid())
    response.headers["x-simulation-active"] = str(_admission._value == 0)
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


def test_health_responds_during_real_simulation_on_same_worker(live_server):
    payload = {
        "model": {"preset": "SIR"},
        "population": {
            "source": "custom",
            "age_groups": {"A": 10000},
            "contact_matrices": {"all": [[1]]},
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-02-01",
            "Nsim": 100,
            "dt": 0.2,
        },
    }
    with ThreadPoolExecutor(max_workers=1) as pool:
        simulation = pool.submit(
            httpx.post, live_server + "/api/v1/simulations", json=payload, timeout=30
        )
        for _ in range(100):
            start = time.monotonic()
            health = httpx.get(live_server + "/api/v1/health", timeout=1)
            elapsed = time.monotonic() - start
            if health.headers["x-simulation-active"] == "True":
                assert elapsed < 0.5
                assert not simulation.done()
                overlap = httpx.post(live_server + "/api/v1/simulations", json=payload, timeout=2)
                assert overlap.status_code == 503, overlap.text
                break
            assert not simulation.done(), simulation.result().text
            time.sleep(0.01)
        else:
            pytest.fail("Did not observe a running simulation")
        response = simulation.result()
        assert response.status_code == 200, response.text
