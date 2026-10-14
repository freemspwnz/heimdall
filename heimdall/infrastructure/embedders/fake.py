KEYWORDS = [
    "postgres",
    "exporter",
    "traefik",
    "whoami",
    "3x-ui",
    "tunnel",
    "loki",
    "jellyfin",
    "restart",
]


class FakeEmbedder:
    async def embed(
        self,
        texts: list[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        del query
        out: list[list[float]] = []
        for text in texts:
            t = text.lower()
            out.append([float(t.count(k)) for k in KEYWORDS])
        return out
