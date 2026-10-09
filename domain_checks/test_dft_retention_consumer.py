# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic checker and incident transitions without subprocesses or delivery."""

from __future__ import annotations

import json
import unittest

from .dft_retention_consumer import CheckerObservation, checker_observation, observe_incident
from .dft_test_support import require


class TestRetentionConsumer(unittest.TestCase):
    """Exercise both truthful recovery and minimized failure observations."""

    @staticmethod
    def test_checker_failure_never_recovers() -> None:
        """Transport faults, stale age, nonzero exits and latches stay unhealthy."""
        cases: list[tuple[int | None, bytes]] = [
            (None, b""), (1, b"{}"), (0, b"{}"), (0, b"[]"),
            (0, b'{"age_seconds":NaN,"overdue_segments":0,"errors":[]}'),
            (0, b'{"age_seconds":900,"overdue_segments":0,"errors":[]}'),
            (1, b'{"age_seconds":1,"overdue_segments":0,"errors":[]}'),
            (0, b'{"age_seconds":1,"overdue_segments":0,"errors":["retention_fault_latched"]}'),
        ]
        for returncode, payload in cases:
            require(condition=not checker_observation(returncode, payload).healthy,
                    message="invalid checker evidence was accepted as recovery")

    @staticmethod
    def test_checker_drops_arbitrary_error_content() -> None:
        """Only allowlisted fixed codes cross the durable observation boundary."""
        payload = json.dumps({"age_seconds": 1, "overdue_segments": 0,
                              "errors": ["private-request-content"]}).encode()
        observation = checker_observation(1, payload)
        require(condition=observation.errors == ("checker_nonzero", "checker_unrecognized_error"),
                message="untrusted checker text escaped classification")

    @staticmethod
    def test_historical_counts_do_not_reopen_acknowledged_recovery() -> None:
        """Published15ae402 checker faults, not historical totals, govern health."""
        historical_count = 8
        payload = json.dumps({"age_seconds": 1, "overdue_segments": historical_count, "errors": []}).encode()
        observed = checker_observation(0, payload)
        require(condition=observed.healthy and observed.overdue_segments == historical_count,
                message="historical evidence was erased or treated as a current fault")

    @staticmethod
    def test_identity_survives_warning_and_requires_acknowledged_recovery() -> None:
        """Neither setup warnings nor later health alone close an incident."""
        failure = CheckerObservation(errors=("retention_fault_latched",))
        warning = CheckerObservation(errors=("checker_unavailable",))
        healthy = checker_observation(0, b'{"age_seconds":1,"overdue_segments":0,"errors":[]}')
        incident = observe_incident(None, failure, now=1, next_incident_id="original")
        for observed in (failure, warning, healthy):
            incident = observe_incident(incident, observed, now=2, next_incident_id="unused")
            require(condition=incident is not None and incident.incident_id == "original"
                    and incident.closed_at is None,
                    message="unresolved incident identity was lost")
        failed_ack = observe_incident(incident, failure, now=3, next_incident_id="unused",
                                     owner_acknowledged_incident_id="original")
        require(condition=failed_ack is not None and failed_ack.closed_at is None,
                message="acknowledgement closed an active fault")
        recovery_time = 4
        recovered = observe_incident(failed_ack, healthy, now=recovery_time, next_incident_id="unused")
        require(condition=recovered is not None and recovered.incident_id == "original"
                and recovered.closed_at == recovery_time,
                message="verified acknowledged recovery did not close the same identity")
        retry = observe_incident(recovered, healthy, now=5, next_incident_id="unused")
        require(condition=retry == recovered, message="retry changed immutable recovery identity")
