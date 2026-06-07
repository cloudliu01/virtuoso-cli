from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, TypeAdapter

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SessionRow(FrozenModel):
    id: str
    port: int
    pid: int
    host: str
    user: str
    created: str


class SessionListResponse(FrozenModel):
    status: str
    count: int
    sessions: tuple[SessionRow, ...]


SESSION_LIST_ADAPTER: Final = TypeAdapter(SessionListResponse)


def _run_vcli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - executes this checkout's Python module
        [sys.executable, "-m", "virtuoso_cli", *args],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_session(
    sessions_dir: Path,
    *,
    session_id: str,
    port: int,
    user: str,
) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session_id}.json"
    path.write_text(
        (
            "{"
            f'"id":"{session_id}","port":{port},"pid":0,'
            f'"host":"cloud-host","user":"{user}",'
            '"created":"2026-06-07T06:09:42Z"'
            "}"
        ),
        encoding="utf-8",
    )
    return path


def _live_listener() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    return listener


def _listener_port(listener: socket.socket) -> int:
    return int(listener.getsockname()[1])


def test_session_list_includes_explicit_extra_registry_path(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    extra_sessions = tmp_path / "cloud_no_ex_network" / ".cache" / "virtuoso_bridge" / "sessions"
    env["VCLI_SESSION_PATHS"] = str(extra_sessions)

    with _live_listener() as listener:
        port = _listener_port(listener)
        _write_session(
            extra_sessions,
            session_id="cloud-host-cloud_no_ex_network-46859",
            port=port,
            user="cloud_no_ex_network",
        )

        result = _run_vcli(env, "--format", "json", "session", "list")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_LIST_ADAPTER.validate_json(result.stdout)
    assert payload == SessionListResponse(
        status="success",
        count=1,
        sessions=(
            SessionRow(
                id="cloud-host-cloud_no_ex_network-46859",
                port=port,
                pid=0,
                host="cloud-host",
                user="cloud_no_ex_network",
                created="2026-06-07T06:09:42Z",
            ),
        ),
    )


def test_session_list_ignores_unreadable_extra_registry_path(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    env["VCLI_SESSION_PATHS"] = str(private_dir / "sessions")

    private_dir.chmod(0)
    try:
        result = _run_vcli(env, "--format", "json", "session", "list")
    finally:
        private_dir.chmod(0o700)

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_LIST_ADAPTER.validate_json(result.stdout)
    assert payload == SessionListResponse(status="success", count=0, sessions=())
