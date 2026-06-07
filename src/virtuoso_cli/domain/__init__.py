"""Framework-independent domain types."""

from virtuoso_cli.domain.errors import ErrorKind, VirtuosoConnectionError, VirtuosoError
from virtuoso_cli.domain.models import ExecutionStatus, VirtuosoResult

__all__ = [
    "ErrorKind",
    "ExecutionStatus",
    "VirtuosoConnectionError",
    "VirtuosoError",
    "VirtuosoResult",
]
