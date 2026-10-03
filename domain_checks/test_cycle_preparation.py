# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native YAML/plugin and startup failure boundaries with private synthetic files."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .config_file import InvalidConfigMappingError, load_config, load_domain_spec
from .cycle_preparation import CyclePreparation
from .dft_test_support import require, require_error

if TYPE_CHECKING:
    from .config_values import ConfigValue


class PreparationTests(unittest.TestCase):
    """No executable discovery, host-state read or external request is allowed."""

    @staticmethod
    def test_yaml_scalars_and_falsey_roots_remain_native() -> None:
        """Dates and binary values retain YAML types while falsey roots become mappings."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("day: 2026-10-03\nblob: !!binary aGVsbG8=\n", encoding="utf-8")
            config = load_config(path)
            require(condition=config == {"day": date(2026, 10, 3), "blob": b"hello"}, message="YAML types changed")
            for source in ("", "null", "false", "0", "[]"):
                path.write_text(source, encoding="utf-8")
                require(condition=load_config(path) == {}, message="falsey YAML root changed")
            path.write_text("- populated", encoding="utf-8")
            with require_error(InvalidConfigMappingError, "Config YAML must be a mapping"):
                load_config(path)

    @staticmethod
    def test_plugin_precedes_inline_and_missing_plugin_uses_inline() -> None:
        """The same local CHECK wins and fallback does not execute a missing plugin."""
        entry: dict[str, ConfigValue] = {"domain": "fixture.invalid", "check": {"url": "https://inline.invalid"}}
        with (patch.object(Path, "exists", return_value=True),
              patch("domain_checks.config_file.runpy.run_path", return_value={
                  "CHECK": {"domain": "fixture.invalid", "url": "https://plugin.invalid"},
              }) as plugin):
            spec = load_domain_spec(entry)
        require(condition=spec.url == "https://plugin.invalid", message="inline check superseded plugin")
        plugin.assert_called_once_with(str(Path(__file__).parent / "fixture.invalid" / "check.py"))
        with (patch.object(Path, "exists", return_value=False),
              patch("domain_checks.config_file.runpy.run_path") as absent):
            spec = load_domain_spec(entry)
        absent.assert_not_called()
        require(condition=spec.url == "https://inline.invalid", message="inline fallback changed")

    @staticmethod
    def test_inventory_failure_precedes_channels_resources_and_chromium() -> None:
        """Invalid inventory fails before channel reads or executable discovery."""
        with (patch("domain_checks.cycle_preparation.load_config", return_value={}),
              patch("domain_checks.cycle_preparation.validate_domain_inventory", side_effect=ValueError("inventory")),
              patch("domain_checks.cycle_preparation.ChannelStartup.read") as channels,
              patch("domain_checks.cycle_preparation.find_chromium_executable") as chromium,
              require_error(ValueError, "inventory")):
            CyclePreparation.read(Path("synthetic.yaml"))
        channels.assert_not_called()
        chromium.assert_not_called()

    @staticmethod
    def test_empty_domains_fail_before_channel_reads() -> None:
        """The original non-empty inventory requirement remains at startup."""
        with (patch("domain_checks.cycle_preparation.load_config", return_value={"domains": []}),
              patch("domain_checks.cycle_preparation.validate_domain_inventory"),
              patch("domain_checks.cycle_preparation.ChannelStartup.read") as channels,
              require_error(ValueError, "Config must contain a non-empty 'domains' list")):
            CyclePreparation.read(Path("synthetic.yaml"))
        channels.assert_not_called()
