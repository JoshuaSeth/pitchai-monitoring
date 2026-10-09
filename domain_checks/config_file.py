# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native YAML configuration and existing per-domain Python plugin loading."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from .common_check import load_domain_spec_from_module_dict

if TYPE_CHECKING:
    from .common_check import DomainCheckSpec
    from .config_values import ConfigValue


class InvalidConfigMappingError(TypeError, ValueError):
    """Invalid YAML root type, retaining the established ValueError catch contract."""


def load_config(path: Path) -> dict[str, ConfigValue]:
    """Load the configured file without replacing YAML dates or other scalar values.

    Returns:
        The original mapping, or an empty mapping for the original falsey inputs.

    Raises:
        InvalidConfigMappingError: A populated YAML root is not a mapping.
    """
    with path.open(encoding="utf-8") as stream:
        decoded = cast("ConfigValue", yaml.safe_load(stream)) or {}
    if not isinstance(decoded, dict):
        message = "Config YAML must be a mapping"
        raise InvalidConfigMappingError(message)
    return decoded


def load_domain_spec(domain_entry: str | dict[str, ConfigValue]) -> DomainCheckSpec:
    """Load the existing CHECK plugin first, preserving inline fallback and precedence.

    Returns:
        The native domain spec without copying or rewriting the plugin's CHECK.

    Raises:
        FileNotFoundError: Neither a domain plugin nor an inline check exists.
    """
    if isinstance(domain_entry, str):
        domain = domain_entry
        inline_check = None
    else:
        domain = str(domain_entry["domain"])
        inline_check = domain_entry.get("check")
    plugin_path = Path(__file__).parent / domain / "check.py"
    if plugin_path.exists():
        module_vars = runpy.run_path(str(plugin_path))
        return load_domain_spec_from_module_dict(module_vars)
    if isinstance(inline_check, dict):
        return load_domain_spec_from_module_dict({"CHECK": {"domain": domain, **inline_check}})
    message = f"Missing domain check module for {domain}: expected {plugin_path} (or inline 'check' in config.yaml)"
    raise FileNotFoundError(message)
