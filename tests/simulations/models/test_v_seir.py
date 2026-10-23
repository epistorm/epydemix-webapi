"""End-to-end tests for the V-SEIR preset.

Locks down compartment structure, default behavior, the parameter-conversion
chain (period inputs and R0 -> beta), and integration with the vaccination
block. Mirrors the V-SEIHR test suite minus the hospitalization-specific
cases.
"""

import pytest

from app.presets import PRESETS

_V_SEIR_COMPARTMENTS = [
    "Susceptible",
    "Susceptible_vax",
    "Exposed",
    "Exposed_vax",
    "Infected",
    "Infected_vax",
    "Recovered",
    "Recovered_vax",
]


def _baseline_request(**overrides):
    request = {
        "model": {
            "preset": "V-SEIR",
            "parameters": {
                "R0": 2.5,
                "incubation_period": 3.0,
                "infectious_period": 2.5,
                "VE_S": 0.7,
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


def test_v_seir_baseline(client):
    """V-SEIR preset runs with defaults and exposes all 8 compartments."""
    response = client.post("/api/v1/simulations", json=_baseline_request())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metadata"]["model"]["compartments"] == _V_SEIR_COMPARTMENTS


def test_v_seir_in_presets_endpoint(client):
    """`GET /models/presets` lists V-SEIR with the right compartments."""
    response = client.get("/api/v1/models/presets")
    assert response.status_code == 200
    presets = {p["name"]: p for p in response.json()["presets"]}
    assert "V-SEIR" in presets
    assert presets["V-SEIR"]["compartments"] == _V_SEIR_COMPARTMENTS


def test_v_seir_registry_consistency(client):
    """The registry, the presets endpoint, and the request literal agree."""
    response = client.get("/api/v1/models/presets")
    endpoint_names = {p["name"] for p in response.json()["presets"]}
    assert endpoint_names == set(PRESETS)


def test_v_seir_calc_params_exposed(client):
    """Preset-specific calc-params surface in `results.parameters`."""
    request = _baseline_request()
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    for name in (
        "transmission_rate",
        "transmission_rate_vax",
        "recovery_rate",
        "incubation_rate",
    ):
        assert name in params["data"], f"missing {name} in results.parameters"


def test_v_seir_VE_zero(client):
    """When VE_S is zero, vaccinated transmission rate equals unvaccinated."""
    request = _baseline_request()
    request["model"]["parameters"]["VE_S"] = 0.0

    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    first = next(iter(params["transmission_rate"]))

    assert params["transmission_rate_vax"][first][0] == pytest.approx(
        params["transmission_rate"][first][0], abs=1e-9
    )


def test_v_seir_waning_off_by_default(client):
    """Without `immunity_duration`, waning_rate stays at 0.0 and no R -> S transitions fire."""
    request = _baseline_request()
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200
    body = response.json()["results"]

    series = next(iter(body["parameters"]["data"]["waning_rate"].values()))
    assert series == pytest.approx([0.0] * len(series), abs=1e-12)

    totals = body["summary"]["totals"]
    for name in ("Recovered_to_Susceptible", "Recovered_vax_to_Susceptible_vax"):
        for age_data in totals[name].values():
            assert age_data["quantiles"]["0.5"] == 0.0, (
                f"{name} median = {age_data['quantiles']['0.5']}, expected 0"
            )


def test_v_seir_waning_enabled_via_immunity_duration(client):
    """`immunity_duration` injects `waning_rate = 1 / immunity_duration` and R -> S fires."""
    request = _baseline_request()
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

    series = next(iter(body["parameters"]["data"]["waning_rate"].values()))
    assert series == pytest.approx([1 / 30.0] * len(series), abs=1e-9)

    totals = body["summary"]["totals"]["Recovered_to_Susceptible"]
    medians = [age_data["quantiles"]["0.5"] for age_data in totals.values()]
    assert sum(medians) > 0, f"Recovered_to_Susceptible medians = {medians}"


def test_v_seir_with_vaccination_campaign(client):
    """Vaccination campaign on V-SEIR drives Susceptible_to_Susceptible_vax transitions."""
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
    totals = data["results"]["summary"]["totals"]["Susceptible_to_Susceptible_vax"]
    medians = [age_data["quantiles"]["0.5"] for age_data in totals.values()]
    assert sum(medians) > 0, f"Susceptible_to_Susceptible_vax medians = {medians}"

    assert data["metadata"]["vaccination"]["campaigns"][0]["rollout"]["daily_doses"] == 100_000


def test_v_seir_explicit_initial_conditions(client):
    """Explicit `initial_percentages` seeds Infected and keeps the _vax branch empty.

    Verifies the two contracts of method=percentage on V-SEIR:
      - The vaccinated branch stays at zero across the whole horizon (no
        vaccination block means no S -> S_vax transitions can fire).
      - The unvaccinated Infected compartment is non-empty at t=0 in every
        age group (the seed actually landed).
    """
    request = _baseline_request()
    request["initial_conditions"] = {
        "method": "percentage",
        "initial_percentages": {"Infected": 0.1},
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    compartments = response.json()["results"]["compartments"]["data"]

    # The entire _vax branch stays at zero for every age group and every step
    # (no vaccination block was supplied, so the S -> S_vax transition is
    # never wired in).
    for comp in ("Susceptible_vax", "Exposed_vax", "Infected_vax", "Recovered_vax"):
        for age_group, quantiles in compartments[comp].items():
            series = quantiles["0.5"]
            assert all(v == 0 for v in series), (
                f"{comp}[{age_group}] median is non-zero somewhere: {series}"
            )

    # The Infected seed lands in every age group (non-empty at t=0).
    for age_group, quantiles in compartments["Infected"].items():
        assert quantiles["0.5"][0] > 0, (
            f"Infected[{age_group}] at t=0 = {quantiles['0.5'][0]}, expected > 0"
        )


def test_v_seir_vaccination_metadata_surfaces_default_flows(client):
    """V-SEIR's defaulted Susceptible -> Susceptible_vax flow is echoed in metadata."""
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


def test_v_seir_summary_peaks_do_not_leak_vax_compartments(client):
    """Susceptible's per-age-group peaks must not include `Susceptible_vax` keys."""
    response = client.post("/api/v1/simulations", json=_baseline_request())
    assert response.status_code == 200, response.text

    peaks = response.json()["results"]["summary"]["peaks"]

    assert "Susceptible" in peaks
    assert "Susceptible_vax" in peaks

    expected_age_groups = {"0-4", "5-19", "20-49", "50-64", "65+", "total"}
    assert set(peaks["Susceptible"].keys()) == expected_age_groups
    assert set(peaks["Susceptible_vax"].keys()) == expected_age_groups

    for comp in ("Susceptible", "Exposed", "Infected", "Recovered"):
        for age_group in peaks[comp]:
            assert not age_group.startswith("vax_"), (
                f"{comp} peaks contain leaked _vax key: {age_group}"
            )


@pytest.mark.slow
def test_v_seir_vaccination_speed_orders_outcomes(client):
    """Faster rollout monotonically decreases both peak incidence and final size.

    Mirrors the V-SEIHR speed-ordering test minus hospitalization parameters.
    """
    n_pop = 1_000_000
    horizon = ("2025-01-01", "2025-08-31")
    base = {
        "model": {
            "preset": "V-SEIR",
            "parameters": {
                "R0": 2.5,
                "incubation_period": 3.0,
                "infectious_period": 2.5,
                "VE_S": 0.85,
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

    order = ["pulse", "very_fast", "fast", "slow", "no_vax"]
    for prev, curr in zip(order, order[1:]):
        assert peaks[prev] <= peaks[curr], (
            f"peak incidence: {prev}={peaks[prev]:.0f} not <= {curr}={peaks[curr]:.0f}"
        )
        assert finals[prev] <= finals[curr], (
            f"final size: {prev}={finals[prev]:.4f} not <= {curr}={finals[curr]:.4f}"
        )

    assert finals["pulse"] < 0.01, f"pulse final size = {finals['pulse']:.4f}, expected < 0.01"
