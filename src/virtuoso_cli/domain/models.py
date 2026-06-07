"""Shared result models used by the CLI, TUI, and future SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _empty_metadata() -> Mapping[str, str]:
    return {}


class ExecutionStatus(str, Enum):
    """Bridge execution status."""

    SUCCESS = "Success"
    FAILURE = "Failure"
    PARTIAL = "Partial"
    ERROR = "Error"


@dataclass(frozen=True, slots=True)
class VirtuosoResult:
    """A bridge result with separate transport and SKILL success layers."""

    status: ExecutionStatus
    output: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    execution_time: float | None = None
    metadata: Mapping[str, str] = field(default_factory=_empty_metadata)

    def ok(self) -> bool:
        """Return transport-layer success."""
        return self.status is ExecutionStatus.SUCCESS

    def skill_ok(self) -> bool:
        """Return success only when transport succeeded and SKILL was non-nil."""
        return self.ok() and self.output.strip() != "nil"

    def output_unquoted(self) -> str:
        """Strip surrounding SKILL double quotes."""
        return self.output.strip('"')

    @classmethod
    def success(cls, output: str) -> VirtuosoResult:
        """Construct a transport-success result."""
        return cls(status=ExecutionStatus.SUCCESS, output=output)

    @classmethod
    def error(cls, errors: Sequence[str]) -> VirtuosoResult:
        """Construct a transport-error result."""
        return cls(
            status=ExecutionStatus.ERROR,
            output="",
            errors=tuple(errors),
        )
