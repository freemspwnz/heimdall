from heimdall.truncate import truncate_payload


def test_truncate_payload_caps_lines() -> None:
    text = "\n".join(f"line-{i}" for i in range(200))
    out = truncate_payload(text, max_lines=100, max_chars=4000)
    assert out.count("\n") + 1 == 100
    assert out.startswith("line-0")


def test_truncate_payload_caps_chars() -> None:
    text = "x" * 8000
    out = truncate_payload(text, max_lines=100, max_chars=4000)
    assert len(out) == 4000
