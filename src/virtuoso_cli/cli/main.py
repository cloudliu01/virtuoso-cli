"""Main vcli entry point."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Final

from virtuoso_cli import __version__
from virtuoso_cli.bridge.client import VirtuosoClient
from virtuoso_cli.domain.errors import ErrorKind, VirtuosoError
from virtuoso_cli.storage.sessions import SessionInfo

if TYPE_CHECKING:
    from virtuoso_cli.domain.models import VirtuosoResult

_JSON_FORMAT: Final = "json"
_DEFAULT_TIMEOUT_SECONDS: Final = 30


def main() -> None:
    """Run the command-line interface."""
    raise SystemExit(run(tuple(sys.argv[1:])))


def run(argv: tuple[str, ...]) -> int:
    """Dispatch the subset of vcli currently migrated to Python."""
    try:
        command_args, output_format = _parse_globals(argv)
        payload = _dispatch(command_args, output_format)
    except VirtuosoError as exc:
        _print_error(exc)
        return exc.exit_code

    if payload is not None and output_format == _JSON_FORMAT:
        sys.stdout.write(f"{json.dumps(payload, separators=(',', ':'))}\n")
    return 0


def _parse_globals(argv: tuple[str, ...]) -> tuple[tuple[str, ...], str]:
    output_format = _JSON_FORMAT
    command_args: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--version":
            sys.stdout.write(f"vcli {__version__}\n")
            return (), "__version_printed__"
        if arg == "--format":
            try:
                output_format = argv[index + 1]
            except IndexError as exc:
                raise VirtuosoError(ErrorKind.CONFIG, "--format requires a value") from exc
            index += 2
            continue
        command_args.append(arg)
        index += 1
    return tuple(command_args), output_format


def _dispatch(argv: tuple[str, ...], output_format: str) -> dict[str, JsonValue] | None:
    if output_format == "__version_printed__":
        return None
    match argv:
        case ("session", "list"):
            return _session_list()
        case ("session", "current"):
            return _session_current()
        case ("session", "show", session_id):
            return _session_show(session_id)
        case ("skill", "exec", code, *args):
            return _skill_exec(code, tuple(args))
        case ():
            raise VirtuosoError(ErrorKind.CONFIG, "missing command")
        case _:
            raise VirtuosoError(ErrorKind.CONFIG, f"unsupported command: {' '.join(argv)}")


JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]


def _session_list() -> dict[str, JsonValue]:
    sessions = SessionInfo.list_alive()
    return {
        "status": "success",
        "count": len(sessions),
        "sessions": [
            {
                "id": session.id,
                "port": session.port,
                "pid": session.pid,
                "host": session.host,
                "user": session.user,
                "created": session.created,
            }
            for session in sessions
        ],
    }


def _session_current() -> dict[str, JsonValue]:
    sessions = SessionInfo.list_alive()
    match len(sessions):
        case 0:
            return {
                "status": "success",
                "session": None,
                "note": "no live sessions; VB_PORT will be used",
            }
        case 1:
            session = sessions[0]
            return {
                "status": "success",
                "session": session.id,
                "port": session.port,
                "auto_selected": True,
            }
        case _:
            return {
                "status": "ambiguous",
                "sessions": [session.id for session in sessions],
                "note": "use --session <id> to select one",
            }


def _session_show(session_id: str) -> dict[str, JsonValue]:
    try:
        session = SessionInfo.load(session_id)
    except FileNotFoundError as exc:
        raise VirtuosoError(ErrorKind.NOT_FOUND, str(exc)) from exc

    alive = session.is_alive()
    return {
        "status": "success",
        "session": {
            "id": session.id,
            "port": session.port,
            "pid": session.pid,
            "host": session.host,
            "user": session.user,
            "created": session.created,
            "alive": alive,
            "daemon_responsive": False,
            "daemon_user": None,
            "daemon_version": None,
            "cli_version": __version__,
        },
        "warnings": {
            "daemon_user": None,
            "cross_user": None,
            "version_skew": None,
            "stale_daemon": None,
        },
    }


def _skill_exec(code: str, args: tuple[str, ...]) -> dict[str, JsonValue]:
    timeout = _parse_timeout(args)
    client = _client_from_env(timeout)
    result = client.execute_skill(code, timeout=timeout)
    return _skill_result_payload(result)


def _parse_timeout(args: tuple[str, ...]) -> int:
    timeout = _DEFAULT_TIMEOUT_SECONDS
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--timeout":
            try:
                timeout = int(args[index + 1])
            except (IndexError, ValueError) as exc:
                raise VirtuosoError(ErrorKind.CONFIG, "--timeout requires an integer") from exc
            index += 2
            continue
        if arg == "--readonly":
            index += 1
            continue
        raise VirtuosoError(ErrorKind.CONFIG, f"unsupported skill exec option: {arg}")
    return timeout


def _client_from_env(timeout: int) -> VirtuosoClient:
    session_id = os.environ.get("VB_SESSION")
    if session_id:
        try:
            session = SessionInfo.load(session_id)
        except FileNotFoundError as exc:
            raise VirtuosoError(ErrorKind.NOT_FOUND, str(exc)) from exc
        return VirtuosoClient("127.0.0.1", session.port, timeout=timeout)

    sessions = SessionInfo.list_alive()
    match len(sessions):
        case 1:
            return VirtuosoClient("127.0.0.1", sessions[0].port, timeout=timeout)
        case session_count if session_count > 1:
            session_ids = ", ".join(session.id for session in sessions)
            message = (
                f"multiple Virtuoso sessions active: {session_ids}. "
                "Use --session <id> to select one."
            )
            raise VirtuosoError(ErrorKind.CONFIG, message)
        case _:
            port = _port_from_env()
            return VirtuosoClient("127.0.0.1", port, timeout=timeout)


def _port_from_env() -> int:
    raw_port = os.environ.get("VB_PORT")
    if raw_port is None:
        raise VirtuosoError(ErrorKind.CONFIG, "no live session found and VB_PORT is not set")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise VirtuosoError(ErrorKind.CONFIG, f"invalid VB_PORT: {raw_port}") from exc
    if port <= 0:
        raise VirtuosoError(ErrorKind.CONFIG, f"invalid VB_PORT: {raw_port}")
    return port


def _skill_result_payload(result: VirtuosoResult) -> dict[str, JsonValue]:
    return {
        "status": "success" if result.ok() else "error",
        "output": result.output,
        "errors": list(result.errors),
        "warnings": list(result.warnings),
        "execution_time": result.execution_time,
    }


def _print_error(error: VirtuosoError) -> None:
    sys.stderr.write(f"{json.dumps(error.to_payload(), separators=(',', ':'))}\n")
