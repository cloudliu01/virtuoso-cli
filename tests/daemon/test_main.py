from __future__ import annotations

import json
import os
import re
import select
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_ROOT = Path(__file__).resolve().parents[2]
_VERSION = "0.4.0-alpha.9"
_DAEMON_CODE = "from virtuoso_cli.daemon.main import main; main()"
_IO_TIMEOUT_SECONDS = 2.0


def _daemon_command(*args: str) -> list[str]:
    return [sys.executable, "-c", _DAEMON_CODE, *args]


def _daemon_env() -> dict[str, str]:
    env = os.environ.copy()
    source_path = str(_ROOT / "src")
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{source_path}{os.pathsep}{current_pythonpath}" if current_pythonpath else source_path
    )
    return env


def _run_daemon(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603
        _daemon_command(*args),
        cwd=_ROOT,
        env=_daemon_env(),
        capture_output=True,
        check=False,
        timeout=_IO_TIMEOUT_SECONDS,
    )


def _read_available(fd: int, *, timeout: float = _IO_TIMEOUT_SECONDS) -> bytes:
    readable, _, _ = select.select([fd], [], [], timeout)
    if not readable:
        pytest.fail(f"timed out waiting for file descriptor {fd}")
    return os.read(fd, 65_536)


def _read_startup_lines(fd: int) -> tuple[str, str, str]:
    data = bytearray()
    deadline = time.monotonic() + _IO_TIMEOUT_SECONDS
    while data.count(b"\n") < 3:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"timed out waiting for daemon startup banners; got {bytes(data)!r}")
        chunk = _read_available(fd, timeout=remaining)
        if not chunk:
            pytest.fail(f"daemon exited before startup banners; got {bytes(data)!r}")
        data.extend(chunk)

    first, second, third = bytes(data).splitlines()
    return first.decode("utf-8"), second.decode("utf-8"), third.decode("utf-8")


def _read_exact(fd: int, size: int) -> bytes:
    data = bytearray()
    deadline = time.monotonic() + _IO_TIMEOUT_SECONDS
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"timed out after reading {bytes(data)!r}; expected {size} bytes")
        chunk = _read_available(fd, timeout=remaining)
        if not chunk:
            pytest.fail(f"pipe closed after {bytes(data)!r}; expected {size} bytes")
        data.extend(chunk)
    assert len(data) == size
    return bytes(data)


def _receive_all(client: socket.socket) -> bytes:
    client.settimeout(_IO_TIMEOUT_SECONDS)
    chunks: list[bytes] = []
    while chunk := client.recv(65_536):
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True, slots=True)
class _Stats:
    calls: int
    errors: int
    uptime_secs: int


def _read_stats(path: Path) -> _Stats:
    match = re.fullmatch(
        r'\{"calls":(\d+),"errors":(\d+),"uptime_secs":(\d+)\}',
        path.read_text(encoding="utf-8"),
    )
    assert match is not None
    calls, errors, uptime_secs = match.groups()
    return _Stats(int(calls), int(errors), int(uptime_secs))


@dataclass(frozen=True, slots=True)
class _RunningDaemon:
    process: subprocess.Popen[bytes]
    port: int
    callback_data: Path
    callback_done: Path
    stats: Path

    def request(self, payload: bytes) -> socket.socket:
        client = socket.create_connection(("127.0.0.1", self.port), _IO_TIMEOUT_SECONDS)
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        return client

    def write_callback(self, payload: bytes) -> None:
        self.callback_data.write_bytes(payload)
        self.callback_done.touch()


@pytest.fixture
def running_daemon() -> Iterator[_RunningDaemon]:
    process = subprocess.Popen(  # noqa: S603
        _daemon_command("127.0.0.1", "0"),
        cwd=_ROOT,
        env=_daemon_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    artifacts: tuple[Path, ...] = ()
    try:
        assert process.stdout is not None
        assert process.stderr is not None

        version_line, port_line, listening_line = _read_startup_lines(process.stderr.fileno())
        assert version_line == f"VERSION:{_VERSION}"
        assert port_line.startswith("PORT:")
        port = int(port_line.removeprefix("PORT:"))
        assert listening_line == f"[virtuoso-daemon] listening on 127.0.0.1:{port}"

        callback_data = Path(f"/tmp/.ramic_cb_{port + 1}")  # noqa: S108
        callback_done = Path(f"/tmp/.ramic_cb_{port + 1}.done")  # noqa: S108
        stats = Path(f"/tmp/.ramic_stats_{port}")  # noqa: S108
        artifacts = callback_data, callback_done, stats
        for artifact in artifacts:
            artifact.unlink(missing_ok=True)

        daemon = _RunningDaemon(process, port, callback_data, callback_done, stats)
        yield daemon
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=_IO_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_IO_TIMEOUT_SECONDS)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        for artifact in artifacts:
            artifact.unlink(missing_ok=True)


def test_version_prints_exact_rust_semver_and_exits_zero() -> None:
    result = _run_daemon("--version", "ignored")

    assert result.returncode == 0
    assert result.stdout == f"{_VERSION}\n".encode()
    assert result.stderr == b""


@pytest.mark.parametrize("args", [(), ("127.0.0.1",)])
def test_missing_required_arguments_prints_usage_and_exits_one(args: tuple[str, ...]) -> None:
    result = _run_daemon(*args)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b"usage: virtuoso-daemon <host> <port>\n"


@pytest.mark.parametrize("port", ["not-a-port", "-1", "65536"])
def test_invalid_port_prints_raw_value_and_exits_one(port: str) -> None:
    result = _run_daemon("127.0.0.1", port)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == f"invalid port: {port}\n".encode()


def test_port_zero_emits_ordered_dynamic_port_banners(running_daemon: _RunningDaemon) -> None:
    assert 1 <= running_daemon.port <= 65_535
    assert running_daemon.process.poll() is None


def test_callback_response_strips_one_trailing_rs_and_writes_success_stats(
    running_daemon: _RunningDaemon,
) -> None:
    skill = 'println("ready")'
    request = json.dumps({"skill": skill, "timeout": 2}).encode()

    with running_daemon.request(request) as client:
        assert running_daemon.process.stdout is not None
        assert _read_exact(running_daemon.process.stdout.fileno(), len(skill)) == skill.encode()
        running_daemon.write_callback(b"\x02ready\x1e\x1e")
        response = _receive_all(client)

    assert response == b"\x02ready\x1e"
    assert not running_daemon.callback_data.exists()
    assert not running_daemon.callback_done.exists()
    stats = _read_stats(running_daemon.stats)
    assert stats.calls == 1
    assert stats.errors == 0
    assert stats.uptime_secs >= 0


def test_zero_timeout_returns_exact_nak_and_increments_error_stats(
    running_daemon: _RunningDaemon,
) -> None:
    request = json.dumps({"skill": "1+1", "timeout": 0}).encode()

    with running_daemon.request(request) as client:
        response = _receive_all(client)

    assert response == b"\x15TimeoutError"
    stats = _read_stats(running_daemon.stats)
    assert stats.calls == 1
    assert stats.errors == 1


def test_malformed_json_closes_connection_and_daemon_recovers(
    running_daemon: _RunningDaemon,
) -> None:
    with running_daemon.request(b"{") as malformed_client:
        malformed_response = _receive_all(malformed_client)

    assert malformed_response == b""
    assert running_daemon.process.stderr is not None
    error_output = _read_available(running_daemon.process.stderr.fileno())
    assert error_output.startswith(b"[virtuoso-daemon] error: invalid json:")
    assert running_daemon.process.poll() is None

    skill = "2+2"
    with running_daemon.request(json.dumps({"skill": skill}).encode()) as valid_client:
        assert running_daemon.process.stdout is not None
        assert _read_exact(running_daemon.process.stdout.fileno(), len(skill)) == skill.encode()
        running_daemon.write_callback(b"\x024\x1e")
        valid_response = _receive_all(valid_client)

    assert valid_response == b"\x024"
    stats = _read_stats(running_daemon.stats)
    assert stats.calls == 2
    assert stats.errors == 0
