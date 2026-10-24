"""HTTP status codes for invalid input and failed simulation runs."""

import copy

import pytest

ENDPOINTS = ["/api/v1/simulations", "/api/v1/simulations/export/python"]

BASE = {
    "model": {"preset": "SIR"},
    "population": {
        "source": "custom",
        "name": "tiny",
        "age_groups": {"all": 1000},
        "contact_matrices": {"all": [[1.0]]},
    },
    "simulation": {"start_date": "2025-01-01", "end_date": "2025-01-31", "Nsim": 1},
}
WINDOW = {"start_date": "2025-01-05", "end_date": "2025-01-10"}


def _request(**sections):
    request = copy.deepcopy(BASE)
    for key, value in sections.items():
        if isinstance(value, dict) and isinstance(request.get(key), dict):
            request[key] = {**request[key], **value}
        else:
            request[key] = value
    return request


INVALID = {
    # 2025-02-30 is invalid because February has no 30th day.
    "nonexistent_date": _request(simulation={"start_date": "2025-02-30"}),
    # 2025/01/31 uses slashes instead of the required YYYY-MM-DD format.
    "slash_date": _request(simulation={"end_date": "2025/01/31"}),
    # 2025-1-31 is invalid because the month must be zero-padded.
    "unpadded_date": _request(simulation={"end_date": "2025-1-31"}),
    # 2025-02-01 is after the default end date of 2025-01-31.
    "reversed_period": _request(simulation={"start_date": "2025-02-01"}),
    # A same-day run with dt=1 has only 1 time step; at least 3 are required.
    "same_day": _request(simulation={"end_date": "2025-01-01"}),
    # A two-day run with dt=1 has only 2 time steps; at least 3 are required.
    "two_days": _request(simulation={"end_date": "2025-01-02"}),
    # The intervention ends on 2025-01-05 before it starts on 2025-01-10.
    "intervention_reversed": _request(
        interventions=[
            {
                "layer_name": "all",
                "start_date": "2025-01-10",
                "end_date": "2025-01-05",
                "reduction_factor": 0.5,
            }
        ]
    ),
    # 2025-13-01 is invalid because month 13 does not exist.
    "intervention_bad_date": _request(
        interventions=[
            {**WINDOW, "layer_name": "all", "end_date": "2025-13-01", "reduction_factor": 0.5}
        ]
    ),
    # 2025-01-32 is invalid because January has no 32nd day.
    "scale_bad_date": _request(
        parameter_transforms=[
            {
                **WINDOW,
                "method": "scale",
                "target_parameter": "transmission_rate",
                "start_date": "2025-01-32",
                "factor": 0.5,
            }
        ]
    ),
    # Jan 15 2025 does not match the required YYYY-MM-DD format.
    "balcan_bad_date": _request(
        parameter_transforms=[
            {
                "method": "balcan",
                "target_parameter": "transmission_rate",
                "max_date": "Jan 15 2025",
                "min_value": 0.5,
            }
        ]
    ),
    # 2025-02-29 is invalid because 2025 is not a leap year.
    "campaign_bad_date": _request(
        model={"preset": "V-SEIR"},
        vaccination={
            "campaigns": [
                {
                    **WINDOW,
                    "end_date": "2025-02-29",
                    "rollout": {"type": "flat_count", "daily_doses": 10},
                }
            ]
        },
    ),
    # Infectious is not a SIR compartment; the correct name is Infected.
    "initial_percentage_typo": _request(
        initial_conditions={"initial_percentages": {"Infectious": 1}}
    ),
    # Infectious is not a SIR compartment; the correct name is Infected.
    "initial_absolute_typo": _request(
        initial_conditions={
            "method": "absolute",
            "compartments": {"Susceptible": [990], "Infectious": [10]},
        }
    ),
}

VALID = {
    "three_days": _request(simulation={"end_date": "2025-01-03"}),
    "same_day_subdaily": _request(simulation={"end_date": "2025-01-01", "dt": 0.5}),
    "initial_conditions": _request(initial_conditions={"initial_percentages": {"Infected": 1}}),
}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("case", INVALID)
def test_invalid_input_is_422(client, endpoint, case):
    response = client.post(endpoint, json=INVALID[case])
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("case", VALID)
def test_valid_input_is_accepted(client, endpoint, case):
    response = client.post(endpoint, json=VALID[case])
    assert response.status_code == 200, response.text


def test_initial_compartment_error_names_model_compartments(client):
    response = client.post("/api/v1/simulations", json=INVALID["initial_percentage_typo"])
    message = str(response.json()["detail"])
    assert "Infectious" in message
    assert "Infected" in message


def test_population_timeout_is_504(client, monkeypatch):
    from app.services import population_service
    from app.services.population_service import PopulationLoadTimeoutError

    def timeout(*args, **kwargs):
        raise PopulationLoadTimeoutError("United_States", 1)

    monkeypatch.setattr(population_service, "get_simulation_population", timeout, raising=False)
    response = client.post("/api/v1/simulations", json=BASE)
    assert response.status_code == 504, response.text


def _broken_worker(connection, request, population):
    connection.send(("error", "RuntimeError: secret internal failure"))
    connection.close()


def test_internal_error_is_500_without_details(client, monkeypatch, caplog):
    from app.services import simulation_runtime

    monkeypatch.setattr(simulation_runtime, "_simulate", _broken_worker)
    response = client.post("/api/v1/simulations", json=BASE)
    assert response.status_code == 500
    assert "secret" not in response.text
    assert "secret internal failure" in caplog.text


@pytest.mark.parametrize("stage", ["engine", "results"])
def test_internal_value_errors_are_not_client_input_errors(monkeypatch, stage):
    from epydemix.model.epimodel import EpiModel

    from app.api.v1.schemas.simulation import SimulationRequest
    from app.services import simulation_service

    def broken(*args, **kwargs):
        raise ValueError("secret internal failure")

    if stage == "engine":
        monkeypatch.setattr(EpiModel, "run_simulations", broken)
    else:
        monkeypatch.setattr(simulation_service, "process_results", broken)
    with pytest.raises(RuntimeError, match="execution or result processing") as error:
        simulation_service.run_simulation(SimulationRequest.model_validate(BASE))
    assert isinstance(error.value.__cause__, ValueError)
