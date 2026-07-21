from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class PromptMetadata:
    compiler_version: str
    generation_time: str


@dataclass(frozen=True)
class PromptIR:
    prompt_id: str
    request_id: str
    contract_id: str
    blueprint_id: str

    role: str
    goal: str
    stop_when: str

    deliverables: tuple[str, ...]
    evidence_requirements: tuple[str, ...]

    allowed_scope: tuple[str, ...]
    protected_scope: tuple[str, ...]

    must_do: tuple[str, ...]
    must_not: tuple[str, ...]

    context_refs: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    output_contract: str
    escalate_when: tuple[str, ...]

    metadata: PromptMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "request_id": self.request_id,
            "contract_id": self.contract_id,
            "blueprint_id": self.blueprint_id,
            "role": self.role,
            "goal": self.goal,
            "stop_when": self.stop_when,
            "deliverables": list(self.deliverables),
            "evidence_requirements": list(self.evidence_requirements),
            "allowed_scope": list(self.allowed_scope),
            "protected_scope": list(self.protected_scope),
            "must_do": list(self.must_do),
            "must_not": list(self.must_not),
            "context_refs": list(self.context_refs),
            "allowed_tools": list(self.allowed_tools),
            "output_contract": self.output_contract,
            "escalate_when": list(self.escalate_when),
            "metadata": {
                "compiler_version": self.metadata.compiler_version,
                "generation_time": self.metadata.generation_time,
            }
        }
