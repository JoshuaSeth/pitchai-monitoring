"""Configuration management for the monitoring system."""

import os
from pathlib import Path
from typing import Dict, Any, Optional
import yaml
from pydantic import BaseModel, Field


class ContainerMonitoringConfig(BaseModel):
    """Container monitoring specific configuration."""
    log_retention_hours: int = Field(default=24, description="Hours to retain logs")
    error_keywords: list[str] = Field(default_factory=list, description="Keywords to identify errors")


class AIAgentConfig(BaseModel):
    """AI Agent integration configuration."""
    enable_structured_output: bool = Field(default=True, description="Enable structured JSON output")
    daily_summary_format: str = Field(default="json", description="Format for daily summaries")
    telegram_ready: bool = Field(default=False, description="Ready for Telegram integration")


class MonitoringConfig(BaseModel):
    """Main configuration for the monitoring system."""
    
    # Environment settings
    environment: str = Field(default="production", description="Environment to monitor")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # UI Testing settings
    ui_test_timeout: int = Field(default=30, description="UI test timeout in seconds")
    browser_headless: bool = Field(default=True, description="Run browser in headless mode")
    screenshot_on_failure: bool = Field(default=True, description="Take screenshots on test failures")
    
    # Docker settings
    docker_host: Optional[str] = Field(default=None, description="Docker host URL")
    docker_containers: list[str] = Field(default_factory=list, description="Container names to monitor")
    auto_discover_containers: bool = Field(default=True, description="Auto-discover running containers")
    
    # Scheduling settings
    test_schedule_cron: str = Field(default="0 */1 * * *", description="Cron expression for test scheduling")
    log_collection_interval: int = Field(default=300, description="Log collection interval in seconds")
    daily_report_time: str = Field(default="06:30", description="Time to generate daily reports")
    
    # Output settings
    reports_directory: str = Field(default="reports", description="Directory for output reports")
    logs_directory: str = Field(default="logs", description="Directory for collected logs")
    incidents_directory: str = Field(default="incidents", description="Directory for incident reports")
    structured_output: bool = Field(default=True, description="Enable structured output for AI agents")
    
    # Security settings
    production_urls: list[str] = Field(default_factory=list, description="Production URLs to test")
    auth_tokens: Dict[str, str] = Field(default_factory=dict, description="Authentication tokens")
    
    # Container monitoring
    container_monitoring: ContainerMonitoringConfig = Field(default_factory=ContainerMonitoringConfig)
    
    # AI Agent settings
    ai_agent: AIAgentConfig = Field(default_factory=AIAgentConfig)


def load_config(config_path: Optional[str] = None) -> MonitoringConfig:
    """Load configuration from file or environment variables."""
    if config_path is None:
        config_path = os.getenv("MONITORING_CONFIG", "config/monitoring.yaml")
    
    config_data = {}
    
    # Load from file if exists
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
    
    # Override with environment variables
    env_overrides = {
        "environment": os.getenv("MONITORING_ENV"),
        "log_level": os.getenv("LOG_LEVEL"),
        "docker_host": os.getenv("DOCKER_HOST"),
        "ui_test_timeout": os.getenv("UI_TEST_TIMEOUT"),
        "browser_headless": os.getenv("BROWSER_HEADLESS"),
    }
    
    # Filter out None values and convert types
    for key, value in env_overrides.items():
        if value is not None:
            if key in ["ui_test_timeout"]:
                value = int(value)
            elif key in ["browser_headless"]:
                value = value.lower() in ("true", "1", "yes")
            config_data[key] = value
    
    return MonitoringConfig(**config_data)


def get_config() -> MonitoringConfig:
    """Get the global configuration instance."""
    return load_config()