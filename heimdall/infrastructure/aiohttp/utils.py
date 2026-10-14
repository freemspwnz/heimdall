def truncate_payload(text: str, max_lines: int = 100, max_chars: int = 4000) -> str:
    lines = text.splitlines()
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines])
    if len(text) > max_chars:
        text = text[:max_chars]
    return text
