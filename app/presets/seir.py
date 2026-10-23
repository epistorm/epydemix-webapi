"""SEIR preset: model builder + registry definition."""

from __future__ import annotations

from epydemix.model.epimodel import EpiModel

from ..utils.parameter_conversions import ParameterConversion
from ._build import add_transitions


COMPARTMENTS: list[str] = ["Susceptible", "Exposed", "Infected", "Recovered"]

# ``R0`` is a source default: ``PARAMETER_CONVERSIONS`` below derives
# ``transmission_rate = R0 * recovery_rate / CONTACT_MATRIX_EIGENVALUE_ALL``
# from the chosen population's contact matrix. An explicit
# ``transmission_rate`` in the request wins and drops the ``R0`` default.
DEFAULT_PARAMETERS: dict[str, float] = {
    "R0": 2.5,
    "incubation_rate": 0.2,
    "recovery_rate": 0.1,
}

DESCRIPTION: str = (
    "Susceptible-Exposed-Infected-Recovered model. "
    "Includes an exposed/latent period before becoming infectious."
)

TRANSITIONS: list[dict] = [
    {
        "source": "Susceptible",
        "target": "Exposed",
        "kind": "mediated",
        "params": ["transmission_rate", "Infected"],
    },
    {
        "source": "Exposed",
        "target": "Infected",
        "kind": "spontaneous",
        "params": ["incubation_rate"],
    },
    {
        "source": "Infected",
        "target": "Recovered",
        "kind": "spontaneous",
        "params": ["recovery_rate"],
    },
]

# Friendlier source inputs the user can supply instead of the rate-form
# parameters above. Resolved by ``app.utils.parameter_conversions``.
PARAMETER_CONVERSIONS: dict[str, ParameterConversion] = {
    "incubation_rate": ParameterConversion("incubation_period", "1 / incubation_period"),
    "recovery_rate": ParameterConversion("infectious_period", "1 / infectious_period"),
    "transmission_rate": ParameterConversion(
        "R0", "R0 * recovery_rate / CONTACT_MATRIX_EIGENVALUE_ALL"
    ),
}


def build_seir_model(
    user_scalars: dict[str, float],
) -> tuple[EpiModel, dict[str, str]]:
    """Construct an SEIR model with user scalar overrides.

    Returns ``(model, preset_calc_params)``. Period→rate and R0→β are handled
    by ``app.utils.parameter_conversions``.
    """
    merged = {**DEFAULT_PARAMETERS, **user_scalars}
    model = EpiModel(compartments=COMPARTMENTS)
    for name, value in merged.items():
        model.add_parameter(parameter_name=name, value=float(value))

    add_transitions(model, TRANSITIONS)
    return model, {}
