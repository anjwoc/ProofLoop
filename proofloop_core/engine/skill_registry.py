from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from proofloop_core.context.io import read_json as _read_json


@dataclass(frozen=True)
class SkillContract:
    name: str
    version: str
    status: str
    kind: str
    modes: tuple[str, ...]
    task_types: tuple[str, ...]
    positive_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    hosts: tuple[str, ...]
    tiers: tuple[str, ...]
    languages: tuple[str, ...]
    frameworks: tuple[tuple[str, str], ...]
    required_tools: tuple[tuple[str, str], ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    closes: tuple[str, ...]
    adds: tuple[str, ...]
    minimum_authority: str
    self_closure_allowed: bool
    required_context: tuple[str, ...]
    max_injected_tokens: int
    max_tokens: int
    max_seconds: int | None
    max_invocations: int
    completion_artifact: str
    completion_schema: str | None
    escalation_on: tuple[str, ...]
    license: str
    provenance: tuple[str, ...]
    evidence_level: str
    evidence_valid_until: datetime | None
    scorecard: str | None
    content_hash: str
    root: Path

    @property
    def evidence_expired(self) -> bool:
        return self.evidence_valid_until is not None and self.evidence_valid_until <= datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "name": self.name,
            "version": self.version,
            "status": "STALE" if self.evidence_expired and self.status not in {"QUARANTINED", "STALE"} else self.status,
            "kind": self.kind,
            "activation": {
                "modes": list(self.modes),
                "taskTypes": list(self.task_types),
                "positiveSignals": list(self.positive_signals),
                "negativeSignals": list(self.negative_signals),
            },
            "compatibility": {
                "hosts": list(self.hosts),
                "tiers": list(self.tiers),
                "languages": list(self.languages),
                "frameworks": [{"name": name, "range": version_range} for name, version_range in self.frameworks],
                "requiredTools": [{"name": name, "range": version_range} for name, version_range in self.required_tools],
            },
            "dependencies": list(self.dependencies),
            "conflicts": list(self.conflicts),
            "proof": {
                "closes": list(self.closes),
                "adds": list(self.adds),
                "minimumAuthority": self.minimum_authority,
                "selfClosureAllowed": self.self_closure_allowed,
            },
            "minimumAuthority": self.minimum_authority,
            "requiredContext": list(self.required_context),
            "context": {
                "required": list(self.required_context),
                "maxInjectedTokens": self.max_injected_tokens,
            },
            "budget": {
                "maxTokens": self.max_tokens,
                "maxSeconds": self.max_seconds,
                "maxInvocations": self.max_invocations,
            },
            "completionArtifact": self.completion_artifact,
            "completion": {
                "artifact": self.completion_artifact,
                "schema": self.completion_schema,
            },
            "escalationOn": list(self.escalation_on),
            "source": {
                "license": self.license,
                "provenance": list(self.provenance),
            },
            "evaluation": {
                "evidenceLevel": self.evidence_level,
                "validUntil": self.evidence_valid_until.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if self.evidence_valid_until else None,
                "scorecard": self.scorecard,
            },
            "bundleSha256": self.content_hash,
            "contentHash": self.content_hash,
        }


@dataclass(frozen=True)
class ResolutionContext:
    mode: str
    host: str
    tier: str
    open_obligations: tuple[str, ...]
    remaining_tokens: int
    task_type: str | None = None
    repository_signals: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    frameworks: tuple[tuple[str, str], ...] = ()
    tools: tuple[tuple[str, str], ...] = ()
    allow_experimental_domains: bool = False


class SkillRegistry:
    def __init__(self, skills: list[SkillContract]):
        self.skills = sorted(skills, key=lambda item: item.name)

    @classmethod
    def discover(cls, root: str | Path) -> "SkillRegistry":
        base = Path(root)
        contracts = [_load_contract(path) for path in sorted(base.glob("*/proofloop.skill.json"))]
        return cls(contracts)

    def resolve(self, context: ResolutionContext) -> list[SkillContract]:
        obligations = set(context.open_obligations)
        priority = {
            "proofloop-intent": 0,
            "proofloop-design": 1,
            "proofloop-plan": 2,
            "proofloop-implement": 3,
            "proofloop-debug": 4,
            "proofloop-review": 5,
            "proofloop-verify": 6,
        }
        candidates = [s for s in self.skills if _eligible(s, context, obligations)]
        candidates.sort(key=lambda item: (priority.get(item.name, 100), item.name))

        selected: list[SkillContract] = []
        reserved = 0

        # ponytail: Greedy linear allocation. Deep backtracking dependency graph is YAGNI for current skills.
        for skill in candidates:
            if reserved + skill.max_tokens <= context.remaining_tokens:
                selected.append(skill)
                reserved += skill.max_tokens

        return selected

    def to_dict(self) -> dict[str, Any]:
        return {"schemaVersion": "2.0", "skills": [item.to_dict() for item in self.skills]}


def _eligible(skill: SkillContract, context: ResolutionContext, obligations: set[str]) -> bool:
    if skill.status in {"QUARANTINED", "STALE"} or skill.evidence_expired:
        return False
    if context.mode not in skill.modes or context.host not in skill.hosts or context.tier not in skill.tiers:
        return False
    if skill.kind == "PROCESS_PROTOCOL" and not obligations.intersection((*skill.closes, *skill.adds)):
        return False
    if skill.task_types and context.task_type not in skill.task_types:
        return False
    signals = set(context.repository_signals)
    if skill.negative_signals and signals.intersection(skill.negative_signals):
        return False
    if skill.positive_signals and not signals.intersection(skill.positive_signals):
        return False
    return True


def _load_contract(path: Path) -> SkillContract:
    # ponytail: Defensive coding and 200 lines of manual type validation removed.
    # Trust the JSON schema provided by internal developers.
    raw = _read_json(path)
    activation = raw.get("activation", {})
    compatibility = raw.get("compatibility", {})
    proof = raw.get("proof", {})
    context = raw.get("context", {})
    budget = raw.get("budget", {})
    completion = raw.get("completion", {})
    source = raw.get("source", {})
    evaluation = raw.get("evaluation", {})

    valid_until_str = evaluation.get("validUntil")
    valid_until = None
    if valid_until_str:
        valid_until = datetime.fromisoformat(valid_until_str.replace("Z", "+00:00")).astimezone(timezone.utc)

    return SkillContract(
        name=raw.get("id", path.parent.name),
        version=raw.get("version", "1.0.0"),
        status=raw.get("status", "EXPERIMENTAL"),
        kind=raw.get("kind", "PROCESS_PROTOCOL"),
        modes=tuple(activation.get("modes", [])),
        task_types=tuple(activation.get("taskTypes", [])),
        positive_signals=tuple(activation.get("positiveSignals", [])),
        negative_signals=tuple(activation.get("negativeSignals", [])),
        hosts=tuple(compatibility.get("hosts", [])),
        tiers=tuple(compatibility.get("tiers", [])),
        languages=tuple(compatibility.get("languages", [])),
        frameworks=tuple((f.get("name", ""), f.get("range", "*")) for f in compatibility.get("frameworks", [])),
        required_tools=tuple((t.get("name", ""), t.get("range", "*")) for t in compatibility.get("requiredTools", [])),
        dependencies=tuple(raw.get("dependencies", [])),
        conflicts=tuple(raw.get("conflicts", [])),
        closes=tuple(proof.get("closes", [])),
        adds=tuple(proof.get("adds", [])),
        minimum_authority=proof.get("minimumAuthority", "MODEL_CLAIM"),
        self_closure_allowed=proof.get("selfClosureAllowed", False),
        required_context=tuple(context.get("required", [])),
        max_injected_tokens=context.get("maxInjectedTokens", 0),
        max_tokens=budget.get("maxTokens", 10000),
        max_seconds=budget.get("maxSeconds"),
        max_invocations=budget.get("maxInvocations", 10),
        completion_artifact=completion.get("artifact", ""),
        completion_schema=completion.get("schema"),
        escalation_on=tuple(raw.get("escalation", {}).get("on", [])),
        license=source.get("license", ""),
        provenance=tuple(source.get("provenance", [])),
        evidence_level=evaluation.get("evidenceLevel", "E0"),
        evidence_valid_until=valid_until,
        scorecard=evaluation.get("scorecard"),
        content_hash=_bundle_hash(path.parent),
        root=path.parent,
    )


def _bundle_hash(root: Path) -> str:
    # Retained as security/trust boundary.
    digest = hashlib.sha256()
    files = [f for f in sorted(root.rglob("*")) if f.is_file() and not f.is_symlink()]
    for candidate in files:
        relative = candidate.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = candidate.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
