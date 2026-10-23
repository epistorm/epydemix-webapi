"""Calculated (expression-valued) parameters in `model.parameters`."""

import pytest

_HOMOGENEOUS_POPULATION = {
    "source": "custom",
    "name": "homogeneous",
    "age_groups": {"all": 1_000_000},
    "contact_matrices": {"all": [[1.0]]},
}


_AGE_GROUP_MAPPING_5 = {
    "0-4": ["0-4"],
    "5-17": ["5-9", "10-14", "15-19"],
    "18-49": ["20-24", "25-29", "30-34", "35-39", "40-44", "45-49"],
    "50-64": ["50-54", "55-59", "60-64"],
    "65+": ["65-69", "70-74", "75+"],
}


def _custom_sir_request(parameters: dict) -> dict:
    """SIR custom model on a homogeneous population used as a substrate for exercising calculated params.

    Defines `S, I, R` with `S → I` mediated by `transmission_rate` and
    `I → R` spontaneous at `recovery_rate`. Both rate names must resolve
    in `model.parameters` (scalar, list, or calculated).
    """
    return {
        "model": {
            "compartments": ["S", "I", "R"],
            "parameters": parameters,
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {"source": "I", "target": "R", "kind": "spontaneous", "params": "recovery_rate"},
            ],
        },
        "population": dict(_HOMOGENEOUS_POPULATION),
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 2,
            "seed": 1,
        },
        "output": {"include_parameters": True},
    }


def test_calculated_param_simple_scalar(client):
    """A calculated scalar resolves to the expected product of source scalars.

    Transmission rate beta is calculated from R0 and recovery_rate via the canonical R0 -> beta conversion.
    """
    request = _custom_sir_request(
        {
            "R0": 2.5,
            "recovery_rate": 0.1,
            "transmission_rate": "R0 * recovery_rate",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"

    params = response.json()["results"]["parameters"]
    series = next(iter(params["data"]["transmission_rate"].values()))
    assert series[0] == pytest.approx(2.5 * 0.1, abs=1e-9)


def test_calculated_param_chained(client):
    """A calculated parameter that depends on another calculated parameter
    is evaluated in topological order, regardless of dict insertion order.

    Two-step chain that mirrors how a user might supply `R0` and
    `infectious_period` and derive both rates:
    - `recovery_rate = 1 / infectious_period` (first calc-param), then
    - `transmission_rate = R0 * recovery_rate` (second calc-param, referencing the first).

    The dict intentionally lists `transmission_rate` before its dependency
    `recovery_rate` to prove the topological sort doesn't rely on dict order.
    """
    request = _custom_sir_request(
        {
            "transmission_rate": "R0 * recovery_rate",
            "recovery_rate": "1 / infectious_period",
            "R0": 2.5,
            "infectious_period": 10.0,
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]

    recovery = next(iter(params["data"]["recovery_rate"].values()))
    beta = next(iter(params["data"]["transmission_rate"].values()))
    assert recovery[0] == pytest.approx(0.1, abs=1e-9)
    assert beta[0] == pytest.approx(2.5 * 0.1, abs=1e-9)


def test_calculated_param_with_age_varying_source(client):
    """A list-valued source flows through the expression as age-varying.

    Age-varying relative susceptibility: kids and elderly often have
    different per-contact infection risk than the general adult population
    (kids are less susceptible to many flu strains; elderly tend to be more).
    The user supplies `relative_susceptibility` as a length-N list and
    `transmission_rate = base_transmission * relative_susceptibility` becomes
    age-varying via numpy broadcasting.
    """
    susceptibilities = [0.5, 0.7, 1.0, 1.0, 1.2]
    base_transmission = 0.3
    request = _custom_sir_request(
        {
            "base_transmission": base_transmission,
            "relative_susceptibility": susceptibilities,
            "transmission_rate": "base_transmission * relative_susceptibility",
            "recovery_rate": 0.1,
        }
    )
    request["population"] = {
        "name": "United_States",
        "contacts_source": "prem_2021",
        "age_group_mapping": _AGE_GROUP_MAPPING_5,
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    beta = response.json()["results"]["parameters"]["data"]["transmission_rate"]
    age_keys = [k for k in beta if k != "total"]
    for ag, susceptibility in zip(age_keys, susceptibilities):
        assert beta[ag][0] == pytest.approx(base_transmission * susceptibility, abs=1e-9)


def test_calculated_param_composes_with_balcan(client):
    """A balcan transform on a scalar source produces a time-varying
    calculated parameter via numpy broadcasting.

    Seasonality goes on R0, and `transmission_rate = R0 * recovery_rate` is the calc-param that picks it up.
    """
    request = _custom_sir_request(
        {
            "R0": 2.5,
            "recovery_rate": 0.1,
            "transmission_rate": "R0 * recovery_rate",
        }
    )
    request["parameter_transforms"] = [
        {
            "target_parameter": "R0",
            "method": "balcan",
            "max_date": "2024-01-15",
            "min_date": "2024-07-15",
            "max_value": 1.0,
            "min_value": 0.5,
        }
    ]

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    beta = response.json()["results"]["parameters"]["data"]["transmission_rate"]
    series = next(iter(beta.values()))
    # The series should not be flat: balcan made R0 time-varying, and
    # `R0 * recovery_rate` therefore varies over time too.
    assert max(series) - min(series) > 1e-3


def test_calculated_param_composes_with_age_varying_plus_balcan(client):
    """Source is age-varying AND time-transformed; calculated output is (T, N).

    `transmission_rate = base_transmission * relative_susceptibility` carries
    an age-varying factor (`relative_susceptibility`) AND a seasonal one
    (balcan on `base_transmission`). The resulting transmission_rate is
    age-varying and time-varying. No eigenvalue involved: `base_transmission`
    is a direct per-contact rate, not an R0-to-beta conversion.
    """
    susceptibilities = [0.5, 0.7, 1.0, 1.0, 1.2]
    request = _custom_sir_request(
        {
            "base_transmission": 0.3,
            "relative_susceptibility": susceptibilities,
            "transmission_rate": "base_transmission * relative_susceptibility",
            "recovery_rate": 0.1,
        }
    )
    request["population"] = {
        "name": "United_States",
        "contacts_source": "prem_2021",
        "age_group_mapping": _AGE_GROUP_MAPPING_5,
    }
    # Extend the horizon so the balcan curve spans its full max-to-min range
    # (max_date 2024-01-15 to min_date 2024-07-15).
    request["simulation"]["end_date"] = "2024-07-31"
    request["parameter_transforms"] = [
        {
            "target_parameter": "base_transmission",
            "method": "balcan",
            "max_date": "2024-01-15",
            "min_date": "2024-07-15",
            "max_value": 1.0,
            "min_value": 0.5,
        }
    ]

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    beta = response.json()["results"]["parameters"]["data"]["transmission_rate"]
    age_keys = [k for k in beta if k != "total"]
    # Different age groups carry distinct transmission_rate series, in the
    # same ratio as their `relative_susceptibility`.
    base_first = beta[age_keys[0]][0]
    for ag, susceptibility in zip(age_keys, susceptibilities):
        ratio = beta[ag][0] / base_first
        assert ratio == pytest.approx(susceptibility / susceptibilities[0], abs=1e-9)
    # Each series is time-varying: balcan modulates `base_transmission` between
    # max_value=1.0 and min_value=0.5, so max/min approaches 2x.
    for ag in age_keys:
        s = beta[ag]
        assert max(s) / min(s) > 1.5


def test_calculated_param_undefined_name(client):
    """Referencing a name that is neither defined nor calculated → 422."""
    request = _custom_sir_request(
        {
            "transmission_rate": 0.3,
            "recovery_rate": "0.15 * epsilon",  # epsilon not defined
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "undefined name" in response.json()["detail"].lower()


def test_calculated_param_circular_dependency(client):
    """Mutually referencing expressions → 422 naming the cycle."""
    request = _custom_sir_request(
        {
            "transmission_rate": 0.3,
            "a": "b + 1",
            "b": "a + 1",
            "recovery_rate": "a * 0.1",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "circular" in detail
    assert "a" in detail and "b" in detail


def test_calculated_param_disallowed_call(client):
    """Function calls are rejected by the AST validator."""
    request = _custom_sir_request(
        {
            "x": 0.3,
            "transmission_rate": 0.3,
            "recovery_rate": "abs(x)",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "Call" in response.json()["detail"]


def test_calculated_param_disallowed_attribute(client):
    """Attribute access is rejected."""
    request = _custom_sir_request(
        {
            "x": 0.3,
            "transmission_rate": 0.3,
            "recovery_rate": "x.real",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "Attribute" in response.json()["detail"]


def test_calculated_param_disallowed_subscript(client):
    """Subscripts are rejected."""
    request = _custom_sir_request(
        {
            "x": 0.3,
            "transmission_rate": 0.3,
            "recovery_rate": "x[0]",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "Subscript" in response.json()["detail"]


def test_calculated_param_syntax_error(client):
    """Unparseable expressions surface as 422 with a clear message."""
    request = _custom_sir_request(
        {
            "R0": 2.5,
            "recovery_rate": 0.1,
            "transmission_rate": "((R0 * recovery_rate",  # unbalanced parentheses
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "transmission_rate" in response.json()["detail"]


def test_calculated_param_transform_target_accepted(client):
    """A `parameter_transforms` entry targeting a calculated parameter is accepted.
    (Previously the API rejected this with 422, but we changed to allow it.)
    """
    request = _custom_sir_request(
        {
            "R0": 2.5,
            "recovery_rate": 0.1,
            "transmission_rate": "R0 * recovery_rate",
        }
    )
    request["parameter_transforms"] = [
        {
            "target_parameter": "transmission_rate",  # Apply scaling on the calculated parameter 'transmission_rate'
            "method": "scale",
            "start_date": "2024-01-05",
            "end_date": "2024-01-10",
            "factor": 0.5,
        }
    ]
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    assert "transmission_rate" in params["data"]

    # Scaling should be applied only during the specified window
    dates = params["dates"]
    first_age_group = next(iter(params["data"]["transmission_rate"]))
    series = params["data"]["transmission_rate"][first_age_group]
    in_window = [v for d, v in zip(dates, series) if "2024-01-05" <= d <= "2024-01-10"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-01-05" or d > "2024-01-10"]

    assert in_window == pytest.approx(
        [0.125] * len(in_window), abs=1e-9
    )  # R0 * recovery_rate * 0.5
    assert out_of_window == pytest.approx(
        [0.25] * len(out_of_window), abs=1e-9
    )  # R0 * recovery_rate


def test_calculated_param_not_echoed_in_metadata(client):
    """`metadata` carries no new calculated-parameter field; expressions live
    only in the request and surface via `results.parameters` when requested."""
    request = _custom_sir_request(
        {
            "R0": 2.5,
            "recovery_rate": 0.1,
            "transmission_rate": "R0 * recovery_rate",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert "calculated_parameters" not in metadata
    # The evaluated value is still observable via include_parameters.
    assert "transmission_rate" in response.json()["results"]["parameters"]["data"]


def test_calculated_param_uses_reserved_eigenvalue(client):
    """R0 calibration via the reserved CONTACT_MATRIX_EIGENVALUE_ALL constant.

    Sets `R0` and derives `transmission_rate = R0 * gamma / eigenvalue`. The
    effective transmission_rate in `results.parameters` should match the
    closed-form value computed from the population's overall contact matrix.
    """
    request = _custom_sir_request(
        {
            "R0": 1.5,
            "gamma": 0.1,
            "recovery_rate": "gamma",
            "transmission_rate": "R0 * gamma / CONTACT_MATRIX_EIGENVALUE_ALL",
        }
    )

    # Use United_States population
    request["population"] = {"name": "United_States"}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    # Independently compute the expected eigenvalue from the same population.
    import numpy as np

    from app.services.population_service import _load_population_cached

    pop = _load_population_cached("United_States")
    summed = sum(np.asarray(m, dtype=float) for m in pop.contact_matrices.values())
    eigenvalue = float(np.max(np.abs(np.linalg.eigvals(summed))))
    expected_beta = 1.5 * 0.1 / eigenvalue

    series = next(
        iter(response.json()["results"]["parameters"]["data"]["transmission_rate"].values())
    )
    assert series[0] == pytest.approx(expected_beta, rel=1e-6)


def test_calculated_param_eigenvalue_match_hand_computable_matrix(client):
    """`CONTACT_MATRIX_EIGENVALUE_ALL` matches a hand-computable dominant
    eigenvalue, on a custom inline population.

    Matrix [[2, 1], [1, 2]] has eigenvalues 3 and 1; dominant is 3.
    Setting R0 = 3 and gamma = 0.1 should yield transmission_rate = 0.1
    (= R0 * gamma / eigenvalue = 3 * 0.1 / 3).
    """
    request = {
        "model": {
            "compartments": ["S", "I", "R"],
            "parameters": {
                "R0": 3.0,
                "gamma": 0.1,
                "recovery_rate": "gamma",
                "eigenval": "CONTACT_MATRIX_EIGENVALUE_ALL",  # dummy parameter to test reserved name in expression
                "transmission_rate": "R0 * gamma / CONTACT_MATRIX_EIGENVALUE_ALL",
            },
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {"source": "I", "target": "R", "kind": "spontaneous", "params": "recovery_rate"},
            ],
        },
        "population": {
            "source": "custom",
            "name": "EigenvalueTest",
            "age_groups": {"young": 50000, "old": 50000},
            "contact_matrices": {"all": [[2.0, 1.0], [1.0, 2.0]]},  # largest eigenvalue is 3.0
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-05",
            "Nsim": 2,
            "seed": 1,
        },
        "output": {"include_parameters": True},
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    series = next(
        iter(response.json()["results"]["parameters"]["data"]["transmission_rate"].values())
    )
    assert series[0] == pytest.approx(0.1, abs=1e-9)

    assert "eigenval" in response.json()["results"]["parameters"]["data"]
    eigen_series = next(iter(response.json()["results"]["parameters"]["data"]["eigenval"].values()))
    assert eigen_series[0] == 3.0


def test_calculated_param_eigenvalue_sums_across_layers(client):
    """`CONTACT_MATRIX_EIGENVALUE_ALL` sums layers before taking the eigenvalue,
    not the eigenvalue of any single layer.

    Two identity layers `[[1,0],[0,1]]` sum to `[[2,0],[0,2]]`, dominant
    eigenvalue 2 (would be 1 if only one layer were used). Setting
    R0 = 2 and gamma = 0.1 yields transmission_rate = 0.1.
    """
    request = {
        "model": {
            "compartments": ["S", "I", "R"],
            "parameters": {
                "R0": 2.0,
                "gamma": 0.1,
                "recovery_rate": "gamma",
                "eigenval": "CONTACT_MATRIX_EIGENVALUE_ALL",  # dummy parameter to test reserved name in expression
                "transmission_rate": "R0 * gamma / CONTACT_MATRIX_EIGENVALUE_ALL",
            },
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {"source": "I", "target": "R", "kind": "spontaneous", "params": "recovery_rate"},
            ],
        },
        "population": {
            "source": "custom",
            "name": "MultiLayerTest",
            "age_groups": {"a": 50000, "b": 50000},
            "contact_matrices": {
                "home": [[1.0, 0.0], [0.0, 1.0]],
                "work": [[1.0, 0.0], [0.0, 1.0]],
            },  # the summed matrix has eigen value 2.0
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-05",
            "Nsim": 2,
            "seed": 1,
        },
        "output": {"include_parameters": True},
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    series = next(
        iter(response.json()["results"]["parameters"]["data"]["transmission_rate"].values())
    )
    # The summed eigenvalue is 2, so transmission_rate = 0.1 (= 2.0 * 0.1 / 2.0).
    assert series[0] == pytest.approx(0.1, abs=1e-9)

    assert "eigenval" in response.json()["results"]["parameters"]["data"]
    eigen_series = next(iter(response.json()["results"]["parameters"]["data"]["eigenval"].values()))
    assert eigen_series[0] == 2.0


def test_calculated_param_reserved_name_collision_rejected(client):
    """A user parameter named like a reserved constant → 422."""
    request = _custom_sir_request(
        {
            "transmission_rate": 0.3,
            "recovery_rate": 0.1,
            "CONTACT_MATRIX_EIGENVALUE_ALL": 5.0,  # This would collide with reserved parameter
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "CONTACT_MATRIX_EIGENVALUE_ALL" in detail
    assert "reserved" in detail.lower()


def test_calculated_param_reserved_value_not_in_results(client):
    """Reserved names exist only in the eval namespace, not in `results.parameters`."""
    request = _custom_sir_request(
        {
            "R0": 1.5,
            "gamma": 0.1,
            "recovery_rate": "gamma",
            "transmission_rate": "R0 * gamma / CONTACT_MATRIX_EIGENVALUE_ALL",
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    data = response.json()["results"]["parameters"]["data"]
    assert "CONTACT_MATRIX_EIGENVALUE_ALL" not in data
    # The downstream calculated value, however, *is* stored and visible.
    assert "transmission_rate" in data


def test_calculated_param_drives_simulation_equivalently_to_scalar(client):
    """End-to-end: a calculated `a = 2 * b` (b=0.05) drives a simple decay
    model `dX/dt = -aX` identically to a scalar `a = 0.1`.

    With a fixed seed, every stochastic draw is the same, so trajectories
    must match bit-for-bit. Compares this against the deterministic
    closed-form expectation `E[X(t)] = X(0) * exp(-a*t)` as a sanity check
    that the rate is actually being applied (not just stored).
    """

    def make_request(params: dict) -> dict:
        return {
            "model": {
                "compartments": ["X", "Y"],
                "parameters": params,
                "transitions": [
                    {"source": "X", "target": "Y", "kind": "spontaneous", "params": ["a"]},
                ],
            },
            "population": {
                "source": "custom",
                "name": "DecayTest",
                "age_groups": {"all": 100000},
                "contact_matrices": {"all": [[1.0]]},
            },
            "initial_conditions": {
                "method": "absolute",
                "compartments": {"X": [100000], "Y": [0]},
            },
            "simulation": {
                "start_date": "2024-01-01",
                "end_date": "2024-04-01",
                "Nsim": 30,
                "seed": 42,
                "dt": 1.0,
            },
            "output": {
                "include_trajectories": True,
                "age_groups": ["total"],
            },
        }

    # Precalculated: a=0.1
    scalar = client.post("/api/v1/simulations", json=make_request({"a": 0.1})).json()
    # Calculated from expression: a = 2 * 0.5 = 0.1
    calc = client.post("/api/v1/simulations", json=make_request({"b": 0.05, "a": "2 * b"})).json()
    assert scalar["status"] == "completed", scalar
    assert calc["status"] == "completed", calc

    # Each pair of n-th run from each simulation should have bit-identical trajectories: same seed, same effective rate.
    s_runs = scalar["results"]["trajectories"]["runs"]
    c_runs = calc["results"]["trajectories"]["runs"]
    assert len(s_runs) == len(c_runs) == 30
    for s_run, c_run in zip(s_runs, c_runs):
        for comp in ("X", "Y"):
            assert s_run["compartments"][comp]["total"] == c_run["compartments"][comp]["total"]

    # Closed-form sanity: ensemble mean of X at the final step should be
    # close to X(0) * exp(-a*t). t = (end - start) in days, here 91 days.
    import numpy as np

    a = 0.1
    t_days = (np.datetime64("2024-04-01") - np.datetime64("2024-01-01")).astype(int)
    expected = 100000.0 * np.exp(-a * t_days)
    finals = [run["compartments"]["X"]["total"][-1] for run in s_runs]
    observed = float(np.mean(finals))
    assert observed == pytest.approx(expected, rel=0.30), (observed, expected)


def test_seir_vax_end_to_end(client):
    """Small SEIR + vaccinated branch model with one calculated rate.

    Compartments: S, E, I, R, Sv, Ev, Iv, Rv. Vaccinated transmission rate
    is `(1 - VE_S) * transmission_rate`. Force of infection across both
    branches is encoded via parallel mediated transitions on `I` and `Iv`.
    """
    request = {
        "model": {
            "compartments": ["S", "E", "I", "R", "Sv", "Ev", "Iv", "Rv"],
            "parameters": {
                "transmission_rate": 0.3,
                "sigma": 0.2,
                "gamma": 0.1,
                "nu": 0.005,
                "VE_S": 0.5,
                "transmission_rate_v": "(1 - VE_S) * transmission_rate",
            },
            "transitions": [
                {"source": "S", "target": "Sv", "kind": "spontaneous", "params": ["nu"]},
                {
                    "source": "S",
                    "target": "E",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {
                    "source": "S",
                    "target": "E",
                    "kind": "mediated",
                    "params": ["transmission_rate", "Iv"],
                },
                {
                    "source": "Sv",
                    "target": "Ev",
                    "kind": "mediated",
                    "params": ["transmission_rate_v", "I"],
                },
                {
                    "source": "Sv",
                    "target": "Ev",
                    "kind": "mediated",
                    "params": ["transmission_rate_v", "Iv"],
                },
                {"source": "E", "target": "I", "kind": "spontaneous", "params": ["sigma"]},
                {"source": "I", "target": "R", "kind": "spontaneous", "params": ["gamma"]},
                {"source": "Ev", "target": "Iv", "kind": "spontaneous", "params": ["sigma"]},
                {"source": "Iv", "target": "Rv", "kind": "spontaneous", "params": ["gamma"]},
            ],
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 2,
            "seed": 1,
        },
        "output": {"include_parameters": True},
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"

    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["transmission_rate_v"].values()))
    assert series[0] == pytest.approx(0.5 * 0.3, abs=1e-9)


# -- Preset-scoped parameter conversions (period -> rate, R0 -> beta) ----------


def _preset_request(preset: str, parameters: dict) -> dict:
    return {
        "model": {"preset": preset, "parameters": parameters},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 2,
            "seed": 7,
        },
        "output": {"include_parameters": True},
    }


def test_sir_infectious_period_drives_recovery_rate(client):
    """`infectious_period: 7.0` on SIR injects `recovery_rate = 1/7` as a calc-param."""
    response = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"infectious_period": 7.0, "transmission_rate": 0.3}),
    )
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["recovery_rate"].values()))
    assert series == pytest.approx([1 / 7.0] * len(series), abs=1e-12)


def test_sir_period_inputs_match_explicit_rate(client):
    """Period-style and rate-style inputs produce identical trajectories with the same seed."""
    period_resp = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"infectious_period": 7.0, "transmission_rate": 0.3}),
    )
    rate_resp = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"recovery_rate": 1 / 7.0, "transmission_rate": 0.3}),
    )
    assert period_resp.status_code == rate_resp.status_code == 200

    period_infected = period_resp.json()["results"]["compartments"]["data"]["Infected"]
    rate_infected = rate_resp.json()["results"]["compartments"]["data"]["Infected"]
    # Same seed = identical trajectories across every age group and every quantile.
    assert period_infected == rate_infected


def test_sir_R0_drives_transmission_rate(client):
    """`R0: 2.5` injects `transmission_rate = R0 * recovery_rate / eig(C)`."""
    response = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"R0": 2.5, "recovery_rate": 0.1}),
    )
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["transmission_rate"].values()))
    # Non-zero, finite values; exact value depends on the contact-matrix eigenvalue.
    assert series[0] > 0
    assert series[0] == series[-1]  # scalar source, no time variation


_TWO_GROUP_POPULATION = {
    "source": "custom",
    "name": "TwoGroups",
    "age_groups": {"young": 50_000, "old": 50_000},
    "contact_matrices": {"all": [[2.0, 1.0], [1.0, 2.0]]},
}

_TWO_LAYER_POPULATION = {
    "source": "custom",
    "name": "TwoLayers",
    "age_groups": {"a": 30_000, "b": 50_000, "c": 20_000},
    "contact_matrices": {
        "home": [[3.0, 1.0, 0.5], [1.0, 2.0, 0.2], [0.5, 0.2, 1.0]],
        "work": [[0.5, 2.0, 0.0], [2.0, 6.0, 0.1], [0.0, 0.1, 0.3]],
    },
}


def _calculate_dominant_eigenvalue(population: dict) -> float:
    import numpy as np

    summed = sum(np.asarray(m, dtype=float) for m in population["contact_matrices"].values())
    return float(np.max(np.abs(np.linalg.eigvals(summed))))


def _get_effective_rates(client, preset: str, population: dict, parameters: dict) -> dict:
    request = _preset_request(preset, parameters)
    request["population"] = population
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed", body.get("error")
    parameter_data = body["results"]["parameters"]["data"]
    return {name: next(iter(series.values()))[0] for name, series in parameter_data.items()}


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
@pytest.mark.parametrize("population", [_TWO_GROUP_POPULATION, _TWO_LAYER_POPULATION])
def test_basic_preset_defaults_give_R0_2_5(client, preset, population):
    """With no parameters, the derived beta gives R0 = beta * rho(C) / mu = 2.5 on any matrix."""
    rates = _get_effective_rates(client, preset, population, {})
    eigenvalue = _calculate_dominant_eigenvalue(population)
    assert rates["recovery_rate"] == pytest.approx(0.1, abs=1e-12)
    assert rates["transmission_rate"] == pytest.approx(2.5 * 0.1 / eigenvalue, rel=1e-9)
    effective_R0 = rates["transmission_rate"] * eigenvalue / rates["recovery_rate"]
    assert effective_R0 == pytest.approx(2.5, rel=1e-9)
    if preset == "SEIR":
        assert rates["incubation_rate"] == pytest.approx(0.2, abs=1e-12)


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
def test_basic_preset_explicit_transmission_rate_wins_over_default_R0(client, preset):
    """An explicit `transmission_rate` stands as given; the default `R0` is dropped."""
    rates = _get_effective_rates(client, preset, _TWO_LAYER_POPULATION, {"transmission_rate": 0.3})
    assert rates["transmission_rate"] == pytest.approx(0.3, abs=1e-12)
    assert "R0" not in rates


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
def test_basic_preset_explicit_R0_and_infectious_period(client, preset):
    """User `R0` and `infectious_period` replace the defaults in the beta conversion."""
    population = _TWO_LAYER_POPULATION
    eigenvalue = _calculate_dominant_eigenvalue(population)

    rates = _get_effective_rates(client, preset, population, {"R0": 1.5})
    # 0.1 is the default recovery_rate for the SIR, SEIR, and SIS presets.
    assert rates["transmission_rate"] == pytest.approx(1.5 * 0.1 / eigenvalue, rel=1e-9)

    rates = _get_effective_rates(client, preset, population, {"infectious_period": 5.0})
    assert rates["recovery_rate"] == pytest.approx(0.2, abs=1e-12)
    assert rates["transmission_rate"] == pytest.approx(2.5 * 0.2 / eigenvalue, rel=1e-9)


def test_both_passed_derived_wins(client):
    """Passing both `infectious_period` and `recovery_rate`: the derived (rate) wins."""
    response = client.post(
        "/api/v1/simulations",
        json=_preset_request(
            "SIR", {"infectious_period": 7.0, "recovery_rate": 0.5, "transmission_rate": 0.3}
        ),
    )
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["recovery_rate"].values()))
    # User scalar `recovery_rate: 0.5` should stand, not the conversion `1/7`.
    assert series == pytest.approx([0.5] * len(series), abs=1e-12)
    # `infectious_period` source scalar should have been popped from model.parameters.
    assert "infectious_period" not in params


def test_custom_model_no_implicit_period_conversion(client):
    """Custom models opt out of period-to-rate conversion.

    Even with `infectious_period` supplied, no `recovery_rate` calc-param
    is injected: the conversion is preset-scoped.
    `infectious_period` is just an unused parameter name; nothing implicit happens.
    """
    request = _custom_sir_request(
        {
            "infectious_period": 7.0,  # This is would not be converted to recovery rate in a custom model. Remains unused.
            "transmission_rate": 0.3,
            "recovery_rate": 0.1,  # supplied explicitly
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]

    # User scalar wins; the conversion is opted out in custom model, so `recovery_rate` stays at 0.1.
    series = next(iter(params["recovery_rate"].values()))
    assert series == pytest.approx([0.1] * len(series), abs=1e-12)

    # `infectious_period` is present but unused: NOT consumed by any conversion.
    assert "infectious_period" in params


def test_custom_model_explicit_period_to_rate_calc_param(client):
    """Custom models can opt INTO the period-to-rate conversion explicitly.

    Complement of `test_custom_model_no_implicit_period_conversion`: the
    preset-scoped resolver doesn't fire for custom models, but a user can
    write the same expression as a calc-param. The general calc-param
    machinery evaluates it regardless of preset.
    """
    request = _custom_sir_request(
        {
            "infectious_period": 7.0,
            "transmission_rate": 0.3,
            "recovery_rate": "1 / infectious_period",  # explicit user calc-param
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["recovery_rate"].values()))
    assert series == pytest.approx([1 / 7.0] * len(series), abs=1e-12)


def test_source_override_propagates_through_calc_param(client):
    """An `override` transform on a source parameter flows through expressions that reference it."""
    request = _custom_sir_request(
        {"a": 1.0, "b": "a * 2", "transmission_rate": 0.3, "recovery_rate": 0.1}
    )
    # Override `a` to 5.0 during 2024-01-10 to 2024-01-20. During that window, `b` should be 10.0; outside it should be 2.0.
    request["parameter_transforms"] = [
        {
            "target_parameter": "a",
            "method": "override",
            "start_date": "2024-01-10",
            "end_date": "2024-01-20",
            "value": 5.0,
        }
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    dates = params["dates"]

    # Extract the value of `b` over time, which should reflect the override on `a` during the specified window.
    series = next(iter(params["data"]["b"].values()))

    in_window = [v for d, v in zip(dates, series) if "2024-01-10" <= d <= "2024-01-20"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-01-10" or d > "2024-01-20"]

    # `b` is 10.0 during the window (5.0 * 2), and 2.0 outside the window (1.0 * 2)
    assert in_window == pytest.approx([10.0] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([2.0] * len(out_of_window), abs=1e-9)
