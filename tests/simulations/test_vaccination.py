"""End-to-end vaccination tests against custom models.

V-SEIHR is exercised separately in ``tests/test_simulations_v_seihr.py``.
Tests here verify validation paths and source/target resolution on a custom
2- or 3-compartment model with vaccinated twin compartments, with no
preset-default dependence.
"""

import pytest


def _custom_vax_model_request(**overrides):
    """Minimal custom S/S_vax/I model with vaccination wired explicitly."""
    request = {
        "model": {
            "compartments": ["S", "S_vax", "I"],
            "parameters": {
                "transmission_rate": 0.3,
                "recovery_rate": 0.0,
            },
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {
                    "source": "S_vax",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
            ],
        },
        "population": {
            "source": "custom",
            "name": "tiny",
            "age_groups": {"all": 1_000_000},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "Nsim": 5,
            "seed": 7,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {
                "S": [1_000_000],
                "S_vax": [0],
                "I": [0],
            },
        },
        "vaccination": {
            "flows": [{"source": "S", "target": "S_vax"}],
            "campaigns": [
                {
                    "start_date": "2025-01-05",
                    "end_date": "2025-01-15",
                    "rollout": {"type": "flat_count", "daily_doses": 10_000},
                }
            ],
        },
    }
    for key, value in overrides.items():
        request[key] = value
    return request


def test_vaccination_custom_model_runs(client):
    """Custom model with explicit source/target wires the vaccination flow end-to-end."""
    response = client.post("/api/v1/simulations", json=_custom_vax_model_request())
    assert response.status_code == 200, response.text
    data = response.json()
    assert "S_to_S_vax" in data["results"]["transitions"]["data"]


def test_vaccination_missing_flows_on_custom_model(client):
    """Custom models without preset defaults must supply `flows` explicitly."""
    request = _custom_vax_model_request()
    request["vaccination"].pop("flows")
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "flows" in detail


def test_vaccination_invalid_source_compartment(client):
    """Flow source must exist in the model; otherwise 422 names it."""
    request = _custom_vax_model_request()
    request["vaccination"]["flows"] = [{"source": "ghost", "target": "S_vax"}]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "ghost" in detail
    assert "source" in detail


def test_vaccination_invalid_target_compartment(client):
    """Flow target (when non-null) must exist in the model; otherwise 422 names it."""
    request = _custom_vax_model_request()
    request["vaccination"]["flows"] = [{"source": "S", "target": "phantom"}]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "phantom" in detail
    assert "target" in detail


def test_vaccination_flow_source_equals_target(client):
    """A self-loop S -> S inside a flow is a configuration error."""
    request = _custom_vax_model_request()
    request["vaccination"]["flows"] = [{"source": "S", "target": "S"}]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail_str = str(response.json()["detail"])
    assert "distinct" in detail_str


def test_vaccination_flows_must_have_one_target(client):
    """`flows` with no entry carrying a non-null target is rejected."""
    request = _custom_vax_model_request()
    request["vaccination"]["flows"] = [
        {"source": "S", "target": None},
        {"source": "S_vax", "target": None},
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail_str = str(response.json()["detail"])
    assert "target" in detail_str


def test_vaccination_flows_empty_list(client):
    """An empty `flows` list is rejected."""
    request = _custom_vax_model_request()
    request["vaccination"]["flows"] = []
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail_str = str(response.json()["detail"])
    assert "flows" in detail_str


def test_vaccination_flows_duplicate_source(client):
    """Duplicate `source` values across `flows` are rejected."""
    request = _custom_vax_model_request()
    request["vaccination"]["flows"] = [
        {"source": "S", "target": "S_vax"},
        {"source": "S", "target": None},
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail_str = str(response.json()["detail"])
    assert "unique" in detail_str


def test_vaccination_legacy_fields_rejected(client):
    """`source_compartment` / `target_compartment` were removed; sending them 422s."""
    request = _custom_vax_model_request()
    request["vaccination"]["source_compartment"] = "S"
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_vaccination_invalid_age_group(client):
    """Each label in `target_age_groups` must match an age group on the resolved population."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"][0]["target_age_groups"] = ["nonexistent"]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "nonexistent" in response.json()["detail"]


def test_vaccination_duplicate_target_age_groups(client):
    """`target_age_groups` must contain unique labels; duplicates are a 422."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"][0]["target_age_groups"] = ["all", "all"]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    # Pydantic validators raise during request parsing, so the detail is the
    # standard list-of-errors shape rather than a plain string.
    detail_str = str(response.json()["detail"])
    assert "unique" in detail_str


def test_vaccination_invalid_window(client):
    """A campaign with `end_date < start_date` is rejected at schema validation."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"][0]["end_date"] = "2024-01-01"
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_vaccination_empty_campaigns(client):
    """`vaccination` with an empty `campaigns` list is a 422 (block is present but vacuous)."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"] = []
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "campaigns" in response.json()["detail"]


def test_vaccination_window_outside_simulation(client):
    """Campaign window outside the simulation window should run cleanly with zero doses."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"][0]["start_date"] = "2030-01-01"
    request["vaccination"]["campaigns"][0]["end_date"] = "2030-01-31"
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text


def test_vaccination_invalid_rollout_type(client):
    """Unknown rollout discriminator should 422 via the Pydantic union."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"][0]["rollout"] = {
        "type": "ramp_count",
        "peak_daily_doses": 1000,
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_vaccination_metadata_echoed(client):
    """The resolved vaccination block is echoed back in `metadata.vaccination`."""
    response = client.post("/api/v1/simulations", json=_custom_vax_model_request())
    assert response.status_code == 200
    metadata = response.json()["metadata"]
    assert metadata["vaccination"]["flows"] == [{"source": "S", "target": "S_vax"}]
    assert len(metadata["vaccination"]["campaigns"]) == 1


def _dose_sink_request():
    """S + R compete for doses; only S -> S_vax fires. Matches epydemix tutorial 09.

    R starts large so the denominator is dominated by R; transitions per step
    should land near `daily_doses * S / (S + R)` rather than `daily_doses`.
    """
    # No model-level transitions: the vaccination block adds the only S -> S_vax
    # transition. Adding a rate-0 spontaneous S -> S_vax here would trigger the
    # upstream epydemix transitions_evolution double-counting bug (see
    # BUG-epydemix-transition-count-duplication.md).
    return {
        "model": {
            "compartments": ["S", "S_vax", "R"],
            "parameters": {"k": 0.0},
            "transitions": [],
        },
        "population": {
            "source": "custom",
            "name": "tiny",
            "age_groups": {"all": 1_000_000},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-15",
            "Nsim": 50,
            "seed": 11,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {"S": [200_000], "S_vax": [0], "R": [800_000]},
        },
        "vaccination": {
            "flows": [
                {"source": "S", "target": "S_vax"},
                {"source": "R", "target": None},
            ],
            "campaigns": [
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-15",
                    "rollout": {"type": "flat_count", "daily_doses": 10_000},
                }
            ],
        },
    }


def test_vaccination_dose_sink_rate_matches_S_over_S_plus_R(client):
    """Per-step S->S_vax expectation = daily_doses * S / (S + R) (dose competition with R)."""
    response = client.post("/api/v1/simulations", json=_dose_sink_request())
    assert response.status_code == 200, response.text
    data = response.json()
    transitions = data["results"]["transitions"]["data"]
    # Only the S -> S_vax transition should exist; R has no target so emits nothing.
    assert "S_to_S_vax" in transitions
    assert not any(key.startswith("R_to_") for key in transitions)

    quantile_data = next(iter(transitions["S_to_S_vax"].values()))
    median_key = "median" if "median" in quantile_data else "0.5"
    series = quantile_data[median_key]
    # Day-0 expectation: 10000 * 200000 / (200000 + 800000) = 2000.
    assert series[0] == pytest.approx(2000.0, rel=0.10)


def test_vaccination_dose_sink_reduces_S_to_S_vax_vs_no_sink(client):
    """Adding {R: null} as a sink must shrink S->S_vax vs the no-sink baseline.

    Same population, seed, and daily_doses; the only difference is the sink
    flow. With the sink, the denominator is S+R; without it, it's just S
    (so dose delivery is capped only by S itself). The ratio of medians on
    day 0 should track S / (S + R) = 0.2.
    """
    sink_request = _dose_sink_request()
    no_sink_request = _dose_sink_request()
    no_sink_request["vaccination"]["flows"] = [{"source": "S", "target": "S_vax"}]

    sink_resp = client.post("/api/v1/simulations", json=sink_request)
    no_sink_resp = client.post("/api/v1/simulations", json=no_sink_request)
    assert sink_resp.status_code == 200, sink_resp.text
    assert no_sink_resp.status_code == 200, no_sink_resp.text

    def _day0_median(resp):
        transitions = resp.json()["results"]["transitions"]["data"]["S_to_S_vax"]
        quantile_data = next(iter(transitions.values()))
        median_key = "median" if "median" in quantile_data else "0.5"
        return quantile_data[median_key][0]

    sink_day0 = _day0_median(sink_resp)
    no_sink_day0 = _day0_median(no_sink_resp)

    # Sanity: sink must strictly reduce vaccinations on day 0.
    assert sink_day0 < no_sink_day0
    # No-sink: denominator = S only, so the campaign delivers ~daily_doses.
    assert no_sink_day0 == pytest.approx(10_000.0, rel=0.10)
    # Sink ratio should track S / (S + R) = 0.2.
    assert sink_day0 / no_sink_day0 == pytest.approx(0.2, rel=0.15)


def _multi_target_request():
    """Single 1000-dose campaign vaccinating both S and S_2 with their own targets.

    Populations are scaled so `daily_doses / (S + S_2) << 1` and the binomial
    rate stays in the near-linear regime, so per-flow daily transitions track
    `daily_doses * S_i / (S + S_2)` to within a small stochastic margin.
    """
    # No model-level transitions: the vaccination block adds the only S -> S_vax
    # and S_2 -> S_2_vax transitions. See note in `_dose_sink_request` for why.
    return {
        "model": {
            "compartments": ["S", "S_vax", "S_2", "S_2_vax"],
            "parameters": {"k": 0.0},
            "transitions": [],
        },
        "population": {
            "source": "custom",
            "name": "tiny",
            "age_groups": {"all": 1_000_000},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-05",
            "Nsim": 100,
            "seed": 17,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {
                "S": [400_000],
                "S_vax": [0],
                "S_2": [600_000],
                "S_2_vax": [0],
            },
        },
        "vaccination": {
            "flows": [
                {"source": "S", "target": "S_vax"},
                {"source": "S_2", "target": "S_2_vax"},
            ],
            "campaigns": [
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-01",
                    "rollout": {"type": "flat_count", "daily_doses": 10_000},
                }
            ],
        },
    }


def test_vaccination_multi_target_proportional_to_live_pool(client):
    """Two paired sources sharing one budget: per-flow counts split proportional to S_i."""
    response = client.post("/api/v1/simulations", json=_multi_target_request())
    assert response.status_code == 200, response.text
    data = response.json()
    transitions = data["results"]["transitions"]["data"]
    assert "S_to_S_vax" in transitions
    assert "S_2_to_S_2_vax" in transitions

    def _day0_median(key: str) -> float:
        q = next(iter(transitions[key].values()))
        mk = "median" if "median" in q else "0.5"
        return float(q[mk][0])

    s_vax = _day0_median("S_to_S_vax")
    s2_vax = _day0_median("S_2_to_S_2_vax")
    # Linearized expectations: 10000 * 0.4 = 4000 and 10000 * 0.6 = 6000.
    # Binomial p = 1 - exp(-r * dt) with r = 10000/1_000_000 = 0.01 lands within
    # ~0.5% of the linearized value, well inside the stochastic slack below.
    assert s_vax == pytest.approx(4000.0, rel=0.05)
    assert s2_vax == pytest.approx(6000.0, rel=0.05)
    # Total respects the budget on average.
    assert s_vax + s2_vax == pytest.approx(10_000.0, rel=0.03)


def _coverage_cap_request(fraction: float = 0.3):
    """fixed_rate campaign with a coverage cap on S_vax."""
    return {
        "model": {
            "compartments": ["S", "S_vax"],
            "parameters": {"k": 0.0},
            "transitions": [],
        },
        "population": {
            "source": "custom",
            "name": "tiny",
            "age_groups": {"all": 1_000_000},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-02-28",
            "Nsim": 20,
            "seed": 29,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {"S": [1_000_000], "S_vax": [0]},
        },
        "vaccination": {
            "flows": [{"source": "S", "target": "S_vax"}],
            "campaigns": [
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-02-28",
                    "rollout": {"type": "fixed_rate", "rate": 0.05},
                    "coverage": {
                        "fraction": fraction,
                        "compartments": ["S_vax"],
                    },
                }
            ],
        },
        "output": {"include_trajectories": True},
    }


def test_coverage_cap_plateaus_at_threshold(client):
    """A coverage cap stops the campaign once vaccinated compartments reach the threshold."""
    fraction = 0.3
    initial_population = 1_000_000.0

    response = client.post("/api/v1/simulations", json=_coverage_cap_request(fraction))
    assert response.status_code == 200, response.text
    data = response.json()
    quantile_data = next(iter(data["results"]["compartments"]["data"]["S_vax"].values()))
    median_key = "median" if "median" in quantile_data else "0.5"
    s_vax_series = quantile_data[median_key]

    # Final S_vax should plateau at <= threshold + a small overshoot.
    threshold = fraction * initial_population

    # One-step overshoot bound: rate=0.05, sub-threshold S ~ 700k, so at most
    # ~35k could land in the last pre-cap step. Use a 10% slack.
    assert s_vax_series[-1] <= threshold * 1.1

    # And must be at least near the threshold (cap fires, doesn't stop early).
    assert s_vax_series[-1] >= threshold * 0.9


def test_coverage_cap_metadata_echoed(client):
    """metadata.vaccination round-trips the coverage block."""
    response = client.post("/api/v1/simulations", json=_coverage_cap_request(0.5))
    assert response.status_code == 200
    coverage = response.json()["metadata"]["vaccination"]["campaigns"][0]["coverage"]
    assert coverage["fraction"] == 0.5
    assert coverage["compartments"] == ["S_vax"]


def test_coverage_unknown_compartment_422(client):
    """coverage.compartments referencing an unknown compartment is rejected at the service."""
    request = _coverage_cap_request(0.5)
    request["vaccination"]["campaigns"][0]["coverage"]["compartments"] = ["S_vax", "phantom_vax"]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail_str = str(response.json()["detail"])
    assert "phantom_vax" in detail_str


def test_coverage_source_overlap_422(client):
    """coverage.compartments including a flow source is rejected (would cap at t=0)."""
    request = _coverage_cap_request(0.5)
    request["vaccination"]["campaigns"][0]["coverage"]["compartments"] = ["S"]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail_str = str(response.json()["detail"])
    assert "overlap" in detail_str.lower() or "source" in detail_str.lower()


def test_coverage_fraction_out_of_range_422(client):
    """coverage.fraction must be in (0, 1]."""
    request = _coverage_cap_request(1.5)
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_empty_target_age_groups_422(client):
    """An empty target_age_groups list is rejected at schema (min_length=1)."""
    request = _custom_vax_model_request()
    request["vaccination"]["campaigns"][0]["target_age_groups"] = []
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
