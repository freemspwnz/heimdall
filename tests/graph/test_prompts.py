from heimdall.infrastructure.graph.prompts import DIAGNOSE_SYSTEM, PROPOSE_SYSTEM


def test_report_prompts_ask_for_status() -> None:
    for prompt in (DIAGNOSE_SYSTEM, PROPOSE_SYSTEM):
        assert "состояние сервиса или хоста" in prompt
        assert "одно-три предложения" in prompt
        assert "должен сделать человек" not in prompt
    assert "только внутри action" in PROPOSE_SYSTEM
