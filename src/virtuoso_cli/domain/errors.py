"""Typed application errors and CLI serialization."""

from __future__ import annotations

from enum import Enum


class ErrorKind(str, Enum):
    """Stable error categories exposed by the CLI."""

    CONNECTION = "connection"
    EXECUTION = "execution"
    SSH = "ssh"
    IO = "io"
    JSON = "json"
    TIMEOUT = "timeout"
    CONFIG = "config"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    AUTH = "auth"


_PREFIXES: dict[ErrorKind, str] = {
    ErrorKind.CONNECTION: "connection failed",
    ErrorKind.EXECUTION: "execution failed",
    ErrorKind.SSH: "ssh error",
    ErrorKind.IO: "io error",
    ErrorKind.JSON: "json error",
    ErrorKind.TIMEOUT: "timeout after",
    ErrorKind.CONFIG: "config error",
    ErrorKind.NOT_FOUND: "not found",
    ErrorKind.CONFLICT: "conflict",
    ErrorKind.AUTH: "auth error",
}

_ERROR_TYPES: dict[ErrorKind, str] = {
    ErrorKind.CONNECTION: "connection_failed",
    ErrorKind.EXECUTION: "execution_failed",
    ErrorKind.SSH: "ssh_error",
    ErrorKind.IO: "io_error",
    ErrorKind.JSON: "json_error",
    ErrorKind.TIMEOUT: "timeout",
    ErrorKind.CONFIG: "config_error",
    ErrorKind.NOT_FOUND: "not_found",
    ErrorKind.CONFLICT: "conflict",
    ErrorKind.AUTH: "auth_error",
}


class VirtuosoError(Exception):
    """Application error with stable CLI semantics."""

    def __init__(self, kind: ErrorKind, detail: str) -> None:
        """Create an error in a stable category."""
        self.kind = kind
        self.detail = detail
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return the user-facing Rust-compatible message."""
        if self.kind is ErrorKind.TIMEOUT:
            return f"{_PREFIXES[self.kind]} {self.detail}s"
        return f"{_PREFIXES[self.kind]}: {self.detail}"

    @property
    def exit_code(self) -> int:
        """Return the public process exit code."""
        if self.kind in {ErrorKind.CONFIG, ErrorKind.AUTH}:
            return 2
        if self.kind is ErrorKind.NOT_FOUND:
            return 3
        if self.kind is ErrorKind.CONFLICT:
            return 5
        return 1

    @property
    def error_type(self) -> str:
        """Return the stable JSON error identifier."""
        return _ERROR_TYPES[self.kind]

    @property
    def retryable(self) -> bool:
        """Whether retrying the operation may succeed."""
        return self.kind in {ErrorKind.CONNECTION, ErrorKind.TIMEOUT}

    @property
    def suggestion(self) -> str | None:
        """Return the same common recovery hint as the Rust CLI."""
        suggestion: str | None = None
        if self.kind is ErrorKind.CONNECTION:
            suggestion = "Run: virtuoso tunnel start"
        elif self.kind is ErrorKind.TIMEOUT:
            try:
                seconds = int(self.detail)
            except ValueError:
                pass
            else:
                suggestion = f"Retry with --timeout {seconds * 2}"
        elif self.kind is ErrorKind.NOT_FOUND:
            suggestion = "Use 'vcli session list' to see active sessions"
        elif self.kind is ErrorKind.CONFIG and "VB_REMOTE_HOST" in self.detail:
            suggestion = "Run: virtuoso init"
        elif self.kind is ErrorKind.SSH and "authentication" in self.detail:
            suggestion = "Check SSH keys: ssh-add -l"
        return suggestion

    def to_payload(self) -> dict[str, object]:
        """Serialize the compact JSON error envelope."""
        payload: dict[str, object] = {
            "error": self.error_type,
            "message": str(self),
        }
        suggestion = self.suggestion
        if suggestion is not None:
            payload["suggestion"] = suggestion
        payload["retryable"] = self.retryable
        return payload


class VirtuosoConnectionError(VirtuosoError):
    """A typed bridge connection failure."""

    def __init__(self, detail: str) -> None:
        """Create a connection failure."""
        super().__init__(ErrorKind.CONNECTION, detail)
