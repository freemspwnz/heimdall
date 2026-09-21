import io

from heimdall.channels.cli import CliChannel
from heimdall.models import Action

ACTION = Action(
    tool="restart",
    target="postgres",
    reason="контейнер нездоров",
    risk="рестарт рвёт активные соединения",
)


def channel(answer: str) -> tuple[CliChannel, io.StringIO]:
    stdout = io.StringIO()
    return CliChannel(stdin=io.StringIO(answer), stdout=stdout), stdout


def test_confirm_accepts_y() -> None:
    cli, _ = channel("y\n")

    assert cli.confirm(ACTION) is True


def test_confirm_accepts_yes_in_any_case() -> None:
    cli, _ = channel("  YES \n")

    assert cli.confirm(ACTION) is True


def test_confirm_treats_empty_answer_as_no() -> None:
    cli, _ = channel("\n")

    assert cli.confirm(ACTION) is False


def test_confirm_treats_n_as_no() -> None:
    cli, _ = channel("n\n")

    assert cli.confirm(ACTION) is False


def test_confirm_treats_garbage_as_no() -> None:
    cli, _ = channel("может быть\n")

    assert cli.confirm(ACTION) is False


def test_confirm_treats_closed_stdin_as_no() -> None:
    cli, _ = channel("")

    assert cli.confirm(ACTION) is False


def test_confirm_prints_restart_command_reason_and_risk() -> None:
    cli, stdout = channel("y\n")

    cli.confirm(ACTION)

    printed = stdout.getvalue()
    assert "docker restart postgres" in printed
    assert ACTION.reason in printed
    assert ACTION.risk in printed


def test_emit_writes_a_line_to_stdout() -> None:
    cli, stdout = channel("")

    cli.emit("готово")

    assert stdout.getvalue() == "готово\n"
