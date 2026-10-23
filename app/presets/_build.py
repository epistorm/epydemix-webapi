"""Shared helpers for preset model builders.

Each preset declares its transitions once in a ``TRANSITIONS`` list (used by
the ``/presets`` registry payload) and feeds the same list into its
``build_*_model`` via ``add_transitions`` here.
"""

from __future__ import annotations

from epydemix.model.epimodel import EpiModel


def add_transitions(model: EpiModel, transitions: list[dict]) -> None:
    """Add transitions declared as dicts to an ``EpiModel``.

    Each entry must have ``source``, ``target``, ``kind`` and ``params``.
    For ``kind == "mediated"``, ``params`` is a 2-element list ``[rate, agent]``
    passed to epydemix as a tuple. For ``kind == "spontaneous"``, ``params`` is
    a 1-element list ``[rate]`` and the rate string is passed directly.
    """
    for tr in transitions:
        kind = tr["kind"]
        params = tr["params"]
        if kind == "mediated":
            resolved_params: object = tuple(params)
        else:
            resolved_params = params[0]
        model.add_transition(
            source=tr["source"],
            target=tr["target"],
            kind=kind,
            params=resolved_params,
        )
