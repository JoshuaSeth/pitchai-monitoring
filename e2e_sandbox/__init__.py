"""Sandbox runners for developer-submitted E2E tests.

These runners are executed by `e2e_runner` either directly (local mode) or inside
an isolated Docker container (sandbox mode). They provide a stable contract so
external developers can upload simple single-file tests without needing to wire
up browsers, timeouts, and artifact capture themselves.
"""

