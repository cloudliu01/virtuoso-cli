"""Main virtuoso-daemon entry point."""

from __future__ import annotations

import json
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from virtuoso_cli import __version__

NAK: Final = b"\x15"
RS: Final = 0x1E
_POLL_SECONDS: Final = 0.01
_REQUIRED_ARG_COUNT: Final = 2
_MAX_PORT: Final = 65_535


@dataclass(slots=True)
class _Stats:
    """Mutable daemon counters."""

    calls: int
    errors: int
    started_at: float


class _InvalidRequestError(Exception):
    """Malformed daemon request."""

    def __init__(self, detail: str) -> None:
        """Create an invalid request error."""
        self.detail = detail
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return the Rust-compatible daemon error detail."""
        return f"invalid json: {self.detail}"


def main() -> None:
    """Run the callback-file bridge daemon."""
    raise SystemExit(run(tuple(sys.argv[1:])))


def run(argv: tuple[str, ...]) -> int:
    """Run the daemon process."""
    if argv[:1] == ("--version",):
        _write_stdout(f"{__version__}\n")
        return 0

    if len(argv) < _REQUIRED_ARG_COUNT:
        _write_stderr("usage: virtuoso-daemon <host> <port>\n")
        return 1

    host = argv[0]
    try:
        port = _parse_port(argv[1])
    except ValueError:
        _write_stderr(f"invalid port: {argv[1]}\n")
        return 1

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
            listener.listen()
            actual_port = int(listener.getsockname()[1])
            _print_startup(host, actual_port)
            _serve(listener, actual_port)
    except OSError as exc:
        _write_stderr(f"failed to bind {host}:{port}: {exc}\n")
        return 1
    return 0


def _parse_port(raw: str) -> int:
    port = int(raw)
    if not 0 <= port <= _MAX_PORT:
        raise ValueError(raw)
    return port


def _print_startup(host: str, port: int) -> None:
    _write_stderr(f"VERSION:{__version__}\n")
    _write_stderr(f"PORT:{port}\n")
    _write_stderr(f"[virtuoso-daemon] listening on {host}:{port}\n")


def _serve(listener: socket.socket, actual_port: int) -> None:
    callback_port = actual_port + 1
    stats = _Stats(calls=0, errors=0, started_at=time.monotonic())
    while True:
        connection, _address = listener.accept()
        with connection:
            try:
                _handle_connection(connection, callback_port, actual_port, stats)
            except _InvalidRequestError as exc:
                _write_stderr(f"[virtuoso-daemon] error: {exc}\n")


def _handle_connection(
    connection: socket.socket,
    callback_port: int,
    actual_port: int,
    stats: _Stats,
) -> None:
    stats.calls += 1
    request_bytes = _receive_all(connection)
    try:
        request = json.loads(request_bytes.decode("utf-8"))
        skill = str(request["skill"])
        timeout = int(request.get("timeout", 30))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _InvalidRequestError(str(exc)) from exc

    data_file, done_file = _callback_files(callback_port)
    data_file.unlink(missing_ok=True)
    done_file.unlink(missing_ok=True)

    sys.stdout.write(skill)
    sys.stdout.flush()

    response = _read_callback_file(data_file, done_file, timeout)
    if response.startswith(NAK):
        stats.errors += 1
    _write_stats(actual_port, stats)
    connection.sendall(response)
    connection.shutdown(socket.SHUT_RDWR)


def _receive_all(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while chunk := connection.recv(65_536):
        chunks.append(chunk)
    return b"".join(chunks)


def _callback_files(callback_port: int) -> tuple[Path, Path]:
    data_file = Path(f"/tmp/.ramic_cb_{callback_port}")  # noqa: S108
    return data_file, Path(f"{data_file}.done")


def _read_callback_file(data_file: Path, done_file: Path, timeout: int) -> bytes:
    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            return NAK + b"TimeoutError"
        if done_file.exists():
            try:
                data = data_file.read_bytes()
            except OSError:
                time.sleep(_POLL_SECONDS)
                continue
            data_file.unlink(missing_ok=True)
            done_file.unlink(missing_ok=True)
            if data.endswith(bytes((RS,))):
                return data[:-1]
            return data
        time.sleep(_POLL_SECONDS)


def _write_stats(port: int, stats: _Stats) -> None:
    uptime_secs = int(time.monotonic() - stats.started_at)
    payload = f'{{"calls":{stats.calls},"errors":{stats.errors},"uptime_secs":{uptime_secs}}}'
    Path(f"/tmp/.ramic_stats_{port}").write_text(payload, encoding="utf-8")  # noqa: S108


def _write_stdout(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


def _write_stderr(message: str) -> None:
    sys.stderr.write(message)
    sys.stderr.flush()
