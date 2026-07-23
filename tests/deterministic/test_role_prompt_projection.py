from __future__ import annotations

from proofloop_core.contracts.prompt_contract import compile_prompt_contract
from proofloop_core.contracts.request_envelope import create
from proofloop_core.contracts.role_view import project_role_view
from proofloop_core.engine.intent import compile_intent


def _active_brief() -> dict:
    request = "proofloop_core/engine/repair.py를 수정하고 테스트해줘."
    envelope = create(
        request_id="run-1",
        raw_text=request,
        repo_root="/repo",
        invocation_source="test",
        host_requested="codex",
    ).to_dict()
    intent = compile_intent(request).to_dict()
    active, _ = compile_prompt_contract(
        request_envelope=envelope,
        intent_contract=intent,
        strategy={"strategy": "PLANNED_IMPLEMENTATION", "tier": "T2"},
        repository_context={"schemaVersion": "1.0", "repoRoot": "/repo"},
        repository_baseline="abc123",
        authority="repository_mutation",
        tier="T2",
    )
    return active


def test_implementer_gets_minimal_scope_and_no_raw_request_block() -> None:
    view = project_role_view(_active_brief(), "implementer_fast", "inv-1")

    assert view["role"] == "implementer_fast"
    assert view["invocationId"] == "inv-1"
    assert "objective" in view
    assert "acceptanceCriteria" in view
    assert "scope" in view
    assert "openQuestions" not in view
    assert "facts" not in view
    assert "originalRequest" not in view
    assert len(view["projectionSha256"]) == 64
    assert view["authorityRefs"]["originalRequest"] == "request-envelope.json"
    assert view["authorityRefs"]["promptCompilation"] == "prompt-compilation.json"


def test_projection_hash_changes_with_invocation_binding() -> None:
    brief = _active_brief()
    first = project_role_view(brief, "planner_deep", "inv-1")
    second = project_role_view(brief, "planner_deep", "inv-2")

    assert first["projectionSha256"] != second["projectionSha256"]
    assert first["provenance"]["executionBriefSha256"] == second["provenance"]["executionBriefSha256"]
