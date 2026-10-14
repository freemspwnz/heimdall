from heimdall.application.models import ToolSpec

LOKI_QUERY = "loki_query"
VM_QUERY = "vm_query"
DOCKER_PS = "docker_ps"
DOCKER_INSPECT = "docker_inspect"
DOCKER_LOGS = "docker_logs"

READ_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name=LOKI_QUERY,
        description="Прочитать логи из Loki по запросу LogQL.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "LogQL-запрос"},
                "since": {"type": "string", "description": "окно, например 15m"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=VM_QUERY,
        description="Прочитать метрики из VictoriaMetrics по запросу MetricsQL.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "MetricsQL-запрос"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name=DOCKER_PS,
        description="Список контейнеров и их состояние.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolSpec(
        name=DOCKER_INSPECT,
        description="Подробное состояние одного контейнера.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "имя контейнера"},
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name=DOCKER_LOGS,
        description="Хвост логов одного контейнера.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "имя контейнера"},
                "tail": {"type": "integer", "description": "сколько строк"},
            },
            "required": ["name"],
        },
    ),
]
