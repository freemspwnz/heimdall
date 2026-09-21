from heimdall.models import Chunk

_MAX_SECTION_CHARS = 800


def chunk_markdown(text: str, source: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in _split_h2_sections(text):
        parts = (
            _split_paragraphs(section)
            if len(section) > _MAX_SECTION_CHARS
            else [section]
        )
        for part in parts:
            body = part.strip()
            if not body:
                continue
            chunks.append(Chunk(text=f"{source}\n{body}", source=source))
    return chunks


def _split_h2_sections(text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("## ") and current:
            sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("".join(current))
    return sections


def _split_paragraphs(section: str) -> list[str]:
    return [part for part in section.split("\n\n") if part.strip()]
