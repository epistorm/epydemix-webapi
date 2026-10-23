"""Request builders shared by parameter tests."""

_HOMOGENEOUS_POPULATION = {
    "source": "custom",
    "name": "homogeneous",
    "age_groups": {"all": 1_000_000},
    "contact_matrices": {"all": [[1.0]]},
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
