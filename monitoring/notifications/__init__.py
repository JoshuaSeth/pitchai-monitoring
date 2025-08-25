"""Notification system for the monitoring platform."""

from .telegram_bot import TelegramNotifier

__all__ = ["TelegramNotifier"]