from __future__ import annotations

from proofloop_core.contracts.prompt_contract import compile_prompt_contract
from proofloop_core.contracts.request_envelope import create
from proofloop_core.engine.intent import compile_intent


def _request() -> str:
    return """proofloop_core/engine/repair.py의 반복 실패 처리를 수정해줘.

1. 동일 실패에는 같은 역할을 다시 호출하지 않는다.
2. public API는 변경하지 않는다.
3. 새 외부 의존성을 추가하지 않는다.
4. 관련 테스트를 실행한다.
5. 테스트하지 않은 내용을 성공했다고 말하지 않는다.
"""


def test_multiline_request_retains_requirements_and_source_refs() -> None:
    intent = compile_intent(_request())
    value = intent.to_dict()

    statements = [item["statement"] for item in value["acceptanceCriteria"]]
    assert any("동일 실패" in item for item in statements)
    assert any("테스트" in item for item in statements)
    assert any("성공" in item for item in statements)
    assert any("public API" in item for item in value["constraints"])
    assert any("외부 의존성" in item for item in value["constraints"])
    assert value["sourceRefs"]["/objective"]
    assert all(
        value["sourceRefs"][f"/acceptanceCriteria/{index}"]
        for index in range(len(value["acceptanceCriteria"]))
    )


def test_all_tiers_compile_an_active_source_linked_brief() -> None:
    request = _request()
    envelope = create(
        request_id="run-1",
        raw_text=request,
        repo_root="/repo",
        invocation_source="test",
        host_requested="codex",
    ).to_dict()
    intent = compile_intent(request).to_dict()
    strategy = {"strategy": "PLANNED_IMPLEMENTATION", "tier": "T1"}
    context = {"schemaVersion": "1.0", "repoRoot": "/repo", "detectedCommands": {}}

    for tier in ("T0", "T1", "T2", "T3"):
        active, compilation = compile_prompt_contract(
            request_envelope=envelope,
            intent_contract=intent,
            strategy={**strategy, "tier": tier},
            repository_context=context,
            repository_baseline="abc123",
            authority="repository_mutation",
            tier=tier,
        )
        assert active["kind"] == "EXECUTION_BRIEF"
        assert active["provenance"]["originalRequestSha256"] == intent["originalRequestHash"]
        assert "intent.mutate.v1" in compilation["selectedTemplateIds"]
        assert "surface.repository.v1" in compilation["selectedTemplateIds"]
        assert ("risk.t2" in compilation["selectedTemplateIds"]) is (tier in {"T2", "T3"})
        assert len(compilation["templateSetSha256"]) == 64
        assert len(compilation["executionBriefSha256"]) == 64
