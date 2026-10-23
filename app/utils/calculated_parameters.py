"""Safe arithmetic-expression evaluator for ``parameters`` values.

Parameters whose value is a string are treated as Python expressions over the
other parameters in the model. Expressions are validated against an allow-list
of AST nodes (arithmetic operators only), topologically sorted by their
inter-dependencies, then evaluated against the already-resolved parameter
values. Source-parameter shapes (scalar, ``(1, N)``, ``(T,)``, ``(T, N)``)
propagate through the expression via numpy broadcasting.

Reserved names (SCREAMING_SNAKE_CASE) are derived from the model state and
injected into the eval namespace alongside user parameters; see
``compute_reserved_params``.
"""

from __future__ import annotations

import ast
import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from epydemix.model.epimodel import EpiModel

_ALLOWED_BINOPS: tuple[type[ast.operator], ...] = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Pow,
    ast.Mod,
)

_ALLOWED_UNARYOPS: tuple[type[ast.unaryop], ...] = (ast.UAdd, ast.USub)

# `ast.walk` recurses into every child, including the `op` field of BinOp /
# UnaryOp. Listing the operator instance types here lets them pass the
# allow-list check; the operator-specific validation happens on the BinOp /
# UnaryOp parent so an unsupported op (e.g. `ast.MatMult`) still fails clearly.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    *_ALLOWED_BINOPS,
    *_ALLOWED_UNARYOPS,
)


def _parse(expr: str, param_name: str) -> ast.Expression:
    """Parse ``expr`` in eval mode, re-raising syntax errors with parameter context."""
    if len(expr) > 2000:
        raise ValueError(f"Calculated parameter '{param_name}' expression exceeds 2000 characters")
    try:
        return ast.parse(expr, mode="eval")
    except (SyntaxError, RecursionError) as e:
        raise ValueError(
            f"Calculated parameter '{param_name}' has invalid expression {expr!r}: {e}"
        ) from e


def _validate(tree: ast.AST, param_name: str) -> None:
    """Walk the AST and raise ValueError on any node outside the allow-list."""
    nodes = list(ast.walk(tree))
    if len(nodes) > 200:
        raise ValueError(f"Calculated parameter '{param_name}' expression exceeds 200 AST nodes")
    for node in nodes:
        if isinstance(node, _ALLOWED_NODES):
            if isinstance(node, ast.BinOp) and not isinstance(node.op, _ALLOWED_BINOPS):
                raise ValueError(
                    f"Calculated parameter '{param_name}' uses disallowed operator "
                    f"{type(node.op).__name__}; allowed binary operators are "
                    f"+, -, *, /, //, **, %."
                )
            if isinstance(node, ast.UnaryOp) and not isinstance(node.op, _ALLOWED_UNARYOPS):
                raise ValueError(
                    f"Calculated parameter '{param_name}' uses disallowed unary operator "
                    f"{type(node.op).__name__}; allowed unary operators are +, -."
                )
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                raise ValueError(
                    f"Calculated parameter '{param_name}' contains a non-numeric "
                    f"constant ({type(node.value).__name__}); only numeric literals "
                    f"are allowed."
                )
            continue
        raise ValueError(
            f"Calculated parameter '{param_name}' uses disallowed expression node "
            f"{type(node).__name__}; only arithmetic over parameter names is "
            f"supported (no function calls, attribute access, subscripts, "
            f"comparisons, or conditionals)."
        )


def parse_expression(expr: str, param_name: str) -> ast.Expression:
    """Validate arithmetic and normalize literals to bounded floating-point values."""
    tree = _parse(expr, param_name)
    _validate(tree, param_name)
    # Float literals prevent Python's unbounded integer exponentiation.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            try:
                node.value = float(node.value)
            except OverflowError as exc:
                raise ValueError(
                    f"Calculated parameter '{param_name}' has an oversized numeric literal"
                ) from exc
            if not math.isfinite(node.value):
                raise ValueError(
                    f"Calculated parameter '{param_name}' has a non-finite numeric literal"
                )
    return tree


def extract_dependencies(tree: ast.AST) -> set[str]:
    """Return the set of `Name` identifiers referenced in a validated AST."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def transitive_dependencies(name: str, expr_params: dict[str, str]) -> set[str]:
    """Return every name ``expr_params[name]`` references, directly or via other expressions.

    Syntax errors raise ValueError as in ``evaluate_expressions``; other
    validation (disallowed nodes, undefined names, cycles) is left to it.
    """
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        for dep in extract_dependencies(_parse(expr_params[current], current)):
            if dep not in seen:
                seen.add(dep)
                if dep in expr_params:
                    stack.append(dep)
    return seen


def _topological_order(
    expr_params: dict[str, str],
    deps: dict[str, set[str]],
) -> list[str]:
    """Return expression-param names in dependency order.

    Only inter-expression dependencies create ordering edges; references to
    non-expression names (scalar/list/transformed source params) are ignored
    here because those values already live in ``resolved_params`` at eval time.
    Cycles raise ValueError naming the involved parameters.
    """
    expr_names = set(expr_params)
    remaining = {name: deps[name] & expr_names for name in expr_params}
    order: list[str] = []

    while remaining:
        ready = sorted(name for name, d in remaining.items() if not d)
        if not ready:
            cycle = sorted(remaining)
            raise ValueError(
                f"Calculated parameters have a circular dependency among: {', '.join(cycle)}."
            )
        for name in ready:
            order.append(name)
            del remaining[name]
        for d in remaining.values():
            d.difference_update(ready)

    return order


def evaluate_expressions(
    expr_params: dict[str, str],
    resolved_params: dict[str, object],
) -> dict[str, object]:
    """Validate, topologically sort, and evaluate ``expr_params``.

    Returns a mapping from expression-parameter name to its evaluated value
    (scalar ``float`` or ``numpy.ndarray`` depending on source shapes).
    Mutates neither input. Raises ``ValueError`` on syntax errors, disallowed
    AST nodes, references to undefined names, or circular dependencies.
    """
    if not expr_params:
        return {}

    trees: dict[str, ast.Expression] = {}
    deps: dict[str, set[str]] = {}
    for name, expr in expr_params.items():
        tree = parse_expression(expr, name)
        trees[name] = tree
        deps[name] = extract_dependencies(tree)

    expr_names = set(expr_params)
    known = set(resolved_params) | expr_names
    for name, refs in deps.items():
        unknown = refs - known
        if unknown:
            raise ValueError(
                f"Calculated parameter '{name}' references undefined name(s): "
                f"{', '.join(sorted(unknown))}."
            )

    order = _topological_order(expr_params, deps)

    # Normalize 1D time-varying values (`(T,)`) to `(T, 1)` so they broadcast
    # cleanly against age-varying `(1, N)` sources within an expression.
    # This is the same convention `_broadcast` already encodes implicitly:
    # 1D arrays in `model.parameters` mean "time-varying, age-uniform".
    namespace: dict[str, object] = {
        k: (
            v.reshape(-1, 1)
            if isinstance(v, np.ndarray) and v.ndim == 1
            else float(v)
            if isinstance(v, (int, float))
            else v
        )
        for k, v in resolved_params.items()
    }

    results: dict[str, object] = {}
    for name in order:
        code = compile(trees[name], filename=f"<calc:{name}>", mode="eval")
        try:
            with np.errstate(all="raise"):
                value = eval(code, {"__builtins__": {}}, namespace)  # noqa: S307
            if np.iscomplexobj(value) or not np.all(np.isfinite(value)):
                raise ValueError("expression must produce finite real numbers")
        except Exception as e:
            raise ValueError(f"Calculated parameter '{name}' failed to evaluate: {e}") from e

        if isinstance(value, np.ndarray):
            # Strip the broadcast helper-axis: `(T, 1)` → `(T,)`, `(1, 1)` → scalar.
            # Leaves genuine `(1, N)` and `(T, N)` shapes untouched.
            if value.ndim == 2 and value.shape[1] == 1 and value.shape[0] != 1:
                stored: object = np.ascontiguousarray(value[:, 0])
            elif value.ndim == 2 and value.shape == (1, 1):
                stored = float(value[0, 0])
            elif value.ndim == 0:
                stored = float(value)
            else:
                stored = value.copy()
        else:
            stored = value

        results[name] = stored
        # Re-normalize for downstream expressions that depend on this one.
        if isinstance(stored, np.ndarray) and stored.ndim == 1:
            namespace[name] = stored.reshape(-1, 1)
        else:
            namespace[name] = stored

    return results


# Reserved names are SCREAMING_SNAKE_CASE constants derived from the model
# state and injected into the eval namespace. They are NOT stored as
# parameters on the model, so they do not appear in `results.parameters`;
# they exist only as ingredients in user expressions. Adding a new reserved
# name means adding one branch to ``compute_reserved_params``.
RESERVED_NAMES: frozenset[str] = frozenset({"CONTACT_MATRIX_EIGENVALUE_ALL"})


def compute_reserved_params(model: EpiModel) -> dict[str, float]:
    """Compute reserved-name values from the model state.

    Currently registers:

    - ``CONTACT_MATRIX_EIGENVALUE_ALL``: dominant eigenvalue (largest by
      magnitude) of the sum across all contact-matrix layers in
      ``model.population.contact_matrices``. Useful for R0 calibration,
      e.g. ``"transmission_rate": "R0 * gamma / CONTACT_MATRIX_EIGENVALUE_ALL"``.

    Future extension for per-layer eigenvalues should follow the
    ``CONTACT_MATRIX_EIGENVALUE_<layer>`` convention (literal layer key).
    """
    matrices = getattr(model.population, "contact_matrices", None) or {}
    if not matrices:
        raise ValueError(
            "Cannot compute reserved parameter 'CONTACT_MATRIX_EIGENVALUE_ALL': "
            "the population has no contact matrices."
        )
    summed = sum(np.asarray(m, dtype=float) for m in matrices.values())
    eigenvalues = np.linalg.eigvals(summed)
    dominant = float(np.max(np.abs(eigenvalues)))
    return {"CONTACT_MATRIX_EIGENVALUE_ALL": dominant}
