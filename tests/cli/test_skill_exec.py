from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, TypeAdapter

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
STX: Final = b"\x02"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SkillExecResponse(FrozenModel):
    status: str
    output: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    execution_time: float | None


class BroadcastResult(FrozenModel):
    session: str
    ok: bool
    output: str | None = None
    error: str | None = None


class SkillBroadcastResponse(FrozenModel):
    status: str
    sessions: int
    ok: int
    results: tuple[BroadcastResult, ...]


SKILL_EXEC_ADAPTER: Final = TypeAdapter(SkillExecResponse)
SKILL_BROADCAST_ADAPTER: Final = TypeAdapter(SkillBroadcastResponse)


def _run_vcli(
    env: dict[str, str],
    *args: str,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - executes this checkout's Python module
        [sys.executable, "-m", "virtuoso_cli", *args],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        input=stdin,
        text=True,
    )


def _write_session(env: dict[str, str], *, session_id: str, port: int) -> None:
    sessions_dir = Path(env["XDG_CACHE_HOME"]) / "virtuoso_bridge" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f"{session_id}.json").write_text(
        (
            "{"
            f'"id":"{session_id}","port":{port},"pid":0,'
            '"host":"cloud-host","user":"cloud_no_ex_network",'
            '"created":"2026-06-07T06:09:42Z"'
            "}"
        ),
        encoding="utf-8",
    )


def _start_fake_daemon(response: bytes) -> tuple[int, queue.Queue[bytes], threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    requests: queue.Queue[bytes] = queue.Queue(maxsize=1)

    def serve_once() -> None:
        with listener:
            while requests.empty():
                connection, _address = listener.accept()
                with connection:
                    chunks: list[bytes] = []
                    while chunk := connection.recv(65_536):
                        chunks.append(chunk)
                    request = b"".join(chunks)
                    if request:
                        requests.put(request)
                        connection.sendall(response)

    thread = threading.Thread(target=serve_once, daemon=True)
    thread.start()
    return port, requests, thread


def test_skill_exec_uses_auto_selected_session_and_returns_json(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    port, requests, thread = _start_fake_daemon(STX + b"2")
    _write_session(env, session_id="cloud-host-cloud_no_ex_network-46859", port=port)

    result = _run_vcli(env, "--format", "json", "skill", "exec", "plus(1 1)", "--timeout", "7")

    thread.join(timeout=1)
    assert not thread.is_alive(), "fake daemon did not receive the CLI request"
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(requests.get_nowait()) == {"skill": "plus(1 1)", "timeout": 7}
    payload = SKILL_EXEC_ADAPTER.validate_json(result.stdout)
    assert payload.status == "success"
    assert payload.output == "2"
    assert payload.errors == ()
    assert payload.warnings == ()
    assert payload.execution_time is not None


def test_skill_eval_wraps_inline_code_in_progn(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    port, requests, thread = _start_fake_daemon(STX + b"3")
    _write_session(env, session_id="cloud-host-cloud_no_ex_network-46859", port=port)

    result = _run_vcli(env, "--format", "json", "skill", "eval", "plus(1 2)")

    thread.join(timeout=1)
    assert not thread.is_alive(), "fake daemon did not receive the CLI request"
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(requests.get_nowait()) == {
        "skill": "progn(\nplus(1 2)\n)",
        "timeout": 30,
    }
    payload = SKILL_EXEC_ADAPTER.validate_json(result.stdout)
    assert payload.status == "success"
    assert payload.output == "3"


def test_skill_eval_reads_stdin_when_requested(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    port, requests, thread = _start_fake_daemon(STX + b"4")
    _write_session(env, session_id="cloud-host-cloud_no_ex_network-46859", port=port)

    result = _run_vcli(
        env,
        "--format",
        "json",
        "skill",
        "eval",
        "--stdin",
        stdin="plus(2 2)",
    )

    thread.join(timeout=1)
    assert not thread.is_alive(), "fake daemon did not receive the CLI request"
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(requests.get_nowait()) == {
        "skill": "progn(\nplus(2 2)\n)",
        "timeout": 30,
    }
    payload = SKILL_EXEC_ADAPTER.validate_json(result.stdout)
    assert payload.status == "success"
    assert payload.output == "4"


def test_skill_load_sends_escaped_load_expression(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    env["VB_CLIENT_ID"] = "pytest-load"
    skill_file = tmp_path / 'quoted"name.il'
    skill_file.write_text("procedure(test() t)\n", encoding="utf-8")
    scratch_file = Path("/tmp/virtuoso_bridge/pytest-load") / skill_file.name  # noqa: S108
    scratch_file.unlink(missing_ok=True)
    port, requests, thread = _start_fake_daemon(STX + b"t")
    _write_session(env, session_id="cloud-host-cloud_no_ex_network-46859", port=port)

    result = _run_vcli(env, "--format", "json", "skill", "load", str(skill_file))

    thread.join(timeout=1)
    assert not thread.is_alive(), "fake daemon did not receive the CLI request"
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(requests.get_nowait()) == {
        "skill": f'(load "{str(scratch_file).replace(chr(34), chr(92) + chr(34))}")',
        "timeout": 30,
    }
    assert scratch_file.stat().st_mode & 0o004
    scratch_file.unlink(missing_ok=True)
    payload = SKILL_EXEC_ADAPTER.validate_json(result.stdout)
    assert payload.status == "success"
    assert payload.output == "t"


def test_skill_broadcast_runs_code_for_each_live_session(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    first_port, first_requests, first_thread = _start_fake_daemon(STX + b"10")
    second_port, second_requests, second_thread = _start_fake_daemon(STX + b"20")
    _write_session(env, session_id="a-session", port=first_port)
    _write_session(env, session_id="b-session", port=second_port)

    result = _run_vcli(
        env,
        "--format",
        "json",
        "skill",
        "broadcast",
        "plus(9 1)",
        "--timeout",
        "5",
    )

    first_thread.join(timeout=1)
    second_thread.join(timeout=1)
    assert not first_thread.is_alive(), "first fake daemon did not receive the CLI request"
    assert not second_thread.is_alive(), "second fake daemon did not receive the CLI request"
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(first_requests.get_nowait()) == {"skill": "plus(9 1)", "timeout": 5}
    assert json.loads(second_requests.get_nowait()) == {"skill": "plus(9 1)", "timeout": 5}
    payload = SKILL_BROADCAST_ADAPTER.validate_json(result.stdout)
    assert payload == SkillBroadcastResponse(
        status="success",
        sessions=2,
        ok=2,
        results=(
            BroadcastResult(session="a-session", ok=True, output="10"),
            BroadcastResult(session="b-session", ok=True, output="20"),
        ),
    )
