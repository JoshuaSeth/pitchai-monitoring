# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fleet token ledger: hourly token usage by provider, model and project.

Host exporters (``python3 -m token_ledger``) tail engine rollouts read-only and
ship hourly buckets to master; the dashboard reads the merged fleet store.
Runtime code stays standard-library only and Python 3.10 compatible because it
runs on each host's system interpreter.
"""
