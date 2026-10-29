from pathlib import Path


def load_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")
