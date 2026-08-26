# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable failures for the bounded Docker Engine boundary."""


class DockerProtocolError(RuntimeError):
    """Docker returned a malformed or oversized successful response."""
