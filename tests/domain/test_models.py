from virtuoso_cli.domain.models import ExecutionStatus, VirtuosoResult


def test_transport_success_and_skill_success_are_distinct() -> None:
    result = VirtuosoResult.success("nil")

    assert result.ok()
    assert not result.skill_ok()


def test_non_nil_skill_result_is_successful() -> None:
    result = VirtuosoResult.success('"hello"')

    assert result.ok()
    assert result.skill_ok()
    assert result.output_unquoted() == "hello"


def test_transport_error_is_not_skill_success() -> None:
    result = VirtuosoResult.error(["TimeoutError"])

    assert result.status is ExecutionStatus.ERROR
    assert not result.ok()
    assert not result.skill_ok()
