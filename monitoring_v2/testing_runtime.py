# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for the repository test runner."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Never, Protocol, Self, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType


class FunctionDecorator(Protocol):
    """Decorator that preserves the wrapped test signature."""

    def __call__[**Parameters, ReturnValue](
        self,
        function: Callable[Parameters, ReturnValue],
    ) -> Callable[Parameters, ReturnValue]:
        """Return the decorated test with its original type."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class FixtureFactory(Protocol):
    """Named fixture decorator factory."""

    def __call__(self, *, name: str) -> FunctionDecorator:
        """Create a signature-preserving fixture decorator."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class Markers(Protocol):
    """Test markers consumed by the monitoring proof."""

    @property
    def asyncio(self) -> FunctionDecorator:
        """Return the asynchronous-test decorator."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class RaisesContext[ExceptionValue: BaseException](Protocol):
    """Captured exception context returned by the test runner."""

    @property
    def value(self) -> ExceptionValue:
        """Return the captured exception."""
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Enter the exception assertion context."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Exit the exception assertion context."""
        raise NotImplementedError


class RaisesFactory(Protocol):
    """Generic exception assertion factory."""

    def __call__[ExceptionValue: BaseException](
        self,
        expected_exception: type[ExceptionValue],
    ) -> RaisesContext[ExceptionValue]:
        """Return a context that captures the expected exception."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class MonkeyPatch(Protocol):
    """Mutation surface used by isolated monitoring tests."""

    def setenv(self, name: str, value: str) -> None:
        """Set one environment variable for the test lifetime."""
        raise NotImplementedError

    def setattr[Mutation](self, target: Mutation, name: str, value: Mutation) -> None:
        """Replace one object attribute for the test lifetime."""
        raise NotImplementedError


class PytestModule(Protocol):
    """Exact pytest surface consumed by monitoring v2."""

    fixture: FixtureFactory
    mark: Markers
    raises: RaisesFactory

    def fail(self, reason: str) -> Never:
        """Fail the active test with a precise reason."""
        raise NotImplementedError

    def skip(self, reason: str) -> Never:
        """Skip the active test with a precise reason."""
        raise NotImplementedError


pytest = cast("PytestModule", cast("object", import_module("pytest")))
