"""Sub-daily ``dt`` last-day aggregation.

Regression coverage for the partial-last-day fix in
``simulation_service.run_simulation``: when ``dt < 1.0`` and the output is
resampled to daily, epydemix's grid leaves the user-requested ``end_date``
with only one sub-step instead of ``1/dt``, so summed transitions on the last
day would otherwise scale by ``dt``. The service pads ``end_date`` by one day
internally and trims the trailing day before responding.

See BUG-epydemix-last-day-partial-aggregation.md.
"""

from __future__ import annotations

import pandas as pd
import pytest
from epydemix.utils.utils import compute_simulation_dates

from app.api.v1.schemas.simulation import SimulationConfig
from app.services.simulation_service import _padded_internal_simulation


def _flu_request(dt: float, end_date: str = "2025-04-15", include_parameters: bool = False) -> dict:
    return {
        "model": {
            "preset": "V-SEIHR",
            "parameters": {
                "R0": 1.5,
                "incubation_period": 1.5,
                "infectious_period": 4.0,
                "hosp_duration": 5.0,
                "hosp_proportion": 0.01,
                "VE_S": 0.5,
                "VE_H": 0.6,
            },
        },
        "population": {
            "source": "custom",
            "name": "homogeneous",
            "age_groups": {"all": 1_000_000},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": end_date,
            "Nsim": 100,
            "seed": 7,
            "dt": dt,
        },
        "initial_conditions": {
            "method": "percentage",
            "initial_percentages": {"Infected": 0.1},
        },
        "output": {"include_parameters": include_parameters},
    }


def _infection_incidence_median(body: dict) -> list[float]:
    """Median ``Exposed_to_Infected`` series (homogeneous: single age group)."""
    section = body["results"]["transitions"]["data"]["Exposed_to_Infected"]
    key = next(k for k in section if k != "total")
    return section[key]["0.5"]


@pytest.mark.parametrize("dt", [1.0, 0.5, 0.25, 0.1])
def test_subdaily_dt_ends_on_user_requested_date(client, dt):
    """Response ends on the user's ``end_date`` and has the expected number of days."""
    end_date = "2025-04-15"
    expected_n_days = 105  # Jan 1 to Apr 15 inclusive

    response = client.post("/api/v1/simulations", json=_flu_request(dt=dt, end_date=end_date))
    assert response.status_code == 200

    body = response.json()
    dates = body["results"]["transitions"]["dates"]
    assert dates[-1] == end_date
    assert len(dates) == expected_n_days


@pytest.mark.parametrize("dt", [0.5, 0.25, 0.1])
def test_subdaily_dt_last_day_not_scaled_by_dt(client, dt):
    """Last-day E->I value follows natural decay, not ``dt × true_value``.

    The flu scenario is past peak at Apr-15, so the curve decays at roughly
    a constant geometric rate. Pre-fix, the last day would be ``~dt`` of the
    previous day (well below 0.7); with the fix it stays close to the
    inter-day decay ratio (~0.93).
    """
    response = client.post("/api/v1/simulations", json=_flu_request(dt=dt))
    incidence = _infection_incidence_median(response.json())
    ratio = incidence[-1] / incidence[-2]
    assert 0.7 < ratio < 1.0


def test_subdaily_dt_does_not_affect_dt_one(client):
    """``dt=1.0`` is a no-op for the padding logic; results unchanged."""
    response = client.post("/api/v1/simulations", json=_flu_request(dt=1.0))
    body = response.json()
    dates = body["results"]["transitions"]["dates"]
    incidence = _infection_incidence_median(body)

    assert dates[-1] == "2025-04-15"
    assert incidence[-1] > 0
    ratio = incidence[-1] / incidence[-2]
    assert 0.7 < ratio < 1.0


def test_subdaily_dt_metadata_reports_user_end_date(client):
    """Metadata echoes the user's ``end_date``, not the internally padded one."""
    response = client.post("/api/v1/simulations", json=_flu_request(dt=0.5))
    assert response.json()["metadata"]["simulation"]["end_date"] == "2025-04-15"


def test_subdaily_dt_parameter_results_match_dates(client):
    """``include_parameters`` returns timeseries matching the trimmed length."""
    response = client.post(
        "/api/v1/simulations",
        json=_flu_request(dt=0.5, include_parameters=True),
    )
    params = response.json()["results"]["parameters"]
    n_dates = len(params["dates"])

    assert params["dates"][-1] == "2025-04-15"
    for groups in params["data"].values():
        for values in groups.values():
            assert len(values) == n_dates


@pytest.mark.parametrize("dt", [1.0, 0.5, 0.25, 0.1])
def test_subdaily_dt_grid_has_uniform_substeps_per_day(dt):
    """Every calendar day in the user's range gets ``1/dt`` sub-steps.

    Direct check on the padded internal grid: after ``_padded_internal_simulation``,
    ``compute_simulation_dates`` should produce a grid where every day inside
    ``[start_date, end_date]`` is covered by exactly ``1/dt`` sub-steps. This is
    what guarantees the daily-resampled ``sum`` aggregation is correct on every
    day, including the last.
    """
    user_start = "2025-01-01"
    user_end = "2025-04-15"
    cutoff = pd.Timestamp(user_end).normalize()
    expected_substeps = round(1.0 / dt)

    sim = SimulationConfig(start_date=user_start, end_date=user_end, Nsim=1, dt=dt)
    padded = _padded_internal_simulation(sim)
    grid = compute_simulation_dates(padded.start_date, padded.end_date, dt=dt)
    days = pd.to_datetime([str(d) for d in grid]).normalize()
    counts_by_day = pd.Series(days).value_counts().sort_index()
    user_visible = counts_by_day[counts_by_day.index <= cutoff]

    assert set(user_visible.tolist()) == {expected_substeps}


def test_subdaily_dt_compartments_match_transition_dates(client):
    """Compartments and transitions share the same trimmed date axis."""
    response = client.post("/api/v1/simulations", json=_flu_request(dt=0.5))
    body = response.json()
    comp_dates = body["results"]["compartments"]["dates"]
    trans_dates = body["results"]["transitions"]["dates"]

    assert comp_dates == trans_dates
    assert comp_dates[-1] == "2025-04-15"
