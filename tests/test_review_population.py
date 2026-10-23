"""Regression checks for shared population loading, age order and I/O deadlines."""

import shutil
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import epydemix.population
import numpy as np
import pandas as pd
import pytest
from epydemix.model.epimodel import EpiModel

from app.api.v1.schemas.simulation import (
    BuiltinPopulationConfig,
    InitialConditionsConfig,
    SimulationRequest,
)
from app.services import population_service as service
from app.services.model_service import apply_age_varying_parameters, create_initial_conditions
from app.services.python_export import render_simulation_python


@pytest.fixture
def population_data(tmp_path, monkeypatch):
    ages = [str(i) for i in range(84)] + ["84+"]
    demographics = pd.DataFrame({"group_name": ages, "value": np.arange(85) + 100})
    demographics.to_csv(tmp_path / "age_distribution.csv", index=False)
    np.savetxt(tmp_path / "matrix.csv", np.eye(85), delimiter=",")
    locations = pd.DataFrame({"location": ["Test"], "primary_contact_source": ["mistry_2021"]})
    monkeypatch.setattr(service, "get_locations_df", lambda: locations)
    downloads = []

    def download(directory, paths, name):
        downloads.append(paths)
        for relative_path in paths:
            target = directory / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            source = "age_distribution.csv" if "demographic" in relative_path else "matrix.csv"
            shutil.copyfile(tmp_path / source, target)

    monkeypatch.setattr(service, "_download_files", download)
    service._load_population_cached_inner.cache_clear()
    yield downloads, ages
    service._load_population_cached_inner.cache_clear()


def test_warmup_detail_and_simulation_share_cache_and_copies(population_data):
    downloads, _ = population_data
    assert service.warm_cache(["Test"]) == {"Test": True}
    detail = service.get_population_detail("Test")
    config = BuiltinPopulationConfig(name="Test", contacts_source="mistry_2021")
    first = service.get_simulation_population(config)
    first.Nk[0] = -1
    first.contact_matrices["home"][0, 0] = -1
    second = service.get_simulation_population(config)
    assert second.Nk[0] == detail.age_groups["0-4"]
    assert second.contact_matrices["home"][0, 0] >= 0
    assert len(downloads) == 1
    assert service.get_cache_info() == {
        "hits": 3,
        "misses": 1,
        "maxsize": 50,
        "currsize": 1,
        "cached_populations": ["Test"],
    }
    service._load_population_cached_inner.cache_clear()
    assert service.get_cache_info()["cached_populations"] == []
    assert detail.total_population > 0  # Metadata and model copies survive eviction.


def test_age_mapping_order_preserves_positional_rates_and_initial_conditions(
    population_data, tmp_path, monkeypatch
):
    downloads, ages = population_data
    mapping = {"young": ages[:50], "older": ages[50:]}
    config = BuiltinPopulationConfig(name="Test", age_group_mapping=mapping)
    model = EpiModel(compartments=["S", "I", "R"])
    service.setup_population(model, config)
    apply_age_varying_parameters(model, {"recovery_rate": [0.1, 0.9]})
    initial = create_initial_conditions(
        model, InitialConditionsConfig(method="absolute", compartments={"I": [3, 7]})
    )
    assert list(model.population.Nk_names) == ["young", "older"]
    assert dict(zip(model.population.Nk_names, model.parameters["recovery_rate"].ravel())) == {
        "young": 0.1,
        "older": 0.9,
    }
    assert dict(zip(model.population.Nk_names, initial["I"])) == {"young": 3, "older": 7}
    reversed_config = config.model_copy(
        update={"age_group_mapping": dict(reversed(mapping.items()))}
    )
    reversed_population = service.get_simulation_population(reversed_config)
    assert list(reversed_population.Nk_names) == ["older", "young"]
    assert len(downloads) == 2

    # Execute the exported setup against the same raw data, retaining the library's aggregation.
    offline = tmp_path / "offline"
    service._download_files(offline, downloads[0], "Test")
    service.get_locations_df().to_csv(offline / "locations.csv", index=False)
    load = service.load_epydemix_population
    monkeypatch.setattr(
        epydemix.population,
        "load_epydemix_population",
        lambda **kwargs: load(**kwargs, path_to_data=str(offline)),
    )
    request = SimulationRequest(
        model={
            "compartments": ["S", "I", "R"],
            "parameters": {"recovery_rate": [0.1, 0.9]},
            "transitions": [
                {"source": "I", "target": "R", "kind": "spontaneous", "params": ["recovery_rate"]}
            ],
        },
        population=config,
        simulation={"start_date": "2025-01-01", "end_date": "2025-01-03", "Nsim": 1},
        initial_conditions={"method": "absolute", "compartments": {"I": [3, 7]}},
    )
    namespace = {}
    source = render_simulation_python(request).split("results = model.run_simulations(")[0]
    exec(compile(source, "<exported-setup>", "exec"), namespace)
    exported = namespace["model"]
    np.testing.assert_array_equal(exported.population.Nk_names, model.population.Nk_names)
    np.testing.assert_array_equal(exported.population.Nk, model.population.Nk)
    np.testing.assert_array_equal(
        exported.parameters["recovery_rate"], model.parameters["recovery_rate"]
    )
    np.testing.assert_array_equal(namespace["initial_conditions"]["I"], initial["I"])


@pytest.mark.parametrize("drip", [False, True])
def test_actual_download_timeout_kills_and_reaps_child(tmp_path, monkeypatch, drip):
    """A slow response and a response which never idles both meet the wall deadline."""
    started = threading.Event()
    disconnected = threading.Event()

    class SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            started.set()
            self.send_response(200)
            self.end_headers()
            try:
                if not drip:
                    time.sleep(0.8)
                for _ in range(100):
                    self.wfile.write(b"a")
                    self.wfile.flush()
                    time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(service, "_DATA_URL", f"http://127.0.0.1:{server.server_port}/")
    token = service._load_deadline.set(time.monotonic() + 0.25)
    try:
        before = time.monotonic()
        with pytest.raises(service.PopulationLoadTimeoutError):
            service._download_files(tmp_path, ["slow.csv"], "Test")
        elapsed = time.monotonic() - before
        assert started.is_set()
        assert 0.15 < elapsed < 0.65
        assert disconnected.wait(1.5), "Timed-out downloader still owns its HTTP connection"
    finally:
        service._load_deadline.reset(token)
        server.shutdown()
        server.server_close()
        thread.join()


def test_builtin_simulation_uses_population_timeout(tmp_path, monkeypatch):
    """The simulation path must pass through the same bounded downloader."""
    monkeypatch.setattr(
        service,
        "get_locations_df",
        lambda: pd.DataFrame({"location": ["Timeout"], "primary_contact_source": ["mistry_2021"]}),
    )
    observed = []

    def fail_download(directory, paths, name):
        observed.append(service._load_deadline.get() - time.monotonic())
        raise service.PopulationLoadTimeoutError(name, 0.1)

    monkeypatch.setattr(service, "_download_files", fail_download)
    with pytest.raises(service.PopulationLoadTimeoutError) as exc:
        service.get_simulation_population(BuiltinPopulationConfig(name="Timeout"), timeout=0.1)
    assert 0 < observed[0] <= 0.1
    assert exc.value.timeout == 0.1
    assert service._load_deadline.get() is None


def test_cache_status_excludes_evicted_populations_despite_external_copies(
    population_data, monkeypatch
):
    _, ages = population_data
    monkeypatch.setattr(
        service,
        "get_locations_df",
        lambda: pd.DataFrame(
            {
                "location": ["First", "Test"],
                "primary_contact_source": ["mistry_2021", "mistry_2021"],
            }
        ),
    )
    retained = service._load_population_cached("First")
    for index in range(51):
        service._load_population_cached(
            "Test", layers=["home"], age_group_mapping={str(index): ages}
        )
    info = service.get_cache_info()
    assert info["currsize"] == 50
    assert info["cached_populations"] == ["Test"]
    assert retained.total_population > 0


def test_concurrent_identical_cold_loads_remain_visible_in_cache(population_data, monkeypatch):
    original = service.load_epydemix_population
    both_loading = threading.Barrier(2)

    def concurrent_load(**kwargs):
        population = original(**kwargs)
        both_loading.wait(timeout=5)
        return population

    monkeypatch.setattr(service, "load_epydemix_population", concurrent_load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service._load_population_cached, "Test") for _ in range(2)]
        populations = [future.result() for future in futures]
    info = service.get_cache_info()
    assert info["currsize"] == 1
    assert info["cached_populations"] == ["Test"]
    assert all(population.total_population > 0 for population in populations)


def test_cache_status_handles_concurrent_insertions_and_evictions(monkeypatch):
    stop = threading.Event()
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(0.000001)
    # Exercise the same weak wrapper insertion/removal as cold loads and LRU eviction.
    monkeypatch.setattr(service, "_cached_populations", type(service._cached_populations)())

    def write():
        retained = deque(maxlen=50)
        try:
            for index in range(10000):
                population = service.Population(name=str(index))
                cached = service._CachedPopulation(population)
                retained.append(cached)
                service._cached_populations[id(cached)] = cached
        finally:
            stop.set()

    writer = threading.Thread(target=write)
    try:
        writer.start()
        while not stop.is_set():
            service.get_cache_info()
    finally:
        writer.join()
        sys.setswitchinterval(old_interval)


def test_warmed_population_handoff_needs_no_child_network(population_data, client, monkeypatch):
    downloads, _ = population_data
    assert service.warm_cache(["Test"]) == {"Test": True}
    # Spawned workers inherit the proxy; any accidental remote metadata load fails.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    response = client.post("/api/v1/simulations", json={
        "model": {"preset": "SIR"},
        "population": {"name": "Test"},
        "simulation": {"start_date": "2025-01-01", "end_date": "2025-01-03", "Nsim": 1},
    })
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["population"]["contacts_source"] == "mistry_2021"
    assert len(downloads) == 1
    assert service.get_cache_info()["hits"] == 1
