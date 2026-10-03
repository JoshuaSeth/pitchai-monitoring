# Copyright (c) 2026 PitchAI. All rights reserved.
"""Resume and serialize the cycle's independent health and probe counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from .browser_phase_context import BrowserProbeState
from .container_phase import ContainerObservations
from .cycle_values import coerce_float, coerce_int
from .health_state import HealthState
from .host_observations import HostObservations
from .probe_frame import ProbeSchedule
from .state_values import coerce_bool_dict, coerce_float_dict, coerce_int_dict, coerce_str_list_dict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonObject, JsonValue

_HEALTH_NAMES = ("host_health", "performance", "slo", "tls", "dns", "red", "container_health", "proxy", "meta")
_PROBE_NAMES = ("synthetic", "web_vitals", "api_contract")
_TIMED_NAMES = ("tls", "dns", "container_health")


@dataclass
class CycleHealthState:
    """Hold the existing mutable state objects shared with observation phases."""

    health: dict[str, HealthState] = field(default_factory=dict)
    schedules: dict[str, ProbeSchedule] = field(default_factory=dict)
    probes: dict[str, BrowserProbeState] = field(default_factory=dict)
    host: HostObservations = field(default_factory=HostObservations)
    containers: ContainerObservations = field(default_factory=ContainerObservations)
    dns_ips: dict[str, list[str]] = field(default_factory=dict)
    write_fail_streak: int = 0

    def restore(self, disk: Mapping[str, JsonValue]) -> None:
        """Restore counters and baselines without changing the persisted schema.

        Each absent or non-object section keeps its original fresh defaults.
        The caller invokes this once before passing references to cycle phases.
        """
        for name in _HEALTH_NAMES:
            section = disk.get(name)
            self.health[name] = HealthState.from_section(section) if isinstance(section, dict) else HealthState()
        for name in _TIMED_NAMES:
            section = disk.get(name)
            timestamp = coerce_float(section.get("last_run_ts"), default=0.0) if isinstance(section, dict) else 0.0
            self.schedules[name] = ProbeSchedule(timestamp)
        for name in _PROBE_NAMES:
            section = disk.get(name)
            fields = section if isinstance(section, dict) else {}
            self.probes[name] = BrowserProbeState(
                coerce_bool_dict(fields.get("last_ok")), coerce_int_dict(fields.get("fail_streak")),
                coerce_int_dict(fields.get("success_streak")), coerce_float_dict(fields.get("last_run_ts")),
            )
        host = disk.get("host_health")
        if isinstance(host, dict):
            self.host.cpu_prev_total = coerce_int(host.get("cpu_prev_total"), default=0)
            self.host.cpu_prev_idle = coerce_int(host.get("cpu_prev_idle"), default=0)
        dns = disk.get("dns")
        if isinstance(dns, dict):
            self.dns_ips = coerce_str_list_dict(dns.get("last_ips"))
        container = disk.get("container_health")
        if isinstance(container, dict):
            self.containers.restart_counts = coerce_int_dict(container.get("restart_counts"))
        meta = disk.get("meta")
        if isinstance(meta, dict):
            self.write_fail_streak = coerce_int(meta.get("state_write_fail_streak"), default=0)

    def snapshot(self, write_fail_streak: int) -> JsonObject:
        """Capture current values, including phase mutations since restoration.

        Returns:
            Original section keys and values; probe dictionaries remain live references.
        """
        sections: dict[str, JsonObject] = {name: self.health[name].to_state() for name in _HEALTH_NAMES}
        sections["host_health"].update(cpu_prev_total=int(self.host.cpu_prev_total),
                                       cpu_prev_idle=int(self.host.cpu_prev_idle))
        for name in _TIMED_NAMES:
            sections[name]["last_run_ts"] = float(self.schedules[name].last_run_ts)
        # These are JSON-compatible mutable maps. Retain their live aliases rather
        # than copying solely to widen invariant dictionary value annotations.
        sections["dns"]["last_ips"] = cast("JsonObject", self.dns_ips)
        sections["container_health"]["restart_counts"] = cast("JsonObject", self.containers.restart_counts)
        sections["meta"]["state_write_fail_streak"] = int(write_fail_streak)
        result: JsonObject = dict(sections)
        for name in _PROBE_NAMES:
            probe = self.probes[name]
            result[name] = {
                "last_ok": cast("JsonObject", probe.last_ok),
                "fail_streak": cast("JsonObject", probe.fail_streak),
                "success_streak": cast("JsonObject", probe.success_streak),
                "last_run_ts": cast("JsonObject", probe.last_run_ts),
            }
        return result
