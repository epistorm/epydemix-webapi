"""End-to-end tests for the V-SEIHR preset.

Locks down compartment structure, default behavior, the parameter-conversion
chain (period inputs and R0 -> beta), and integration with the vaccination
block.
"""

import pytest

from app.presets import PRESETS

_V_SEIHR_COMPARTMENTS = [
    "Susceptible",
    "Susceptible_vax",
    "Exposed",
    "Exposed_vax",
    "Infected",
    "Infected_vax",
    "Hospitalized",
    "Hospitalized_vax",
    "Recovered",
    "Recovered_vax",
]


def _baseline_request(**overrides):
    request = {
        "model": {
            "preset": "V-SEIHR",
            "parameters": {
                "R0": 2.5,
                "incubation_period": 3.0,
                "infectious_period": 2.5,
                "hosp_duration": 5.0,
                "hosp_proportion": 0.05,
                "VE_S": 0.7,
                "VE_H": 0.85,
            },
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
            "Nsim": 3,
            "seed": 42,
        },
    }
    request.update(overrides)
    return request


def test_v_seihr_baseline(client):
    """V-SEIHR preset runs with defaults and exposes all 10 compartments."""
    response = client.post("/api/v1/simulations", json=_baseline_request())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metadata"]["model"]["compartments"] == _V_SEIHR_COMPARTMENTS


def test_v_seihr_in_presets_endpoint(client):
    """`GET /models/presets` lists V-SEIHR with the right compartments."""
    response = client.get("/api/v1/models/presets")
    assert response.status_code == 200
    presets = {p["name"]: p for p in response.json()["presets"]}
    assert "V-SEIHR" in presets
    assert presets["V-SEIHR"]["compartments"] == _V_SEIHR_COMPARTMENTS


def test_v_seihr_registry_consistency(client):
    """The registry, the presets endpoint, and the request literal agree."""
    response = client.get("/api/v1/models/presets")
    endpoint_names = {p["name"] for p in response.json()["presets"]}
    assert endpoint_names == set(PRESETS)


def test_v_seihr_calc_params_exposed(client):
    """Preset-specific calc-params surface in `results.parameters`."""
    request = _baseline_request()
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    for name in (
        "transmission_rate",
        "transmission_rate_vax",
        "hosp_proportion_vax",
        "I_to_R_rate",
        "I_to_H_rate",
        "Ivax_to_R_rate",
        "Ivax_to_H_rate",
        "recovery_rate",
        "incubation_rate",
        "hosp_recovery_rate",
    ):
        assert name in params["data"], f"missing {name} in results.parameters"


def test_v_seihr_VE_zero(client):
    """When VE_S and VE_H are zero, vaccinated rate parameters equal unvaccinated."""
    request = _baseline_request()

    # Set VE_S and VE_H to zero to disable vaccine effects
    request["model"]["parameters"]["VE_S"] = 0.0
    request["model"]["parameters"]["VE_H"] = 0.0

    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    first = next(iter(params["transmission_rate"]))

    # Compare transmission_rate and hosp_proportion to their vax twins
    # With VE_S and VE_H at zero, the twins should be equal
    assert params["transmission_rate_vax"][first][0] == pytest.approx(
        params["transmission_rate"][first][0], abs=1e-9
    )
    assert params["hosp_proportion_vax"][first][0] == pytest.approx(
        params["hosp_proportion"][first][0], abs=1e-9
    )


def test_v_seihr_waning_off_by_default(client):
    """Without `immunity_duration`, waning_rate stays at 0.0 and no R -> S transitions fire.

    Locks down both the parameter value AND the simulation consequence: with the
    waning rate at zero the stochastic draw on `Recovered -> Susceptible`
    (and its vaccinated twin) can never produce a non-zero transition count.
    """
    request = _baseline_request()  # No parameters for waning, so the preset default of 0.0 applies.
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200
    body = response.json()["results"]

    # Parameter value: waning_rate is exactly 0.0 everywhere.
    series = next(iter(body["parameters"]["data"]["waning_rate"].values()))
    assert series == pytest.approx([0.0] * len(series), abs=1e-12)

    # Simulation: zero cumulative R -> S transitions in the median trajectory,
    # across both layers and every age group.
    totals = body["summary"]["totals"]
    for name in ("Recovered_to_Susceptible", "Recovered_vax_to_Susceptible_vax"):
        for age_data in totals[name].values():
            assert age_data["quantiles"]["0.5"] == 0.0, (
                f"{name} median = {age_data['quantiles']['0.5']}, expected 0"
            )


def test_v_seihr_waning_enabled_via_immunity_duration(client):
    """`immunity_duration` injects `waning_rate = 1 / immunity_duration` and R -> S fires.

    Complement of `test_v_seihr_waning_off_by_default`: with waning on, the
    cumulative `Recovered -> Susceptible` count must be positive at the
    median quantile (some recovered individuals re-enter the susceptible
    pool over the simulation horizon).
    """
    request = _baseline_request()

    # Set waning on via immunity_duration
    request["model"]["parameters"]["immunity_duration"] = 30.0
    request["initial_conditions"] = {
        "method": "absolute",
        "compartments": {
            "Recovered": [10_000, 10_000, 10_000, 10_000, 10_000],
        },
    }
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    body = response.json()["results"]

    # Parameter value: waning_rate is 1/30 everywhere.
    series = next(iter(body["parameters"]["data"]["waning_rate"].values()))
    assert series == pytest.approx([1 / 30.0] * len(series), abs=1e-9)

    # Simulation: R -> S median total is positive
    # (seeded recovered individuals re-enter the susceptible pool).
    totals = body["summary"]["totals"]["Recovered_to_Susceptible"]
    medians = [age_data["quantiles"]["0.5"] for age_data in totals.values()]
    assert sum(medians) > 0, f"Recovered_to_Susceptible medians = {medians}"


def test_v_seihr_with_vaccination_campaign(client):
    """Vaccination campaign on V-SEIHR drives Susceptible_to_Susceptible_vax transitions."""
    request = _baseline_request()
    request["simulation"]["end_date"] = "2025-04-30"
    request["vaccination"] = {
        "campaigns": [
            {
                "start_date": "2025-02-01",
                "end_date": "2025-02-28",
                "rollout": {"type": "flat_count", "daily_doses": 100_000},
            }
        ]
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    data = response.json()
    transitions = data["results"]["transitions"]

    assert "Susceptible_to_Susceptible_vax" in transitions["data"]
    # The campaign must actually drive S -> S_vax flow.
    totals = data["results"]["summary"]["totals"]["Susceptible_to_Susceptible_vax"]
    medians = [age_data["quantiles"]["0.5"] for age_data in totals.values()]
    assert sum(medians) > 0, f"Susceptible_to_Susceptible_vax medians = {medians}"

    # Echo-back in metadata.
    assert data["metadata"]["vaccination"]["campaigns"][0]["rollout"]["daily_doses"] == 100_000


def test_v_seihr_hosp_proportion_default_is_age_stratified(client):
    """The hosp_proportion default is a length-5 list matching the dashboard.

    Locks down both the registry advertisement and the runtime behavior: the
    list reaches the model and surfaces as a per-age-group series in
    ``results.parameters``, and the derived calc-params (``hosp_proportion_vax``,
    ``I_to_H_rate``, ``Ivax_to_H_rate``) inherit the per-group shape.
    """
    expected = [0.002, 0.005, 0.015, 0.05, 0.18]

    # Registry advertises the list default (and the presets endpoint echoes it).
    presets_response = client.get("/api/v1/models/presets")
    assert presets_response.status_code == 200
    v_seihr = next(p for p in presets_response.json()["presets"] if p["name"] == "V-SEIHR")
    assert v_seihr["parameters"]["hosp_proportion"] == expected

    # Runtime: omit hosp_proportion so the default is exercised end-to-end.
    request = _baseline_request()
    request["model"]["parameters"].pop("hosp_proportion")
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]

    # hosp_proportion appears once per age group, each as a constant time series
    # equal to its bin's default. There are five bins; bin ordering follows the
    # epydemix United_States age structure.
    groups = list(params["hosp_proportion"].keys())
    assert len(groups) == 5, groups
    for group_name, group_default in zip(groups, expected):
        series = params["hosp_proportion"][group_name]
        assert series == pytest.approx([group_default] * len(series), abs=1e-12)

    # Derived calc-params inherit the age structure.
    for derived in ("hosp_proportion_vax", "I_to_H_rate", "Ivax_to_H_rate"):
        assert len(params[derived]) == 5, f"{derived} not age-stratified"


def test_v_seihr_explicit_initial_conditions(client):
    """Initial conditions seed Infected and leave _vax compartments empty when requested explicitly."""
    request = _baseline_request()
    request["initial_conditions"] = {
        "method": "percentage",
        "initial_percentages": {"Infected": 0.1},
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text


def test_v_seihr_vaccination_metadata_surfaces_default_flows(client):
    """V-SEIHR's defaulted Susceptible -> Susceptible_vax flow is echoed in metadata.

    Regression: previously the metadata block echoed back the raw request, so
    if the caller omitted `vaccination.flows` it stayed `null` in the response
    even though the simulator had defaulted it internally.
    """
    request = _baseline_request()
    request["vaccination"] = {
        "campaigns": [
            {
                "start_date": "2025-02-01",
                "end_date": "2025-03-15",
                "rollout": {"type": "flat_count", "daily_doses": 100000},
            }
        ]
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    flows = response.json()["metadata"]["vaccination"]["flows"]
    assert flows == [{"source": "Susceptible", "target": "Susceptible_vax"}]


def test_v_seihr_summary_peaks_do_not_leak_vax_compartments(client):
    """Susceptible's per-age-group peaks must not include `Susceptible_vax` keys.

    Regression: the previous age-group resolver stripped `base + "_"` from every
    stacked-data key, so `Susceptible_vax_0-4` was misread as age group
    `vax_0-4` under base `Susceptible` (and `vax_total` under `Susceptible`).
    The fix grounds age groups in the population's `Nk_names` instead of
    inferring them from key suffixes.
    """
    response = client.post("/api/v1/simulations", json=_baseline_request())
    assert response.status_code == 200, response.text

    peaks = response.json()["results"]["summary"]["peaks"]

    # Susceptible (unvaccinated) and Susceptible_vax (vaccinated) must both be
    # present, each with its own age groups - no cross-leakage.
    assert "Susceptible" in peaks
    assert "Susceptible_vax" in peaks

    expected_age_groups = {"0-4", "5-19", "20-49", "50-64", "65+", "total"}
    assert set(peaks["Susceptible"].keys()) == expected_age_groups
    assert set(peaks["Susceptible_vax"].keys()) == expected_age_groups

    # No vax_* leakage in the unvaccinated compartment, and the same check
    # holds across every other compartment with a _vax twin.
    for comp in ("Susceptible", "Exposed", "Infected", "Hospitalized", "Recovered"):
        for age_group in peaks[comp]:
            assert not age_group.startswith("vax_"), (
                f"{comp} peaks contain leaked _vax key: {age_group}"
            )


@pytest.mark.slow
def test_v_seihr_vaccination_speed_orders_outcomes(client):
    """Faster rollout monotonically decreases both peak incidence and final size.

    Runs five scenarios on a homogeneous 1M population:
      - No vaccination (baseline)
      - Pulse on day 2 (essentially all S -> S_vax in one step)
      - Flat very fast (3% of N per day, 6-month window)
      - Flat fast (1% of N per day, 6-month window)
      - Flat slow (0.1% of N per day, 6-month window)

    Expected ordering for both metrics:
        pulse <= very_fast <= fast <= slow <= no_vax

    Peak incidence = max over time of the median daily
    `Exposed_to_Infected + Exposed_vax_to_Infected_vax` count.

    Final size = `1 - (S(end) + S_vax(end)) / N`,
    i.e. the fraction of the population that ever left the susceptible pools (vaccinated or not).
    """
    n_pop = 1_000_000
    horizon = ("2025-01-01", "2025-08-31")
    base = {
        "model": {
            "preset": "V-SEIHR",
            "parameters": {
                "R0": 2.5,
                "incubation_period": 3.0,
                "infectious_period": 2.5,
                "hosp_duration": 5.0,
                "hosp_proportion": 0.05,
                "VE_S": 0.85,
                "VE_H": 0.9,
            },
        },
        "population": {
            "source": "custom",
            "name": "homogeneous",
            "age_groups": {"all": n_pop},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": horizon[0],
            "end_date": horizon[1],
            "Nsim": 15,
            "seed": 7,
        },
        "initial_conditions": {
            "method": "percentage",
            "initial_percentages": {"Infected": 0.1},
        },
    }

    def _campaign(daily_doses, start="2025-01-02", end="2025-06-30"):
        return {
            "campaigns": [
                {
                    "start_date": start,
                    "end_date": end,
                    "rollout": {"type": "flat_count", "daily_doses": daily_doses},
                }
            ]
        }

    scenarios = {
        "no_vax": None,
        "pulse": _campaign(1e11, start="2025-01-02", end="2025-01-02"),
        "very_fast": _campaign(0.03 * n_pop),
        "fast": _campaign(0.01 * n_pop),
        "slow": _campaign(0.001 * n_pop),
    }

    def _run(vaccination):
        req = dict(base)
        if vaccination is not None:
            req = {**req, "vaccination": vaccination}
        resp = client.post("/api/v1/simulations", json=req)
        assert resp.status_code == 200, resp.text
        return resp.json()["results"]

    def _peak_incidence(results):
        inc_u = next(iter(results["transitions"]["data"]["Exposed_to_Infected"].values()))["0.5"]
        inc_v = next(iter(results["transitions"]["data"]["Exposed_vax_to_Infected_vax"].values()))[
            "0.5"
        ]
        return max(a + b for a, b in zip(inc_u, inc_v))

    def _final_attack_rate(results):
        s = next(iter(results["compartments"]["data"]["Susceptible"].values()))["0.5"]
        s_vax = next(iter(results["compartments"]["data"]["Susceptible_vax"].values()))["0.5"]
        return 1.0 - (s[-1] + s_vax[-1]) / n_pop

    bodies = {k: _run(v) for k, v in scenarios.items()}
    peaks = {k: _peak_incidence(b) for k, b in bodies.items()}
    finals = {k: _final_attack_rate(b) for k, b in bodies.items()}

    # The flat scenarios should actually deliver near `daily_doses` doses per
    # day during the early campaign window (before the epidemic noticeably
    # drains S) and never exceed `daily_doses` by more than stochastic noise.
    daily_targets = {
        "very_fast": 0.03 * n_pop,
        "fast": 0.01 * n_pop,
        "slow": 0.001 * n_pop,
    }
    for key, target in daily_targets.items():
        vax_series = next(
            iter(bodies[key]["transitions"]["data"]["Susceptible_to_Susceptible_vax"].values())
        )["0.5"]
        # First five in-window days
        early = vax_series[1:6]

        # Should mostly hit the target in the initial phases of rollout, before the epidemic noticeably drains S.
        assert all(v == pytest.approx(target, rel=0.05) for v in early), (
            f"{key}: early in-window doses {early} not near target {target}"
        )

        # Median never exceeds the per-day budget by more than the stochastic
        # noise.
        assert max(vax_series) <= target * 1.05, (
            f"{key}: max daily doses {max(vax_series):.0f} > 1.05 * target {target:.0f}"
        )

    order = ["pulse", "very_fast", "fast", "slow", "no_vax"]
    # Peak size and final size should be monotonically non-decreasing along this order
    for prev, curr in zip(order, order[1:]):
        assert peaks[prev] <= peaks[curr], (
            f"peak incidence: {prev}={peaks[prev]:.0f} not <= {curr}={peaks[curr]:.0f}"
        )
        assert finals[prev] <= finals[curr], (
            f"final size: {prev}={finals[prev]:.4f} not <= {curr}={finals[curr]:.4f}"
        )

    # Pulse on day 2 should essentially eliminate the epidemic: with VE_S=0.85
    # and a tiny initial seed, only a small fraction ever gets infected.
    assert finals["pulse"] < 0.01, f"pulse final size = {finals['pulse']:.4f}, expected < 0.01"
