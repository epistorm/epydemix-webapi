"""Period-end aggregation and raw-output filters must preserve the requested data."""

from copy import deepcopy

import pytest

REQUEST = {
    "model": {"preset": "SIR", "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1}},
    "population": {
        "source": "custom",
        "age_groups": {"A": 100000},
        "contact_matrices": {"all": [[1.0]]},
    },
    "simulation": {
        "start_date": "2025-01-01", "end_date": "2025-01-10", "Nsim": 2, "seed": 42,
    },
    "output": {"include_trajectories": True},
}


def _run(client, frequency="D", dt=1.0, **output):
    request = deepcopy(REQUEST)
    request["simulation"].update(resample_frequency=frequency, dt=dt)
    request["output"].update(output)
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    return response.json()["results"]


@pytest.mark.parametrize("dt", [1.0, 0.5, 0.25])
@pytest.mark.parametrize("frequency,last_label", [("W", "2025-01-12"), ("ME", "2025-01-31")])
def test_partial_periods_keep_all_events(client, dt, frequency, last_label):
    daily = _run(client, dt=dt)
    aggregated = _run(client, frequency, dt)
    assert aggregated["transitions"]["dates"][-1] == last_label
    for daily_run, aggregated_run in zip(
        daily["trajectories"]["runs"], aggregated["trajectories"]["runs"]
    ):
        for transition, groups in daily_run["transitions"].items():
            for group, values in groups.items():
                assert sum(aggregated_run["transitions"][transition][group]) == sum(values)
        for compartment, groups in daily_run["compartments"].items():
            for group, values in groups.items():
                assert aggregated_run["compartments"][compartment][group][-1] == values[-1]
    assert aggregated["summary"]["totals"] == daily["summary"]["totals"]


def test_raw_trajectories_honor_empty_and_named_filters(client):
    results = _run(client, compartments=["Infected"], transitions=[], age_groups=["A"])
    assert set(results["compartments"]["data"]) == {"Infected"}
    for run in results["trajectories"]["runs"]:
        assert set(run["compartments"]) == {"Infected"}
        assert set(run["compartments"]["Infected"]) == {"A"}
        assert run["transitions"] == {}


def test_raw_trajectories_honor_transition_selection(client):
    results = _run(client, compartments=[], transitions=["Infected_to_Recovered"])
    for run in results["trajectories"]["runs"]:
        assert run["compartments"] == {}
        assert set(run["transitions"]) == {"Infected_to_Recovered"}


@pytest.mark.parametrize("dt,frequency", [(0.5, "12h"), (0.25, "6h")])
def test_subdaily_axes_preserve_each_timestamp(client, dt, frequency):
    results = _run(client, frequency, dt, include_parameters=True)
    for section in ("compartments", "transitions", "parameters", "trajectories"):
        dates = results[section]["dates"]
        assert len(dates) == len(set(dates))
        assert len(dates) == 10 * round(1 / dt)
        assert dates[0] == "2025-01-01T00:00:00"
        assert "T" in dates[-1]


def test_subdaily_export_preserves_the_same_axis(client, tmp_path, monkeypatch):
    import numpy as np
    import pandas as pd

    from app.api.v1.schemas.simulation import SimulationRequest
    from app.services.python_export import render_simulation_python

    request = deepcopy(REQUEST)
    request["simulation"].update(dt=0.5, resample_frequency="12h")
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    result = response.json()["results"]["compartments"]
    monkeypatch.chdir(tmp_path)
    namespace = {}
    exec(render_simulation_python(SimulationRequest.model_validate(request)), namespace)
    native = namespace["compartment_quantiles"]
    median = native[native["quantile"] == 0.5]
    assert pd.to_datetime(result["dates"]).tolist() == median["date"].tolist()
    np.testing.assert_array_equal(
        result["data"]["Infected"]["total"]["0.5"], median["Infected_total"]
    )
