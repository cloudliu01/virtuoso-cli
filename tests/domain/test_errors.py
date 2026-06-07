import pytest
from virtuoso_cli.domain.errors import ErrorKind, VirtuosoError


@pytest.mark.parametrize(
    ("kind", "exit_code", "error_type"),
    [
        (ErrorKind.CONNECTION, 1, "connection_failed"),
        (ErrorKind.EXECUTION, 1, "execution_failed"),
        (ErrorKind.TIMEOUT, 1, "timeout"),
        (ErrorKind.CONFIG, 2, "config_error"),
        (ErrorKind.AUTH, 2, "auth_error"),
        (ErrorKind.NOT_FOUND, 3, "not_found"),
        (ErrorKind.CONFLICT, 5, "conflict"),
    ],
)
def test_error_exit_code_and_wire_type(
    kind: ErrorKind,
    exit_code: int,
    error_type: str,
) -> None:
    error = VirtuosoError(kind, "detail")

    assert error.exit_code == exit_code
    assert error.error_type == error_type


def test_connection_error_is_retryable_and_suggests_tunnel() -> None:
    error = VirtuosoError(ErrorKind.CONNECTION, "refused")

    assert error.retryable
    assert error.suggestion == "Run: virtuoso tunnel start"
    assert error.to_payload() == {
        "error": "connection_failed",
        "message": "connection failed: refused",
        "suggestion": "Run: virtuoso tunnel start",
        "retryable": True,
    }
