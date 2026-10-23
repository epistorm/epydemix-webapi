"""Centralized preset registry.

Assembled from per-preset modules. Each preset owns its own metadata
(compartments, defaults, transitions, parameter-conversion opt-ins,
description) and exposes a ``build_*_model`` callable. The registry just
wires them together so consumers see a uniform ``PresetDefinition``.

Consumers:

- ``app.services.simulation_service.create_model`` for runtime construction.
- ``app.api.v1.endpoints.presets`` for the ``GET /models/presets`` payload.
- ``app.api.v1.schemas.simulation.request.ModelConfig`` for the ``preset``
  literal.

Adding a preset = create ``app/presets/<name>.py`` exposing the same module
attributes (``COMPARTMENTS``, ``DEFAULT_PARAMETERS``, ``TRANSITIONS``,
``PARAMETER_CONVERSIONS``, ``DESCRIPTION``, and ``build_*_model``), then
register it in the ``PRESETS`` dict below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from epydemix.model.epimodel import EpiModel

from ..utils.parameter_conversions import ParameterConversion
from . import seir, sir, sis, v_seihr, v_seir


@dataclass(frozen=True)
class PresetDefinition:
    """One source of truth per preset.

    Fields:
      - ``name``: user-facing identifier, matches the ``preset`` request literal.
      - ``description``: free-text shown in ``GET /models/presets``.
      - ``compartments``: ordered compartment names.
      - ``default_parameters``: scalar (or age-varying) defaults shown in
        ``GET /models/presets``.
      - ``transitions``: structured transition listing for the ``/presets`` payload.
      - ``parameter_conversions``: derived-name → ``ParameterConversion`` for
        the period→rate / R0→β substitutions this preset accepts (see
        ``app.utils.parameter_conversions``). Empty = preset opts out.
      - ``probability_parameters``: names that are probabilities or proportions
        and must stay in ``[0, 1]`` after evaluation and transforms.
      - ``build_model``: callable. Receives a dict of user-supplied scalar
        parameters (preset defaults are merged inside). Returns
        ``(EpiModel, dict[str, str])`` where the second element is any
        preset-specific calculated parameters to merge into ``expr_params``.
    """

    name: str
    description: str
    compartments: list[str]
    default_parameters: dict[str, float | list[float]]
    transitions: list[dict]
    parameter_conversions: dict[str, ParameterConversion]
    build_model: Callable[[dict[str, float]], tuple[EpiModel, dict[str, str]]]
    default_initial_conditions: Callable[[EpiModel], dict[str, np.ndarray]] | None = None
    probability_parameters: tuple[str, ...] = ()


PRESETS: dict[str, PresetDefinition] = {
    "SIR": PresetDefinition(
        name="SIR",
        description=sir.DESCRIPTION,
        compartments=sir.COMPARTMENTS,
        default_parameters=dict(sir.DEFAULT_PARAMETERS),
        transitions=list(sir.TRANSITIONS),
        parameter_conversions=dict(sir.PARAMETER_CONVERSIONS),
        build_model=sir.build_sir_model,
    ),
    "SEIR": PresetDefinition(
        name="SEIR",
        description=seir.DESCRIPTION,
        compartments=seir.COMPARTMENTS,
        default_parameters=dict(seir.DEFAULT_PARAMETERS),
        transitions=list(seir.TRANSITIONS),
        parameter_conversions=dict(seir.PARAMETER_CONVERSIONS),
        build_model=seir.build_seir_model,
    ),
    "SIS": PresetDefinition(
        name="SIS",
        description=sis.DESCRIPTION,
        compartments=sis.COMPARTMENTS,
        default_parameters=dict(sis.DEFAULT_PARAMETERS),
        transitions=list(sis.TRANSITIONS),
        parameter_conversions=dict(sis.PARAMETER_CONVERSIONS),
        build_model=sis.build_sis_model,
    ),
    "V-SEIR": PresetDefinition(
        name="V-SEIR",
        description=v_seir.DESCRIPTION,
        compartments=list(v_seir.COMPARTMENTS),
        default_parameters=dict(v_seir.DEFAULT_PARAMETERS),
        transitions=list(v_seir.TRANSITIONS),
        parameter_conversions=dict(v_seir.PARAMETER_CONVERSIONS),
        build_model=v_seir.build_v_seir_model,
        default_initial_conditions=v_seir.default_initial_conditions,
        probability_parameters=("VE_S",),
    ),
    "V-SEIHR": PresetDefinition(
        name="V-SEIHR",
        description=v_seihr.DESCRIPTION,
        compartments=list(v_seihr.COMPARTMENTS),
        default_parameters=dict(v_seihr.DEFAULT_PARAMETERS),
        transitions=list(v_seihr.TRANSITIONS),
        parameter_conversions=dict(v_seihr.PARAMETER_CONVERSIONS),
        build_model=v_seihr.build_v_seihr_model,
        default_initial_conditions=v_seihr.default_initial_conditions,
        probability_parameters=("VE_S", "VE_H", "hosp_proportion"),
    ),
}


def preset_names() -> tuple[str, ...]:
    """Tuple of preset names, in registry insertion order."""
    return tuple(PRESETS.keys())
