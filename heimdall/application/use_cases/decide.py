from typing import Literal

from ..protocols import Graph


async def decide(
    run_id: str,
    accepted: bool,
    graph: Graph,
) -> Literal["unknown", "not_waiting", "ok"]:

    return await graph.decide(run_id, accepted)
