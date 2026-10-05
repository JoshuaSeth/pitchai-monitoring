# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof that the Claude plan-limit readout is local, fail-closed, and carried between probes."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast, final
from unittest.mock import patch

from ._claude_quota_test_fixtures import (
    DOT,
    FABLE_RESET,
    LIMITS_TEXT,
    NO_LIMITS_TEXT,
    NOW,
    PROBE_ARGUMENTS,
    SESSION_RESET,
    WEEK_RESET,
    ClaudeQuotaCase,
    usage_reply,
)
from ._timeseries_test_fixtures import check, check_equal, require_array
from .claude_accounts import main
from .claude_quota import guard_reason, parse_limits, reset_epoch

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

QUIET_CALL = f"usage quiet=1 tz=UTC updater=1 key=unset entries=0 args={PROBE_ARGUMENTS}"
RETRY_CALL = f"usage quiet=unset tz=UTC updater=1 key=unset entries=0 args={PROBE_ARGUMENTS}"
EXPECTED_WINDOWS: JsonObject = {
    "five_hour": {"used_percent": 34.0, "resets_at": SESSION_RESET},
    "seven_day": {"used_percent": 11.0, "resets_at": WEEK_RESET},
}
EXPECTED_SCOPED: list[JsonValue] = [{"label": "Fable", "used_percent": 0.0, "resets_at": FABLE_RESET}]
TIMEOUT_CEILING_SECONDS = 10.0


def moment(year: int, month: int, day: int, hour: int) -> float:
    """Return one UTC moment on the hour as an epoch."""
    return datetime(year, month, day, hour, tzinfo=UTC).timestamp()


@final
class ClaudeQuotaTest(ClaudeQuotaCase):
    """Prove the readout parser, guard, ordering, retry, timeout, and carry-forward."""

    def test_parser_reads_windows_resets_and_scoped_labels(self) -> None:
        """Parse the verified example, a reset-less session, and Sonnet-only and overage forms."""
        windows, scoped = parse_limits(LIMITS_TEXT, NOW)
        check_equal(windows, EXPECTED_WINDOWS, "named windows")
        check_equal(scoped, EXPECTED_SCOPED, "model-scoped weekly windows")
        overage = "\n".join((
            "You are currently using your overages to power your Claude Code usage",
            "Current session: 0% used",
            f"Current week (Sonnet only): 100% used {DOT} resets Oct 10, 1pm (UTC)",
            f"Current week (Opus only): 7% used {DOT} resets Oct 9, 11:05pm (UTC)",
            "Current week (all models): 120% used",
        ))
        expected: JsonObject = {
            "five_hour": {"used_percent": 0.0, "resets_at": None},
            "seven_day_sonnet": {"used_percent": 100.0, "resets_at": moment(2026, 10, 10, 13)},
            "seven_day": {"used_percent": 100.0, "resets_at": None},
        }
        opus_reset = datetime(2026, 10, 9, 23, 5, tzinfo=UTC).timestamp()
        with self.subTest(form="overage"):
            windows, scoped = parse_limits(overage, NOW)
            check_equal(windows, expected, "overage windows")
            check_equal(scoped, [{"label": "Opus", "used_percent": 7.0, "resets_at": opus_reset}], "Opus scope")
        check_equal(parse_limits(NO_LIMITS_TEXT, NOW), ({}, []), "missing limits stay unknown")

    def test_reset_years_resolve_and_malformed_times_stay_unknown(self) -> None:
        """Resolve a year-less reset to the nearest date and reject malformed or foreign times."""
        new_year_eve = moment(2026, 12, 30, 12)
        check_equal(reset_epoch("Jan 2, 3am (UTC)", new_year_eve), moment(2027, 1, 2, 3), "rolled-over year")
        check_equal(reset_epoch("Jan 2, 2027, 3am (UTC)", NOW), moment(2027, 1, 2, 3), "explicit year")
        check_equal(reset_epoch("Oct 4, 11pm (UTC)", NOW), moment(2026, 10, 4, 23), "recent reset")
        check_equal(reset_epoch("Oct 5, 12am", NOW), moment(2026, 10, 5, 0), "midnight")
        malformed = ("Feb 30, 1am (UTC)", "Oct 5, 13pm (UTC)", "Oct 5, 1:61pm (UTC)", "Oct 5, 1pm (PST)", "Foo 5, 1pm")
        malformed += ("Jan 2, 0000, 3am (UTC)", "Oct 5, 1pm (UTC) extra")
        for text in malformed:
            with self.subTest(text=text):
                check_equal(reset_epoch(text, NOW), None, "malformed reset")

    def test_guard_accepts_only_local_zero_turn_zero_token_results(self) -> None:
        """Flag any result that could have reached a model."""
        check_equal(guard_reason(usage_reply(LIMITS_TEXT)), None, "verified local result")
        spent: JsonObject = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        unsafe: list[tuple[JsonValue, str]] = [
            (usage_reply(LIMITS_TEXT, num_turns=1), "model_turns_reported"),
            (usage_reply(LIMITS_TEXT, num_turns=False), "model_turns_reported"),
            (usage_reply(LIMITS_TEXT, usage={**spent, "output_tokens": 12}), "tokens_reported"),
            (usage_reply(LIMITS_TEXT, usage=spent), "tokens_reported"),
            (usage_reply(LIMITS_TEXT, usage={**spent, "output_tokens": 0, "thinking_tokens": 3}), "tokens_reported"),
            (usage_reply(LIMITS_TEXT, total_cost_usd=0.01), "cost_reported"),
            (usage_reply(LIMITS_TEXT, local_command=None), "not_a_local_usage_result"),
            ([usage_reply(LIMITS_TEXT)], "not_a_local_usage_result"),
        ]
        for document, reason in unsafe:
            with self.subTest(reason=reason):
                check_equal(guard_reason(document), reason, "unsafe readout")

    def test_probe_runs_first_in_an_empty_scrubbed_directory(self) -> None:
        """Read limits before `auth status`, with a scrubbed quiet environment and a removed empty cwd."""
        for profile in ("primary", "secondary"):
            self.reply(profile, usage_reply(LIMITS_TEXT))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "must-not-leak"}):
            primary, secondary = self.collect_rows(self.settings())
        check_equal(self.calls("primary"), [QUIET_CALL, "auth"], "probe precedes auth status")
        check_equal(self.calls("secondary"), [QUIET_CALL, "auth"], "second profile order")
        directory = (self.home("primary") / "directories.log").read_text(encoding="utf-8").strip()
        check(directory != str(self.home("primary")), "probe ran inside the profile home")
        check(not Path(directory).exists(), "probe directory was not removed")
        check_equal(primary["windows"], EXPECTED_WINDOWS, "exported windows")
        check_equal(primary["scoped_windows"], EXPECTED_SCOPED, "exported scoped windows")
        check_equal((primary["quota_observed_at"], primary["quota_error"]), (NOW, None), "fresh reading")
        check_equal((primary["window"], primary["used_percent"]), ("five_hour", 34.0), "tightest window")
        check_equal(primary["usage_observed_at"], NOW, "tightest window moment")
        check_equal((primary["status"], primary["email"]), ("ready", "primary@pitchai.net"), "status")
        check_equal(secondary["quota_source"], "claude_cli_usage", "reading source")

    def test_probe_retries_once_without_the_traffic_flag(self) -> None:
        """Let the binary refresh an expired token itself when the quiet attempt shows no limits."""
        self.reply("primary", usage_reply(NO_LIMITS_TEXT), "1")
        self.reply("primary", usage_reply(LIMITS_TEXT), "retry")
        self.reply("secondary", usage_reply(NO_LIMITS_TEXT))
        primary, secondary = self.collect_rows(self.settings())
        check_equal(self.calls("primary"), [QUIET_CALL, RETRY_CALL, "auth"], "single retry without the flag")
        check_equal((primary["windows"], primary["quota_error"]), (EXPECTED_WINDOWS, None), "retried reading")
        check_equal(self.calls("secondary"), [QUIET_CALL, RETRY_CALL, "auth"], "retried empty readout")
        check_equal((secondary["windows"], secondary["quota_error"]), ({}, "no_limits_reported"), "no limits")
        check_equal(secondary["used_percent"], None, "missing limits stay unknown")

    def test_ordinary_failures_do_not_trip_the_guard(self) -> None:
        """Report a failed exit and an invalid reply as probe failures without disabling probing."""
        (self.home("primary") / "exit").write_text("", encoding="utf-8")
        self.reply("secondary", "not json")
        primary, secondary = self.collect_rows(self.settings())
        check_equal(primary["quota_error"], "probe_failed", "non-zero exit")
        check_equal(secondary["quota_error"], "probe_failed", "invalid JSON")
        check_equal(self.calls("primary"), [QUIET_CALL, "auth"], "failed probe is not retried")
        check(not (self.root / "guard" / "probe.disabled").exists(), "ordinary failure tripped the guard")

    def test_guard_trip_disables_every_further_probe(self) -> None:
        """Write the guard file on an unsafe result and never probe again while it exists."""
        self.reply("primary", usage_reply(LIMITS_TEXT, num_turns=1, usage={"input_tokens": 9}))
        self.reply("secondary", usage_reply(LIMITS_TEXT))
        primary, secondary = self.collect_rows(self.settings())
        guard = (self.root / "guard" / "probe.disabled").read_text(encoding="utf-8")
        check(guard.startswith("2026-10-05T12:00:00Z model_turns_reported"), f"guard record: {guard!r}")
        check_equal((primary["quota_error"], primary["windows"]), ("probe_guard_tripped", {}), "tripped row")
        check_equal(secondary["quota_error"], "probe_disabled", "later profile")
        check_equal(self.calls("secondary"), ["auth"], "later profile was probed")
        rows = self.collect_rows(self.settings(), now=NOW + 3_600)
        check_equal([row["quota_error"] for row in rows], ["probe_disabled", "probe_disabled"], "disabled rows")
        check_equal(self.calls("primary"), [QUIET_CALL, "auth", "auth"], "guarded run probed again")

    def test_timeout_kills_the_probe_without_retry(self) -> None:
        """Kill a hung readout at its deadline and keep the profile's status flowing."""
        (self.home("primary") / "sleep").write_text("", encoding="utf-8")
        self.reply("secondary", usage_reply(LIMITS_TEXT))
        started = time.monotonic()
        primary, secondary = self.collect_rows(self.settings(timeout=0.3))
        check(time.monotonic() - started < TIMEOUT_CEILING_SECONDS, "hung probe was not killed")
        check_equal(primary["quota_error"], "probe_timeout", "timeout code")
        check_equal(self.calls("primary"), [QUIET_CALL, "auth"], "timed-out probe is not retried")
        check_equal(secondary["windows"], EXPECTED_WINDOWS, "next profile still probed")

    def test_full_limit_turns_a_ready_row_into_cooldown(self) -> None:
        """Hold a profile whose weekly limit is used up until that window resets."""
        full = f"Current session: 40% used {DOT} resets Oct 5, 1:49pm (UTC)\n"
        full += f"Current week (all models): 100% used {DOT} resets Oct 10, 3:59am (UTC)"
        self.reply("primary", usage_reply(full))
        self.reply("secondary", usage_reply(LIMITS_TEXT))
        primary, secondary = self.collect_rows(self.settings())
        check_equal((primary["status"], primary["cooldown_until"]), ("cooldown", WEEK_RESET), "full weekly limit")
        check_equal((primary["window"], primary["used_percent"]), ("seven_day", 100.0), "tightest weekly")
        check_equal(secondary["status"], "ready", "partial use stays ready")

    def test_main_carries_readings_until_the_interval_elapses(self) -> None:
        """Probe at most once per interval and carry the previous snapshot's reading in between."""
        runtime = self.root / "runtime"
        bundled = runtime / ".venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude"
        bundled.parent.mkdir(parents=True)
        self.fake_cli().rename(bundled)
        for profile in ("primary", "secondary"):
            self.reply(profile, usage_reply(LIMITS_TEXT))
        output, guard = self.root / "out" / "claude-accounts.json", self.root / "guard" / "probe.disabled"
        arguments = ["--owners", str(self.owners()), "--runtime", str(runtime), "--output", str(output)]
        arguments += ["--probe-guard", str(guard), "--quota-interval", "300"]
        observed: list[JsonValue] = []
        for _ in range(2):
            check_equal(main(arguments), 0, "exporter exit status")
            document = cast("JsonObject", json.loads(output.read_text(encoding="utf-8")))
            first = cast("JsonObject", require_array(document["accounts"], "accounts")[0])
            observed.append(first["quota_observed_at"])
            check_equal(document["schema_version"], 1, "schema stays additive")
            check_equal(cast("JsonObject", first["windows"])["seven_day"], EXPECTED_WINDOWS["seven_day"], "reading")
        check_equal(observed[0], observed[1], "carried reading keeps its moment")
        check_equal(self.calls("primary"), [QUIET_CALL, "auth", "auth"], "probe was not due")
        check_equal(self.calls("secondary"), [QUIET_CALL, "auth", "auth"], "second profile not due")
