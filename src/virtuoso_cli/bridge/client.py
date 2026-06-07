"""TCP bridge client compatible with the Rust daemon protocol."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Final

from virtuoso_cli.domain.errors import ErrorKind, VirtuosoConnectionError, VirtuosoError
from virtuoso_cli.domain.models import ExecutionStatus, VirtuosoResult

STX: Final = 0x02
NAK: Final = 0x15
MAX_RESPONSE_SIZE: Final = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class VirtuosoClient:
    """Synchronous client for the local Virtuoso bridge daemon."""

    host: str
    port: int
    timeout: float = 30

    def execute_skill(self, skill_code: str, timeout: float | None = None) -> VirtuosoResult:
        """Execute SKILL and return the two-layer bridge result."""
        request_timeout = self.timeout if timeout is None else timeout
        request = json.dumps(
            {"skill": skill_code, "timeout": request_timeout},
            separators=(",", ":"),
        ).encode("utf-8")
        start = time.monotonic()
        data = self._send_request(request, request_timeout)

        if not data:
            raise VirtuosoError(ErrorKind.EXECUTION, "empty response from daemon")

        marker = data[0]
        payload = data[1:].decode("utf-8", errors="replace")
        elapsed = time.monotonic() - start

        match marker:
            case 0x02:
                return VirtuosoResult(
                    status=ExecutionStatus.SUCCESS,
                    output=payload,
                    execution_time=elapsed,
                )
            case 0x15:
                return VirtuosoResult(
                    status=ExecutionStatus.ERROR,
                    output="",
                    errors=(payload,),
                    execution_time=elapsed,
                )
            case _:
                return VirtuosoResult(
                    status=ExecutionStatus.SUCCESS,
                    output=data.decode("utf-8", errors="replace"),
                    warnings=("non-standard response marker",),
                    execution_time=elapsed,
                )

    def _send_request(self, request: bytes, timeout: float) -> bytes:
        try:
            with socket.create_connection((self.host, self.port), timeout) as stream:
                stream.settimeout(timeout)
                stream.sendall(request)
                stream.shutdown(socket.SHUT_WR)
                return _read_response(stream)
        except OSError as exc:
            raise VirtuosoConnectionError(str(exc)) from exc


def _read_response(stream: socket.socket) -> bytes:
    chunks: list[bytes] = []
    total_size = 0
    while chunk := stream.recv(65_536):
        total_size += len(chunk)
        if total_size > MAX_RESPONSE_SIZE:
            raise VirtuosoError(
                ErrorKind.EXECUTION,
                f"response exceeds {MAX_RESPONSE_SIZE // 1024 // 1024}MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)
