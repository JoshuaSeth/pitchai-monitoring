"""Telegram notification system for monitoring alerts."""

import os
from datetime import datetime
from typing import Any

import structlog

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = structlog.get_logger(__name__)


class TelegramNotifier:
    """Handles Telegram notifications for monitoring alerts."""

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        """Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token (or from TELEGRAM_BOT_TOKEN env)
            chat_id: Telegram chat ID (or from TELEGRAM_CHAT_ID env)
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.bot = None

        if self.bot_token:
            self.bot = Bot(token=self.bot_token)
            logger.info("Telegram notifier initialized")
        else:
            logger.warning("Telegram bot token not configured")

    async def send_daily_report(self, report: dict[str, Any]) -> bool:
        """Send daily monitoring report via Telegram.

        Args:
            report: Daily monitoring report data

        Returns:
            True if sent successfully
        """
        if not self._is_configured():
            return False

        message = self._format_daily_report(report)
        return await self._send_message(message)

    async def send_critical_alert(self, alert: dict[str, Any]) -> bool:
        """Send critical alert immediately.

        Args:
            alert: Critical alert data

        Returns:
            True if sent successfully
        """
        if not self._is_configured():
            return False

        message = self._format_critical_alert(alert)
        return await self._send_message(message, priority="high")

    async def send_test_failure_summary(self, failures: list[dict[str, Any]]) -> bool:
        """Send UI test failure summary.

        Args:
            failures: List of test failures

        Returns:
            True if sent successfully
        """
        if not self._is_configured():
            return False

        message = self._format_test_failures(failures)
        return await self._send_message(message)

    def _format_daily_report(self, report: dict[str, Any]) -> str:
        """Format daily report for Telegram."""
        timestamp = report.get("timestamp", datetime.utcnow().isoformat())

        # Overall status emoji
        status_emoji = "✅" if report.get("all_healthy", True) else "⚠️"

        lines = [
            f"{status_emoji} *PitchAI Daily Monitoring Report*",
            f"_Generated: {timestamp}_",
            "",
            "📊 *Summary*",
            f"• UI Tests: {report.get('ui_tests_passed', 0)}/{report.get('ui_tests_total', 0)} passed",
            f"• Containers: {report.get('containers_monitored', 0)} monitored",
            f"• Errors: {report.get('total_errors', 0)} detected",
            ""
        ]

        # Add critical issues if any
        if report.get("critical_issues"):
            lines.append("🚨 *Critical Issues*")
            for issue in report["critical_issues"][:5]:  # Limit to 5
                lines.append(f"• {issue.get('container', 'Unknown')}: {issue.get('message', '')[:100]}")
            lines.append("")

        # Add failed tests if any
        if report.get("failed_tests"):
            lines.append("❌ *Failed UI Tests*")
            for test in report["failed_tests"][:5]:  # Limit to 5
                lines.append(f"• {test.get('name', 'Unknown')}: {test.get('error', '')[:100]}")
            lines.append("")

        # Add recommendations
        if report.get("recommendations"):
            lines.append("💡 *Recommendations*")
            for rec in report["recommendations"][:3]:  # Limit to 3
                lines.append(f"• {rec}")
            lines.append("")

        # Health status
        lines.append("🏥 *System Health*")
        lines.append(f"• Overall: {'Healthy' if report.get('all_healthy', True) else 'Issues Detected'}")
        lines.append(f"• Uptime: {report.get('uptime_percentage', 100):.1f}%")

        return "\n".join(lines)

    def _format_critical_alert(self, alert: dict[str, Any]) -> str:
        """Format critical alert for immediate notification."""
        lines = [
            "🚨🚨🚨 *CRITICAL ALERT* 🚨🚨🚨",
            "",
            f"*Service:* {alert.get('service', 'Unknown')}",
            f"*Issue:* {alert.get('issue', 'Unknown error')}",
            f"*Time:* {alert.get('timestamp', datetime.utcnow().isoformat())}",
            "",
            "*Details:*",
            f"{alert.get('details', 'No additional details available')[:500]}",
            "",
            f"*Action Required:* {alert.get('action', 'Please investigate immediately')}",
            "",
            "_This is an automated alert from PitchAI Monitoring_"
        ]

        return "\n".join(lines)

    def _format_test_failures(self, failures: list[dict[str, Any]]) -> str:
        """Format test failures for notification."""
        if not failures:
            return "✅ All UI tests passed successfully!"

        lines = [
            "⚠️ *UI Test Failures Detected*",
            f"_Failed: {len(failures)} test(s)_",
            ""
        ]

        for failure in failures[:10]:  # Limit to 10
            lines.append(f"❌ *{failure.get('test_name', 'Unknown Test')}*")
            lines.append(f"   Error: {failure.get('error', 'Unknown error')[:200]}")
            lines.append(f"   Duration: {failure.get('duration', 0):.2f}s")
            lines.append("")

        if len(failures) > 10:
            lines.append(f"_... and {len(failures) - 10} more failures_")

        return "\n".join(lines)

    async def _send_message(self, message: str, priority: str = "normal") -> bool:
        """Send message via Telegram.

        Args:
            message: Formatted message to send
            priority: Message priority (normal/high)

        Returns:
            True if sent successfully
        """
        if not self.bot or not self.chat_id:
            logger.warning("Telegram not configured, skipping notification")
            return False

        try:
            # Add priority indicator for high priority
            if priority == "high":
                message = "‼️ " + message

            # Send message with Markdown parsing
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

            logger.info("Telegram notification sent", priority=priority)
            return True

        except TelegramError as e:
            logger.error("Failed to send Telegram notification", error=str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error sending Telegram notification", error=str(e))
            return False

    def _is_configured(self) -> bool:
        """Check if Telegram is properly configured."""
        return bool(self.bot and self.chat_id)

    async def test_connection(self) -> bool:
        """Test Telegram connection with a test message.

        Returns:
            True if test message sent successfully
        """
        test_message = (
            "🔔 *PitchAI Monitoring Test*\n"
            f"_Connection test at {datetime.utcnow().isoformat()}_\n"
            "\n"
            "✅ Telegram notifications are working!"
        )

        return await self._send_message(test_message)
