"""Session-file storage compatible with the Rust CLI."""

from __future__ import annotations

import json
import os
import pwd
import re
import socket
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_CONNECT_TIMEOUT: Final = 0.05
_SUDO: Final = Path("/usr/bin/sudo")
_PYTHON3: Final = Path("/usr/bin/python3")
_USER_RE: Final = re.compile(r"[A-Za-z0-9_.-]+")
_LIST_SESSIONS_SCRIPT: Final = (
    "import json,sys\n"
    "from pathlib import Path\n"
    "items=[]\n"
    "for path in sorted(Path(sys.argv[1]).glob('*.json')):\n"
    "    try:\n"
    "        items.append(json.loads(path.read_text(encoding='utf-8')))\n"
    "    except (OSError, ValueError):\n"
    "        pass\n"
    "print(json.dumps(items,separators=(',',':')))\n"
)
JsonScalar = str | int | None


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """Registered Virtuoso bridge session."""

    id: str
    port: int
    pid: int
    host: str
    user: str
    created: str
    daemon_user: str | None = None
    daemon_version: str | None = None
    source_dir: Path | None = None

    @classmethod
    def sessions_dir(cls) -> Path:
        """Return the directory containing session JSON files."""
        cache_home = os.environ.get("XDG_CACHE_HOME")
        base = Path(cache_home) if cache_home else Path.home() / ".cache"
        return base / "virtuoso_bridge" / "sessions"

    @classmethod
    def load(cls, session_id: str) -> SessionInfo:
        """Load a single session file by ID."""
        path = cls.sessions_dir() / f"{session_id}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            message = f"session '{session_id}' not found: {exc}"
            raise FileNotFoundError(message) from exc
        return cls._from_json(raw)

    @classmethod
    def list(cls) -> tuple[SessionInfo, ...]:
        """Load all parseable sessions sorted by ID."""
        sessions_by_id: dict[str, SessionInfo] = {}
        for directory in _session_directories():
            for session in cls._list_directory(directory):
                sessions_by_id.setdefault(session.id, session)
        for user in _session_users():
            for session in cls._list_user_via_sudo(user):
                sessions_by_id.setdefault(session.id, session)
        return tuple(sorted(sessions_by_id.values(), key=lambda session: session.id))

    @classmethod
    def list_alive(cls) -> tuple[SessionInfo, ...]:
        """Return live sessions and remove stale session files."""
        live: list[SessionInfo] = []
        for session in cls.list():
            if session.is_alive():
                live.append(session)
            else:
                _remove_file(session.path())
        return tuple(live)

    @classmethod
    def _load_path(cls, path: Path) -> SessionInfo | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls._from_json(raw, source_dir=path.parent)
        except (OSError, TypeError, ValueError):
            return None

    @classmethod
    def _list_directory(cls, directory: Path) -> tuple[SessionInfo, ...]:
        if not _path_exists(directory):
            return ()

        sessions: list[SessionInfo] = []
        try:
            paths = tuple(directory.glob("*.json"))
        except OSError:
            return ()
        for path in paths:
            session = cls._load_path(path)
            if session is not None:
                sessions.append(session)
        return tuple(sessions)

    @classmethod
    def _list_user_via_sudo(cls, user: str) -> tuple[SessionInfo, ...]:
        directory = _session_dir_for_user(user)
        if directory is None or not _can_sudo_read_user(user):
            return ()

        result = subprocess.run(  # noqa: S603 - argv is fixed; user is allow-list validated.
            [
                str(_SUDO),
                "-n",
                "-u",
                user,
                str(_PYTHON3),
                "-c",
                _LIST_SESSIONS_SCRIPT,
                str(directory),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return ()

        sessions: list[SessionInfo] = []
        try:
            raw_sessions = json.loads(result.stdout)
        except json.JSONDecodeError:
            return ()
        for raw in raw_sessions:
            session = cls._from_json_or_none(raw, source_dir=directory)
            if session is not None:
                sessions.append(session)
        return tuple(sessions)

    @classmethod
    def _from_json(
        cls,
        raw: dict[str, JsonScalar],
        *,
        source_dir: Path | None = None,
    ) -> SessionInfo:
        return cls(
            id=str(_required(raw, "id")),
            port=int(_required(raw, "port")),
            pid=int(_required(raw, "pid")),
            host=str(_required(raw, "host")),
            user=str(_required(raw, "user")),
            created=str(_required(raw, "created")),
            daemon_user=_optional_str(raw.get("daemon_user")),
            daemon_version=_optional_str(raw.get("daemon_version")),
            source_dir=source_dir,
        )

    @classmethod
    def _from_json_or_none(
        cls,
        raw: dict[str, JsonScalar],
        *,
        source_dir: Path,
    ) -> SessionInfo | None:
        try:
            return cls._from_json(raw, source_dir=source_dir)
        except (TypeError, ValueError):
            return None

    def path(self) -> Path:
        """Return this session's JSON path."""
        directory = self.source_dir if self.source_dir is not None else self.sessions_dir()
        return directory / f"{self.id}.json"

    def is_alive(self) -> bool:
        """Check whether the registered local daemon port is bound."""
        try:
            with socket.create_connection(("127.0.0.1", self.port), _CONNECT_TIMEOUT):
                return True
        except OSError:
            return False


def _optional_str(value: str | int | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _required(raw: dict[str, JsonScalar], key: str) -> str | int:
    value = raw.get(key)
    if value is None:
        raise ValueError(key)
    return value


def _session_directories() -> tuple[Path, ...]:
    directories = [SessionInfo.sessions_dir()]
    extra_paths = os.environ.get("VCLI_SESSION_PATHS", "")
    directories.extend(
        Path(raw_path).expanduser() for raw_path in extra_paths.split(os.pathsep) if raw_path
    )
    for user in _session_users():
        directory = _session_dir_for_user(user)
        if directory is not None:
            directories.append(directory)
    return _dedupe_paths(tuple(directories))


def _session_users() -> tuple[str, ...]:
    raw_users = os.environ.get("VCLI_SESSION_USERS", "")
    users = [
        raw_user
        for raw_user in re.split(r"[\s,]+", raw_users)
        if raw_user and _USER_RE.fullmatch(raw_user)
    ]
    return tuple(dict.fromkeys(users))


def _session_dir_for_user(user: str) -> Path | None:
    try:
        home = Path(pwd.getpwnam(user).pw_dir)
    except KeyError:
        return None
    return home / ".cache" / "virtuoso_bridge" / "sessions"


def _can_sudo_read_user(user: str) -> bool:
    return _SUDO.exists() and _PYTHON3.exists() and _USER_RE.fullmatch(user) is not None


def _dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    deduped: dict[str, Path] = {}
    for path in paths:
        deduped.setdefault(str(path), path)
    return tuple(deduped.values())


def _remove_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False
