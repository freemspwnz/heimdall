from heimdall.rag import chunk_markdown


def test_chunk_markdown_splits_on_h2_headings() -> None:
    text = "# Hosts\n\noverview\n\n## Postgres\n\npg body\n\n## Jellyfin\n\njf body\n"
    chunks = chunk_markdown(text, "inventory.md")
    assert len(chunks) >= 2
    assert all(c.source == "inventory.md" for c in chunks)
    assert all(c.text.startswith("inventory.md\n") for c in chunks)
    texts = [c.text for c in chunks]
    assert any("## Postgres" in t and "pg body" in t for t in texts)
    assert any("## Jellyfin" in t and "jf body" in t for t in texts)
    assert not any("## Postgres" in t and "## Jellyfin" in t for t in texts)


def test_chunk_markdown_splits_on_h3_headings() -> None:
    text = (
        "## Postgres\n\npg intro\n\n"
        "### Symptoms\n\nbad connections\n\n"
        "### Restart\n\nrestart after logs\n"
    )
    chunks = chunk_markdown(text, "postgres.md")
    texts = [c.text for c in chunks]
    assert any("### Symptoms" in t and "bad connections" in t for t in texts)
    assert any("### Restart" in t and "restart after logs" in t for t in texts)
    assert not any("### Symptoms" in t and "### Restart" in t for t in texts)


def test_chunk_markdown_splits_long_section_on_paragraphs() -> None:
    para1 = "postgres " + ("aaa " * 220)
    para2 = "exporter " + ("bbb " * 220)
    text = f"## Database\n\n{para1}\n\n{para2}\n"
    assert len(text) > 800
    chunks = chunk_markdown(text, "postgres.md")
    assert len(chunks) >= 2
    assert all(c.source == "postgres.md" for c in chunks)
    assert all(c.text.startswith("postgres.md\n") for c in chunks)
    assert not any(para1.strip() in c.text and para2.strip() in c.text for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    assert "postgres" in joined
    assert "exporter" in joined
