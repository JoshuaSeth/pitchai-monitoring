# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sandbox runners for developer-submitted E2E tests.

The root supervisor launches each submitted test under a leased non-root UID,
private staged source/HOME/TMP/artifact paths, and a dedicated process session.
It kills the process group and any escaped process still owned by that UID before
sealing the job tree back to root. This is an identity/process/filesystem boundary,
not a container or network namespace; world-readable host files and the network
remain reachable by submitted code.
"""
