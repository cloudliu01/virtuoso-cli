from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
CLI_VERSION: Final = "0.4.0-alpha.9"


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


class SessionCurrentResponse(FrozenModel):
    status: str
    session: str | None = None
    port: int | None = None
    auto_selected: bool | None = None
    sessions: tuple[str, ...] | None = None
    note: str | None = None


class SessionDetails(SessionRow):
    alive: bool
    daemon_responsive: bool
    daemon_user: str | None
    daemon_version: str | None
    cli_version: str


class SessionWarnings(FrozenModel):
    daemon_user: str | None
    cross_user: str | None
    version_skew: str | None
    stale_daemon: str | None


class SessionShowResponse(FrozenModel):
    status: str
    session: SessionDetails
    warnings: SessionWarnings


class CliErrorResponse(FrozenModel):
    error: str
    message: str
    suggestion: str | None = None
    diagnostic: str | None = None
    retryable: bool


SESSION_LIST_ADAPTER: Final = TypeAdapter(SessionListResponse)
SESSION_CURRENT_ADAPTER: Final = TypeAdapter(SessionCurrentResponse)
SESSION_SHOW_ADAPTER: Final = TypeAdapter(SessionShowResponse)
CLI_ERROR_ADAPTER: Final = TypeAdapter(CliErrorResponse)


@pytest.fixture
def cli_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    for key in (
        "VB_PROFILE",
        "VB_REMOTE_HOST",
        "VB_SESSION",
        "VCLI_API_KEY",
        "VIRTUAL_ENV",
    ):
        env.pop(key, None)
    return env


def run_vcli(cli_env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - executes this checkout's Python module
        [sys.executable, "-m", "virtuoso_cli", *args],
        cwd=PROJECT_ROOT,
        env=cli_env,
        check=False,
        capture_output=True,
        text=True,
    )


def write_session(
    cli_env: dict[str, str],
    *,
    session_id: str,
    port: int,
    pid: int = 1234,
) -> Path:
    sessions_dir = Path(cli_env["XDG_CACHE_HOME"]) / "virtuoso_bridge" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session_id}.json"
    path.write_text(
        (
            "{"
            f'"id":"{session_id}","port":{port},"pid":{pid},'
            '"host":"eda-host","user":"designer",'
            '"created":"2026-06-07T12:00:00Z"'
            "}"
        ),
        encoding="utf-8",
    )
    return path


def live_listener() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    return listener


def listener_port(listener: socket.socket) -> int:
    host_port = listener.getsockname()
    return int(host_port[1])


def test_version_returns_release_version(cli_env: dict[str, str]) -> None:
    result = run_vcli(cli_env, "--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"vcli {CLI_VERSION}"
    assert result.stderr == ""


def test_session_list_accepts_global_format_after_command_and_removes_stale(
    cli_env: dict[str, str],
) -> None:
    with live_listener() as listener:
        port = listener_port(listener)
        write_session(cli_env, session_id="live-session", port=port)
        stale_path = write_session(cli_env, session_id="stale-session", port=1)

        result = run_vcli(cli_env, "session", "list", "--format", "json")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_LIST_ADAPTER.validate_json(result.stdout)
    assert payload == SessionListResponse(
        status="success",
        count=1,
        sessions=(
            SessionRow(
                id="live-session",
                port=port,
                pid=1234,
                host="eda-host",
                user="designer",
                created="2026-06-07T12:00:00Z",
            ),
        ),
    )
    assert not stale_path.exists()


def test_session_current_with_no_live_sessions(cli_env: dict[str, str]) -> None:
    result = run_vcli(cli_env, "--format", "json", "session", "current")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_CURRENT_ADAPTER.validate_json(result.stdout)
    assert payload == SessionCurrentResponse(
        status="success",
        session=None,
        note="no live sessions; VB_PORT will be used",
    )


def test_session_current_auto_selects_one_live_session(
    cli_env: dict[str, str],
) -> None:
    with live_listener() as listener:
        port = listener_port(listener)
        write_session(cli_env, session_id="only-session", port=port)

        result = run_vcli(cli_env, "session", "current", "--format", "json")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_CURRENT_ADAPTER.validate_json(result.stdout)
    assert payload == SessionCurrentResponse(
        status="success",
        session="only-session",
        port=port,
        auto_selected=True,
    )


def test_session_current_reports_multiple_sessions_without_error(
    cli_env: dict[str, str],
) -> None:
    with live_listener() as first_listener, live_listener() as second_listener:
        first_port = listener_port(first_listener)
        second_port = listener_port(second_listener)
        write_session(cli_env, session_id="z-session", port=first_port)
        write_session(cli_env, session_id="a-session", port=second_port)

        result = run_vcli(cli_env, "--format", "json", "session", "current")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_CURRENT_ADAPTER.validate_json(result.stdout)
    assert payload == SessionCurrentResponse(
        status="ambiguous",
        sessions=("a-session", "z-session"),
        note="use --session <id> to select one",
    )


def test_session_show_reports_a_dead_registered_session(
    cli_env: dict[str, str],
) -> None:
    write_session(cli_env, session_id="dead-session", port=1)

    result = run_vcli(cli_env, "session", "show", "dead-session", "--format", "json")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = SESSION_SHOW_ADAPTER.validate_json(result.stdout)
    assert payload.status == "success"
    assert payload.session.id == "dead-session"
    assert payload.session.alive is False
    assert payload.session.daemon_responsive is False
    assert payload.session.cli_version == CLI_VERSION
    assert payload.warnings == SessionWarnings(
        daemon_user=None,
        cross_user=None,
        version_skew=None,
        stale_daemon=None,
    )


def test_session_show_missing_is_json_error_on_stderr(
    cli_env: dict[str, str],
) -> None:
    result = run_vcli(cli_env, "--format", "json", "session", "show", "missing")

    assert result.returncode == 3
    assert result.stdout == ""
    payload = CLI_ERROR_ADAPTER.validate_json(result.stderr)
    assert payload.error == "not_found"
    assert "session 'missing' not found" in payload.message
    assert payload.suggestion == "Use 'vcli session list' to see active sessions"
    assert payload.retryable is False
