"""Safe expression and command rendering for Python exports."""

from __future__ import annotations

import ast
from pprint import pformat

from ...api.v1.schemas.simulation import SimulationRequest
from ...utils.calculated_parameters import RESERVED_NAMES, _parse, _validate, extract_dependencies


def _literal(value: object) -> str:
    """Format a Python value as deterministic, readable source code."""
    return pformat(value, width=100, sort_dicts=False)


class _ExpressionRenderer(ast.NodeTransformer):
    """Turn expression names into lookups on the epydemix model."""

    def visit_Name(self, node: ast.Name) -> ast.expr:  # noqa: N802
        """Replace a parameter name with its generated runtime lookup."""
        if node.id == "CONTACT_MATRIX_EIGENVALUE_ALL":
            return ast.Call(
                func=ast.Name(id="calculate_dominant_contact_eigenvalue", ctx=ast.Load()),
                args=[ast.Name(id="population", ctx=ast.Load())],
                keywords=[],
            )
        return ast.Call(
            func=ast.Name(id="get_parameter_for_calculation", ctx=ast.Load()),
            args=[ast.Name(id="model", ctx=ast.Load()), ast.Constant(node.id)],
            keywords=[],
        )


def _render_expression(expression: str) -> str:
    """Render a validated parameter expression as executable Python source.

    Parameter names become lookups on ``model`` and reserved population values
    become calls to the corresponding helper included in the exported script.

    Parameters
    ----------
    expression : str
        Arithmetic expression to render.

    Returns
    -------
    str
        Python source that evaluates the expression at runtime.
    """
    normalized = " ".join(expression.split())
    if normalized == "R0 * recovery_rate / CONTACT_MATRIX_EIGENVALUE_ALL":
        return (
            "calculate_transmission_rate_from_r0("
            "r0=get_parameter_for_calculation(model, 'R0'), "
            "recovery_rate=get_parameter_for_calculation(model, 'recovery_rate'), "
            "contact_eigenvalue=calculate_dominant_contact_eigenvalue(population))"
        )
    tree = ast.parse(expression, mode="eval")
    rendered = _ExpressionRenderer().visit(tree)
    ast.fix_missing_locations(rendered)
    return ast.unparse(rendered.body)


def _expression_order(expressions: dict[str, str]) -> list[str]:
    """Return calculated parameter names in dependency-safe order.

    Parameters
    ----------
    expressions : dict of {str: str}
        Calculated parameter names mapped to their arithmetic expressions.

    Returns
    -------
    list of str
        Parameter names in topological evaluation order.

    Raises
    ------
    ValueError
        If the calculated parameters contain a dependency cycle.
    """
    dependencies = {
        name: {
            node.id
            for node in ast.walk(ast.parse(expression, mode="eval"))
            if isinstance(node, ast.Name) and node.id in expressions
        }
        for name, expression in expressions.items()
    }
    remaining = dict(dependencies)
    order: list[str] = []
    while remaining:
        ready = sorted(name for name, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError(
                "Calculated parameters contain a cycle: " + ", ".join(sorted(remaining))
            )
        order.extend(ready)
        for name in ready:
            del remaining[name]
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def _validate_expressions(expressions: dict[str, str], parameter_names: set[str]) -> None:
    """Validate calculated expressions using the simulation runtime's safety rules.

    Parameters
    ----------
    expressions : dict of {str: str}
        Calculated parameter names mapped to their arithmetic expressions.
    parameter_names : set of str
        Names of parameters available before expressions are evaluated.

    Raises
    ------
    ValueError
        If an expression is unsafe or references an undefined name.
    """
    known_names = parameter_names | set(expressions) | set(RESERVED_NAMES)
    for name, expression in expressions.items():
        tree = _parse(expression, name)
        _validate(tree, name)
        unknown = extract_dependencies(tree) - known_names
        if unknown:
            raise ValueError(
                f"Calculated parameter {name!r} references undefined name(s): "
                + ", ".join(sorted(unknown))
            )


def _render_transition(source: str, target: str, kind: str, params: list[str]) -> list[str]:
    """Render one ``model.add_transition`` call as lines of Python source.

    Parameters
    ----------
    source : str
        Source compartment name.
    target : str
        Target compartment name.
    kind : str
        epydemix transition kind.
    params : list of str
        Parameter names consumed by the transition.

    Returns
    -------
    list of str
        Source lines for the transition registration call.
    """
    native_params: object = tuple(params) if kind == "mediated" else params[0]
    return [
        "model.add_transition(",
        f"    source={source!r},",
        f"    target={target!r},",
        f"    kind={kind!r},",
        f"    params={native_params!r},",
        ")",
    ]


def _render_transform_calls(
    request: SimulationRequest,
    transforms: list,
) -> list[str]:
    """Render native parameter-transform calls for one orchestration pass.

    Balcan seasonality and scaling calls retain their request order. Overrides
    are emitted afterward to match the API execution pipeline. The returned
    lines are source code only; this function does not mutate a model.

    Parameters
    ----------
    request : SimulationRequest
        Request providing simulation dates and time-step configuration.
    transforms : list
        Parameter transforms to render in this orchestration pass.

    Returns
    -------
    list of str
        Source lines containing native transform helper calls.
    """
    if not transforms:
        return []
    sim = request.simulation
    end_name = "internal_end_date"
    lines: list[str] = []
    multiplicative = [item for item in transforms if item.method in ("balcan", "scale")]
    overrides = [item for item in transforms if item.method == "override"]
    for item in [*multiplicative, *overrides]:
        lines.extend(["", f"# Apply {item.method} to {item.target_parameter}."])
        if item.method == "balcan":
            lines.extend(
                [
                    "model.add_parameter(",
                    f"    parameter_name={item.target_parameter!r},",
                    "    value=apply_balcan_seasonality(",
                    f"        value=model.get_parameter({item.target_parameter!r}),",
                    f"        start_date={sim.start_date!r},",
                    f"        end_date={end_name},",
                    f"        max_date={item.max_date!r},",
                    f"        min_date={item.min_date!r},",
                    f"        min_value={item.min_value!r},",
                    f"        max_value={item.max_value!r},",
                    f"        dt={sim.dt!r},",
                    "    ),",
                    ")",
                ]
            )
        elif item.method == "scale":
            lines.extend(
                [
                    "model.add_parameter(",
                    f"    parameter_name={item.target_parameter!r},",
                    "    value=apply_parameter_scaling(",
                    f"        value=model.get_parameter({item.target_parameter!r}),",
                    f"        start_date={sim.start_date!r},",
                    f"        end_date={end_name},",
                    f"        scaling_start={item.start_date!r},",
                    f"        scaling_end={item.end_date!r},",
                    f"        factor={item.factor!r},",
                    f"        dt={sim.dt!r},",
                    "    ),",
                    ")",
                ]
            )
        else:
            lines.extend(
                [
                    "model.add_parameter(",
                    f"    parameter_name={item.target_parameter!r},",
                    "    value=apply_parameter_override(",
                    f"        value=model.get_parameter({item.target_parameter!r}),",
                    f"        override_value={_literal(item.value)},",
                    f"        start_date={sim.start_date!r},",
                    f"        end_date={end_name},",
                    f"        override_start={item.start_date!r},",
                    f"        override_end={item.end_date!r},",
                    "        number_of_groups=population.num_groups,",
                    f"        dt={sim.dt!r},",
                    "    ),",
                    ")",
                ]
            )
    return lines
