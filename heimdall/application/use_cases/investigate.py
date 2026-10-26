from collections.abc import AsyncIterator

from ..models import RunEvent
from ..protocols import Graph


async def investigate(
    question: str,
    graph: Graph,
) -> AsyncIterator[RunEvent]:
    async for event in graph.start(question):
        yield event
