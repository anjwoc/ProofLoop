from __future__ import annotations

import pytest

from proofloop_core.prompting.algebra import (
    AuthorityLevel,
    PromptTemplateConflict,
    TemplatePolicy,
    compile_ir,
    merge_templates,
)


def test_allowed_scope_is_intersected_and_authority_is_restricted() -> None:
    left = TemplatePolicy(
        id="left",
        authority_ceiling=AuthorityLevel.REPOSITORY_MUTATION,
        allowed_scope=frozenset({"src/**", "tests/**"}),
    )
    right = TemplatePolicy(
        id="right",
        authority_ceiling=AuthorityLevel.READ_ONLY,
        allowed_scope=frozenset({"tests/**", "docs/**"}),
    )

    merged = merge_templates([left, right])

    assert merged.allowed_scope == frozenset({"tests/**"})
    assert merged.authority_ceiling == AuthorityLevel.READ_ONLY


def test_disjoint_declared_scopes_fail_closed() -> None:
    with pytest.raises(PromptTemplateConflict, match="PROMPT_SCOPE_WIDENING_REJECTED"):
        merge_templates([
            TemplatePolicy(id="a", allowed_scope=frozenset({"src/**"})),
            TemplatePolicy(id="b", allowed_scope=frozenset({"tests/**"})),
        ])


def test_contradictory_rules_fail_closed() -> None:
    with pytest.raises(PromptTemplateConflict, match="PROMPT_TEMPLATE_CONFLICT"):
        merge_templates([
            TemplatePolicy(id="a", must_do=frozenset({"Modify protected paths."})),
            TemplatePolicy(id="b", must_not=frozenset({"Modify protected paths."})),
        ])


def test_prompt_identity_is_content_addressed_not_time_based() -> None:
    template = TemplatePolicy(id="stable")
    first = compile_ir("run-1", "planner_deep", "goal", [template])
    second = compile_ir("run-1", "planner_deep", "goal", [template])

    assert first.prompt_id == second.prompt_id
    assert first.contract_id == second.contract_id
    assert first.metadata.generation_time == "content-addressed"
    assert first.metadata.content_sha256 == second.metadata.content_sha256
    assert "todo" not in first.prompt_id.lower()
