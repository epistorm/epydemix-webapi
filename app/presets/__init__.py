"""Preset model registry and builders.

Public surface: ``PRESETS`` (the registry mapping preset name to
``PresetDefinition``), and ``preset_names()`` for the request literal.
"""

from .registry import PRESETS, PresetDefinition, preset_names

__all__ = ["PRESETS", "PresetDefinition", "preset_names"]
