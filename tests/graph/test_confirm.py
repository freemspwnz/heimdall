import pytest
from heimdall.infrastructure.graph.nodes.confirm import _decision


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("y", "yes"),
        ("yes", "yes"),
        ("YES", "yes"),
        (" y ", "yes"),
        ("да", "no"),
        ("д", "no"),
        ("n", "no"),
        ("", "no"),
        (None, "no"),
    ],
)
def test_confirmation_accepts_only_latin_yes(answer: object, expected: str) -> None:
    assert _decision(answer) == expected
