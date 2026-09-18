# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for configuration serialization libraries."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from .json_types import JsonInput


class _YamlModule(NamedTuple):
    safe_load: object


class YamlLoader(Protocol):
    """Callable YAML parser contract."""

    def __call__(self, source: str) -> JsonInput:
        """Decode one YAML document into Python values."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


_YAML = cast("_YamlModule", cast("object", import_module("yaml")))
load_yaml = cast("YamlLoader", _YAML.safe_load)
