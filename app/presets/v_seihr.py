"""V-SEIHR preset: vaccinated/unvaccinated parallel-compartment SEIHR.

Every compartment has a vaccinated twin (``X_vax``). Vaccine efficacy reduces
susceptibility (``VE_S``, applied to the force-of-infection on the vaccinated
branch) and severity (``VE_H``, applied to the hospitalization split for
vaccinated infected individuals). Vaccinated infectious individuals carry the
*same* per-contact transmissibility as unvaccinated.

The ``vaccination`` request block drives ``Susceptible → Susceptible_vax``.
Both branches share the rate-form parameters (``incubation_rate``,
``recovery_rate``, ``hosp_recovery_rate``, ``waning_rate``); the VE twins
``transmission_rate_vax`` and ``hosp_proportion_vax`` are calculated from the
unvaccinated values via ``(1 - VE)``.
"""

from __future__ import annotations

import numpy as np
from epydemix.model.epimodel import EpiModel

from ..utils.parameter_conversions import ParameterConversion
from ._build import add_transitions

DESCRIPTION: str = (
    "Vaccinated SEIHR model with parallel unvaccinated/vaccinated compartments. "
    "Vaccine efficacy reduces susceptibility (VE_S) and severity (VE_H). Use "
    "with the `vaccination` block to drive doses from Susceptible to "
    "Susceptible_vax."
)


COMPARTMENTS: list[str] = [
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


# Defaults. Periods are in days; ``hosp_proportion`` / VE are unitless in
# [0, 1]; ``R0`` is unitless.
#
# ``hosp_proportion`` is age-stratified: five bins matching the default
# ``United_States`` population (prem-style 5-group split). Pass a scalar to
# collapse to homogeneous behavior, or a length-N list when running against
# a population with a different number of age groups.
#
# Waning is OFF by default (``waning_rate: 0.0``). Pass ``immunity_duration``
# in the request to enable; the parameter-conversion resolver then injects
# ``waning_rate = 1 / immunity_duration`` as a calculated parameter and the
# scalar default is dropped.
DEFAULT_PARAMETERS: dict[str, float | list[float]] = {
    "R0": 2.5,
    "incubation_period": 3.0,
    "infectious_period": 2.5,
    "hosp_duration": 5.0,
    "waning_rate": 0.0,
    "hosp_proportion": [0.002, 0.005, 0.015, 0.05, 0.18],
    "VE_S": 0.7,
    "VE_H": 0.85,
}


TRANSITIONS: list[dict] = [
    {
        "source": "Susceptible",
        "target": "Exposed",
        "kind": "mediated",
        "params": ["transmission_rate", "Infected"],
    },
    {
        "source": "Susceptible",
        "target": "Exposed",
        "kind": "mediated",
        "params": ["transmission_rate", "Infected_vax"],
    },
    {
        "source": "Exposed",
        "target": "Infected",
        "kind": "spontaneous",
        "params": ["incubation_rate"],
    },
    {"source": "Infected", "target": "Recovered", "kind": "spontaneous", "params": ["I_to_R_rate"]},
    {
        "source": "Infected",
        "target": "Hospitalized",
        "kind": "spontaneous",
        "params": ["I_to_H_rate"],
    },
    {
        "source": "Hospitalized",
        "target": "Recovered",
        "kind": "spontaneous",
        "params": ["hosp_recovery_rate"],
    },
    {
        "source": "Recovered",
        "target": "Susceptible",
        "kind": "spontaneous",
        "params": ["waning_rate"],
    },
    {
        "source": "Susceptible_vax",
        "target": "Exposed_vax",
        "kind": "mediated",
        "params": ["transmission_rate_vax", "Infected"],
    },
    {
        "source": "Susceptible_vax",
        "target": "Exposed_vax",
        "kind": "mediated",
        "params": ["transmission_rate_vax", "Infected_vax"],
    },
    {
        "source": "Exposed_vax",
        "target": "Infected_vax",
        "kind": "spontaneous",
        "params": ["incubation_rate"],
    },
    {
        "source": "Infected_vax",
        "target": "Recovered_vax",
        "kind": "spontaneous",
        "params": ["Ivax_to_R_rate"],
    },
    {
        "source": "Infected_vax",
        "target": "Hospitalized_vax",
        "kind": "spontaneous",
        "params": ["Ivax_to_H_rate"],
    },
    {
        "source": "Hospitalized_vax",
        "target": "Recovered_vax",
        "kind": "spontaneous",
        "params": ["hosp_recovery_rate"],
    },
    {
        "source": "Recovered_vax",
        "target": "Susceptible_vax",
        "kind": "spontaneous",
        "params": ["waning_rate"],
    },
]


# Friendlier source inputs the user can supply instead of the rate-form
# defaults. Resolved by ``app.utils.parameter_conversions``.
PARAMETER_CONVERSIONS: dict[str, ParameterConversion] = {
    "incubation_rate": ParameterConversion("incubation_period", "1 / incubation_period"),
    "recovery_rate": ParameterConversion("infectious_period", "1 / infectious_period"),
    "hosp_recovery_rate": ParameterConversion("hosp_duration", "1 / hosp_duration"),
    "waning_rate": ParameterConversion("immunity_duration", "1 / immunity_duration"),
    "transmission_rate": ParameterConversion(
        "R0", "R0 * recovery_rate / CONTACT_MATRIX_EIGENVALUE_ALL"
    ),
}


# V-SEIHR-specific calc-params (vaccine-efficacy twins and the
# I → R / I → H competing-exit composites). Users can override any of these
# by passing a matching name in ``parameters``; user-supplied calc-params
# win on collision (see ``create_model`` merge order).
PRESET_CALC_PARAMETERS: dict[str, str] = {
    # Vaccine-efficacy twins.
    "transmission_rate_vax": "(1 - VE_S) * transmission_rate",
    "hosp_proportion_vax": "(1 - VE_H) * hosp_proportion",
    # Competing-exit composites: I → R or H split by ``hosp_proportion``,
    # both exit at rate ``recovery_rate`` (no separate "time to hospitalization").
    "I_to_R_rate": "(1 - hosp_proportion) * recovery_rate",
    "I_to_H_rate": "hosp_proportion * recovery_rate",
    "Ivax_to_R_rate": "(1 - hosp_proportion_vax) * recovery_rate",
    "Ivax_to_H_rate": "hosp_proportion_vax * recovery_rate",
}


def default_initial_conditions(model: EpiModel) -> dict[str, np.ndarray]:
    """Sensible default initial conditions for V-SEIHR.

    Seeds ~0.05% of each age group split evenly between ``Exposed`` and
    ``Infected`` (~0.025% each) and puts the rest into ``Susceptible``; all
    other compartments (including the ``_vax`` branch) start at zero. This
    overrides epydemix's built-in default, which mis-splits the population
    for V-SEIHR-style models because the two parallel mediated transitions
    (S→E by I/I_vax and S_vax→E_vax by I/I_vax) inflate the source/agent
    compartment lists and leave ~50% of the population in ``Susceptible_vax``
    at t=0.
    """
    pop_per_group = np.array(model.population.Nk, dtype=float)
    seed_count = pop_per_group * 0.00025
    susceptible_count = pop_per_group - 2 * seed_count
    conditions = {comp: np.zeros_like(pop_per_group) for comp in COMPARTMENTS}
    conditions["Susceptible"] = susceptible_count
    conditions["Exposed"] = seed_count
    conditions["Infected"] = seed_count
    return conditions


def build_v_seihr_model(
    user_scalars: dict[str, float],
) -> tuple[EpiModel, dict[str, str]]:
    """Construct the V-SEIHR model.

    Returns ``(model, preset_calc_params)``. The preset writes its scalar
    defaults (including ``R0``, periods, and ``waning_rate: 0.0``) directly into
    ``model.parameters``; user scalars override on top. Period→rate and R0→β
    conversions are applied after this returns, by
    ``app.utils.parameter_conversions.resolve_parameter_conversions``.

    The vaccinated branch mirrors the unvaccinated transitions exactly, with two
    differences:

      - the force-of-infection uses ``transmission_rate_vax`` (= (1 - VE_S) *
        transmission_rate);
      - the hospitalization split uses ``hosp_proportion_vax`` (= (1 - VE_H) *
        hosp_proportion).

    The ``Susceptible → Susceptible_vax`` flow is *not* declared here; it is
    added later by ``apply_vaccinations`` when the request supplies a
    ``vaccination`` block. Without a vaccination block the vaccinated branch
    stays at zero (default initial conditions).
    """
    model = EpiModel(compartments=COMPARTMENTS)
    # List-valued defaults / overrides are handled by apply_age_varying_parameters
    # after the population is bound; skip them here.
    merged = {**DEFAULT_PARAMETERS, **user_scalars}
    for name, value in merged.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            model.add_parameter(parameter_name=name, value=float(value))

    add_transitions(model, TRANSITIONS)

    return model, dict(PRESET_CALC_PARAMETERS)
