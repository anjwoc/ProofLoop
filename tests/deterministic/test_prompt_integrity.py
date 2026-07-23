from __future__ import annotations

from proofloop_core.prompting.prompt_ir import PromptIR, PromptMetadata
from proofloop_core.prompting.renderers import render_prompt


def _prompt(role: str) -> PromptIR:
    return PromptIR(
        prompt_id="prompt-1",
        request_id="request-1",
        contract_id="contract-1",
        blueprint_id="blueprint-1",
        role=role,
        goal="Make the smallest correct change.",
        stop_when="",
        deliverables=(),
        evidence_requirements=(),
        allowed_scope=(),
        protected_scope=(),
        must_do=("Follow the active task contract.",),
        must_not=("Do not claim verification.",),
        context_refs=("repository context",),
        allowed_tools=(),
        output_contract="Return the role result.",
        escalate_when=(),
        metadata=PromptMetadata(compiler_version="test", generation_time="test"),
    )


def test_truth_contract_precedes_every_role_and_provider_directive() -> None:
    roles = (
        "classifier_fast",
        "explorer_fast",
        "planner_deep",
        "implementer_fast",
        "implementer_recovery",
        "reviewer_deep",
    )
    providers = ("generic", "codex", "claude-code", "agy")

    for role in roles:
        for provider in providers:
            rendered = render_prompt(_prompt(role), provider)
            assert rendered.startswith("ProofLoop mandatory truth and minimality contract")
            assert "TEST, MOCK, FAKE, SIMULATED" in rendered
            assert "Never fabricate a host, model identity, command result" in rendered
            assert "Never convert absence into PASS" in rendered
            assert "first sufficient Ponytail rung" in rendered
            assert "The parent Core alone owns authoritative execution" in rendered
            assert rendered.index("ProofLoop mandatory truth") < rendered.index(f"Role: {role}")


def test_role_instructions_cannot_erase_the_mandatory_contract() -> None:
    ir = _prompt("implementer_fast")
    rendered = render_prompt(ir, "codex")

    assert "ProofLoop Codex contract" in rendered
    assert "Follow the active task contract." in rendered
    assert "Do not claim verification." in rendered
    assert rendered.count("ProofLoop mandatory truth and minimality contract") == 1
