"""Preset-scoped parameter conversions: period→rate and R0→β.

Lets users supply friendlier source inputs (``infectious_period`` instead of
``recovery_rate``, ``R0`` instead of ``transmission_rate``) on opted-in
presets. Each conversion is a ``(derived, source, expression)`` triple; when
the source is present in the model and the derived is not, the resolver
injects the expression as a calculated parameter.

Each preset declares its own ``PARAMETER_CONVERSIONS`` dict so the math is
visible at the preset module and free to differ between presets (e.g. an
R0→β formula that depends on the next-generation matrix of the preset's
infectious compartments). Custom models retain the existing
explicit-parameter contract: name-based collisions would break the
custom-model surface, so nothing implicit is injected when ``preset`` is
``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParameterConversion:
    """One preset-canonical way to express a model parameter via a friendlier source.

    Attributes
    ----------
    source : str
        The user-facing scalar (e.g. ``infectious_period``, ``R0``) that the
        user supplies instead of the derived rate-form value.
    expression : str
        The calc-param expression injected as ``<derived> = <expression>``
        when ``source`` is present in ``model.parameters``. Must reference
        ``source`` (and possibly other names available at calc-eval time).

    The derived name is the dict key in each preset's ``PARAMETER_CONVERSIONS``;
    it is not duplicated here.
    """

    source: str
    expression: str


def resolve_parameter_conversions(
    model_parameters: dict[str, Any],
    user_scalar_names: set[str],
    conversions: dict[str, ParameterConversion],
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Inject calc-params for source scalars the user supplied on opted-in presets.

    Called after preset construction (so preset defaults are already in
    ``model_parameters``) and before calc-param evaluation. Mutates
    ``model_parameters`` in place (drops the source scalar when the user
    overrides the derived directly) and returns a dict of derived-name →
    expression to merge into the pipeline's ``expr_params``, plus the
    ``(source, derived)`` pairs whose conversion was skipped by rule 1.

    Parameters
    ----------
    model_parameters : dict
        ``model.parameters`` mutated in place. Source scalars are popped when
        the user supplies the derived value directly.
    user_scalar_names : set[str]
        Names of scalar/list parameters the user supplied in the request.
        Distinguishes preset defaults from user inputs; preset defaults alone
        do not satisfy the "user passed the derived" precedence rule.
    conversions : dict[str, ParameterConversion]
        DERIVED parameter name → conversion for the active preset. Custom
        models pass ``{}`` to opt out.

    Returns
    -------
    dict[str, str]
        Derived name → expression. Empty when nothing fires.
    list[tuple[str, str]]
        ``(source, derived)`` for every conversion skipped because the user
        passed the derived directly. Callers filter by which sources the user
        supplied (vs. preset defaults) before surfacing a warning.

    Precedence per derived entry ``conv = conversions[name]``:

    1. If ``name`` is in ``user_scalar_names`` (the user passed the derived
       parameter directly), drop ``conv.source`` from ``model_parameters`` and
       emit no calc-param. The user's scalar stands.
    2. Else if ``conv.source`` is present in ``model_parameters``, emit
       ``name = conv.expression``.
    3. Else do nothing.

    Disabling a flow (e.g. no waning) is handled by the preset: ship a scalar
    default (``waning_rate: 0.0``) and don't define the source. Users enable
    by passing the source (``immunity_duration: 365``), which triggers the
    calc-param injection and overrides the scalar default. No ``None``-as-
    disable handling needed here.
    """
    new_calc_params: dict[str, str] = {}
    overridden: list[tuple[str, str]] = []
    for derived_name, conv in conversions.items():
        if derived_name in user_scalar_names:
            model_parameters.pop(conv.source, None)
            overridden.append((conv.source, derived_name))
            continue
        if conv.source not in model_parameters:
            continue
        new_calc_params[derived_name] = conv.expression
    return new_calc_params, overridden
