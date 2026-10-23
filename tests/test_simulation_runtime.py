"""Exercise actual spawned workers, deadlines and admission without epidemic work."""

import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.api.v1.schemas.simulation import SimulationRequest
from app.config import settings
from app.services import population_service, simulation_runtime


def _sleeping_worker(connection, request, population):
    time.sleep(30)
    connection.send(("ok", None))


def _quick_worker(connection, request, population):
    connection.send(("ok", "finished"))


@pytest.fixture
def request_and_population(monkeypatch):
    request = SimulationRequest.model_validate(
        {
            "model": {"preset": "SIR"},
            "population": {"name": "Italy", "contacts_source": "mistry_2021"},
            "simulation": {"start_date": "2024-01-01", "end_date": "2024-01-03", "Nsim": 1},
        }
    )
    population = SimpleNamespace(Nk=[1000], contact_matrices={"all": [[1]]})
    monkeypatch.setattr(
        population_service, "get_simulation_population", lambda *a, **kw: population, raising=False
    )
    return request


def test_timeout_kills_and_reaps_worker_and_releases_admission(monkeypatch, request_and_population):
    previous_children = {p.pid for p in multiprocessing.active_children()}
    monkeypatch.setattr(settings, "request_timeout", 0.2)
    monkeypatch.setattr(simulation_runtime, "_simulate", _sleeping_worker)
    start = time.monotonic()
    with pytest.raises(simulation_runtime.SimulationTimeoutError):
        simulation_runtime.run_simulation(request_and_population)
    assert time.monotonic() - start < 3
    assert {p.pid for p in multiprocessing.active_children()} == previous_children
    monkeypatch.setattr(settings, "request_timeout", 10)
    monkeypatch.setattr(simulation_runtime, "_simulate", _quick_worker)
    assert simulation_runtime.run_simulation(request_and_population) == "finished"


def test_admission_rejects_overlap_without_starting_second_job(monkeypatch, request_and_population):
    entered = threading.Event()
    release = threading.Event()

    def load(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise ValueError("test load complete")

    monkeypatch.setattr(population_service, "get_simulation_population", load)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(simulation_runtime.run_simulation, request_and_population)
        assert entered.wait(5)
        try:
            with pytest.raises(simulation_runtime.SimulationBusyError):
                simulation_runtime.run_simulation(request_and_population)
        finally:
            release.set()
        with pytest.raises(ValueError, match="test load complete"):
            first.result()
