from pathlib import Path
from typing import Protocol


class Loader(Protocol):
    def __call__(self, path: Path) -> str: ...
