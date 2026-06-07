from __future__ import annotations

import json
import queue
import socket
import threading
from typing import TYPE_CHECKING

import pytest
from virtuoso_cli.bridge.client import VirtuosoClient
from virtuoso_cli.bridge.escaping import escape_skill_string
from virtuoso_cli.domain.errors import VirtuosoConnectionError

if TYPE_CHECKING:
    from collections.abc import Callable

    from virtuoso_cli.domain.models import VirtuosoResult

STX = b"\x02"
NAK = b"\x15"


def _start_fake_server(
    response: bytes,
) -> tuple[int, queue.Queue[bytes], threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    requests: queue.Queue[bytes] = queue.Queue(maxsize=1)

    def serve_once() -> None:
        with listener:
            connection, _address = listener.accept()
            with connection:
                with connection.makefile("rb") as request_stream:
                    requests.put(request_stream.read())
                connection.sendall(response)

    thread = threading.Thread(target=serve_once, daemon=True)
    thread.start()
    return port, requests, thread


def _execute_against(
    response: bytes,
    action: Callable[[VirtuosoClient], None],
) -> bytes:
    port, requests, thread = _start_fake_server(response)
    action(VirtuosoClient(host="127.0.0.1", port=port, timeout=1))
    thread.join(timeout=1)
    assert not thread.is_alive(), "fake bridge server did not finish"
    return requests.get_nowait()


def test_execute_skill_sends_compact_json_request_and_half_closes_write() -> None:
    result_holder: list[VirtuosoResult] = []

    def execute(client: VirtuosoClient) -> None:
        result_holder.append(client.execute_skill('printf("hello")', timeout=7))

    request = _execute_against(STX + b'"hello"', execute)

    assert request == b'{"skill":"printf(\\"hello\\")","timeout":7}'
    assert json.loads(request) == {"skill": 'printf("hello")', "timeout": 7}
    result = result_holder[0]
    assert result.ok()
    assert result.skill_ok()
    assert result.output == '"hello"'


def test_stx_nil_is_transport_success_but_skill_failure() -> None:
    result_holder: list[VirtuosoResult] = []

    def execute(client: VirtuosoClient) -> None:
        result_holder.append(client.execute_skill("nil"))

    _execute_against(STX + b"nil", execute)

    result = result_holder[0]
    assert result.ok()
    assert not result.skill_ok()
    assert result.output == "nil"
    assert result.errors == ()


def test_nak_is_returned_as_transport_failure() -> None:
    result_holder: list[VirtuosoResult] = []

    def execute(client: VirtuosoClient) -> None:
        result_holder.append(client.execute_skill("error()"))

    _execute_against(NAK + b"*Error* eval: unbound variable", execute)

    result = result_holder[0]
    assert not result.ok()
    assert not result.skill_ok()
    assert result.output == ""
    assert result.errors == ("*Error* eval: unbound variable",)


def test_unknown_response_marker_preserves_frame_and_adds_warning() -> None:
    result_holder: list[VirtuosoResult] = []

    def execute(client: VirtuosoClient) -> None:
        result_holder.append(client.execute_skill("1+1"))

    _execute_against(b"\x7fpayload", execute)

    result = result_holder[0]
    assert result.ok()
    assert result.skill_ok()
    assert result.output == "\x7fpayload"
    assert result.warnings == ("non-standard response marker",)


def test_connection_refusal_raises_typed_connection_error() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]

    client = VirtuosoClient(host="127.0.0.1", port=unused_port, timeout=0.05)

    with pytest.raises(VirtuosoConnectionError, match="connection failed"):
        client.execute_skill("1+1")


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("plain", "plain"),
        ("back\\slash", "back\\\\slash"),
        ('double"quote', 'double\\"quote'),
        ("first\nsecond", "first\\nsecond"),
        ('C:\\work\\cell"\nnext', 'C:\\\\work\\\\cell\\"\\nnext'),
    ],
)
def test_escape_skill_string_matches_bridge_contract(raw: str, escaped: str) -> None:
    assert escape_skill_string(raw) == escaped
