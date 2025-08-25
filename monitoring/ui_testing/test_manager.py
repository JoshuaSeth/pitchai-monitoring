"""Test management for loading and organizing UI tests."""

import json
from pathlib import Path
from typing import Any

import structlog
import yaml

from ..config import get_config

logger = structlog.get_logger(__name__)


class TestManager:
    """Manages UI test definitions and configurations."""

    def __init__(self, tests_directory: str | None = None):
        self.config = get_config()
        self.tests_directory = Path(tests_directory or "tests")

    def load_test_config(self, test_file: str) -> dict[str, Any]:
        """Load a single test configuration from file."""
        test_path = self.tests_directory / test_file

        if not test_path.exists():
            raise FileNotFoundError(f"Test file not found: {test_path}")

        logger.debug("Loading test config", file=test_file)

        if test_path.suffix.lower() == '.json':
            with open(test_path) as f:
                return json.load(f)
        elif test_path.suffix.lower() in ['.yaml', '.yml']:
            with open(test_path) as f:
                return yaml.safe_load(f)
        else:
            raise ValueError(f"Unsupported test file format: {test_path.suffix}")

    def load_all_tests(self) -> list[dict[str, Any]]:
        """Load all test configurations from the tests directory."""
        test_configs = []

        if not self.tests_directory.exists():
            logger.warning("Tests directory does not exist", directory=str(self.tests_directory))
            return test_configs

        # Find all test files
        for pattern in ["*.json", "*.yaml", "*.yml"]:
            for test_file in self.tests_directory.glob(pattern):
                try:
                    config = self.load_test_config(test_file.name)
                    test_configs.append(config)
                    logger.debug("Loaded test config", file=test_file.name)
                except Exception as e:
                    logger.error("Failed to load test config", file=test_file.name, error=str(e))

        logger.info("Loaded test configurations", count=len(test_configs))
        return test_configs

    def create_test_from_template(self, template_data: dict[str, Any]) -> dict[str, Any]:
        """Create a standardized test configuration from template data."""
        return {
            "flow_name": template_data.get("flow_name", "Unnamed Test"),
            "description": template_data.get("description", ""),
            "target_url": template_data.get("target_url"),
            "target_env": template_data.get("target_env", "production"),
            "owner": template_data.get("owner", ""),
            "last_verified": template_data.get("last_verified", ""),
            "metadata": template_data.get("metadata", {}),
            "steps": template_data.get("steps", [])
        }

    def save_test_config(self, test_config: dict[str, Any], filename: str | None = None) -> str:
        """Save a test configuration to file."""
        if filename is None:
            # Generate filename from flow name
            flow_name = test_config.get("flow_name", "test")
            filename = f"{flow_name.lower().replace(' ', '_').replace('—', '_')}.yaml"

        test_path = self.tests_directory / filename
        test_path.parent.mkdir(parents=True, exist_ok=True)

        with open(test_path, 'w') as f:
            yaml.dump(test_config, f, default_flow_style=False, indent=2)

        logger.info("Saved test configuration", file=filename)
        return str(test_path)

    def validate_test_config(self, test_config: dict[str, Any]) -> bool:
        """Validate a test configuration for required fields."""
        required_fields = ["flow_name", "steps"]

        for field in required_fields:
            if field not in test_config:
                logger.error("Missing required field in test config", field=field)
                return False

        # Validate steps
        steps = test_config.get("steps", [])
        if not isinstance(steps, list):
            logger.error("Steps must be a list")
            return False

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                logger.error("Each step must be a dictionary", step_index=i)
                return False

            if "action" not in step:
                logger.error("Each step must have an action", step_index=i)
                return False

        return True

    def filter_tests_by_environment(self, test_configs: list[dict[str, Any]], environment: str) -> list[dict[str, Any]]:
        """Filter tests by target environment."""
        filtered = [
            config for config in test_configs
            if config.get("target_env", "production") == environment
        ]

        logger.info("Filtered tests by environment", environment=environment, count=len(filtered))
        return filtered

    def filter_tests_by_owner(self, test_configs: list[dict[str, Any]], owner: str) -> list[dict[str, Any]]:
        """Filter tests by owner."""
        filtered = [
            config for config in test_configs
            if config.get("owner", "").lower() == owner.lower()
        ]

        logger.info("Filtered tests by owner", owner=owner, count=len(filtered))
        return filtered
