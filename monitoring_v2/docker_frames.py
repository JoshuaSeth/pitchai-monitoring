# Copyright (c) 2026 PitchAI. All rights reserved.
"""Decode bounded Docker stdout/stderr multiplex frames."""

from .docker_errors import DockerProtocolError

_FRAME_HEADER_BYTES = 8
_STDOUT_STREAM = 1
_STDERR_STREAM = 2


def decode_multiplexed_stream(payload: bytes) -> tuple[bytes, bytes]:
    """Decode Docker's eight-byte stdout/stderr frame protocol.

    Returns:
        Separate stdout and stderr byte streams.

    Raises:
        DockerProtocolError: If Docker returns a malformed frame stream.
    """
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < _FRAME_HEADER_BYTES:
            message = "Docker exec stream ended inside a frame header"
            raise DockerProtocolError(message)
        stream = payload[offset]
        length = int.from_bytes(payload[offset + 4 : offset + _FRAME_HEADER_BYTES], byteorder="big")
        offset += _FRAME_HEADER_BYTES
        end = offset + length
        if end > len(payload):
            message = "Docker exec stream ended inside a frame body"
            raise DockerProtocolError(message)
        frame = payload[offset:end]
        if stream == _STDOUT_STREAM:
            stdout_parts.append(frame)
        elif stream == _STDERR_STREAM:
            stderr_parts.append(frame)
        else:
            message = "Docker exec stream used an unknown channel"
            raise DockerProtocolError(message)
        offset = end
    return b"".join(stdout_parts), b"".join(stderr_parts)
