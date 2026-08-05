from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, Any
from proofloop_core.context.io import write_json
from proofloop_core.engine.skill_registry import SkillRegistry, SkillContract, ResolutionContext
from proofloop_core.engine.domain_runtime import select_reference_slices

if TYPE_CHECKING:
    from proofloop_core.engine.orchestrator import ProofLoopOrchestrator

def resolve_skills(orchestrator: "ProofLoopOrchestrator") -> None:
    assert orchestrator.run_dir is not None and orchestrator.strategy is not None and orchestrator.proof_graph is not None
    protocols_root = Path(__file__).resolve().parents[1] / "proofloop_protocols"
    domain_root = Path(__file__).resolve().parents[1] / "proofloop_domain_packs"
    protocol_registry = SkillRegistry.discover(protocols_root) if protocols_root.exists() else SkillRegistry([])
    domain_registry = SkillRegistry.discover(domain_root) if domain_root.exists() else SkillRegistry([])
    registry = SkillRegistry([*protocol_registry.skills, *domain_registry.skills])
    write_json(orchestrator.run_dir / "skill-registry.json", registry.to_dict())
    token_budgets = {"T0": 20_000, "T1": 60_000, "T2": 180_000, "T3": 360_000}
    budget = token_budgets[orchestrator.strategy.tier]
    strategy = orchestrator.strategy
    proof_graph = orchestrator.proof_graph
    orchestrator.token_budget = budget
    resolution_mode = "goal" if orchestrator.goal_mode or orchestrator.mode == "orchestrate" else orchestrator.mode
    fingerprint = orchestrator.repository_fingerprint or {
        "taskTypes": [], "signals": [], "languages": [], "frameworks": {}, "tools": {}
    }
    raw_frameworks = fingerprint.get("frameworks")
    frameworks = raw_frameworks if isinstance(raw_frameworks, dict) else {}
    raw_tools = fingerprint.get("tools")
    tools = raw_tools if isinstance(raw_tools, dict) else {}
    def resolution_context(remaining_tokens: int, task_type: str | None = None) -> ResolutionContext:
        return ResolutionContext(
            mode=resolution_mode,
            host=orchestrator.host,
            tier=strategy.tier,
            open_obligations=tuple(item.obligation_id for item in proof_graph.obligations),
            remaining_tokens=remaining_tokens,
            task_type=task_type,
            repository_signals=tuple(str(item) for item in fingerprint.get("signals", [])),
            languages=tuple(str(item) for item in fingerprint.get("languages", [])),
            frameworks=tuple((str(name), str(version)) for name, version in frameworks.items()),
            tools=tuple((str(name), str(version)) for name, version in tools.items()),
            allow_experimental_domains=orchestrator.experimental_domain_packs,
        )
    selected_protocols = protocol_registry.resolve(resolution_context(budget)) if orchestrator.skills_enabled else []
    selected_domains: list[SkillContract] = []
    selected_domain_names: set[str] = set()
    reserved = sum(item.max_tokens for item in selected_protocols)
    if orchestrator.skills_enabled:
        for task_type in list(fingerprint.get("taskTypes", []))[:3]:
            candidates = domain_registry.resolve(
                resolution_context(max(0, budget - reserved), str(task_type))
            )
            for candidate in candidates:
                if candidate.name in selected_domain_names:
                    continue
                if reserved + candidate.max_tokens > budget:
                    continue
                selected_domains.append(candidate)
                selected_domain_names.add(candidate.name)
                reserved += candidate.max_tokens
    selected = [*selected_protocols, *selected_domains]
    orchestrator.selected_skills = selected
    orchestrator.selected_skill_references = {}
    task_types = {str(item) for item in fingerprint.get("taskTypes", [])}
    skipped_domains = [
        {
            "skill": skill.name,
            "status": skill.status,
            "reasonCode": "EXPERIMENTAL_REQUIRES_OPT_IN",
        }
        for skill in domain_registry.skills
        if skill.name not in selected_domain_names
        and skill.status == "EXPERIMENTAL"
        and bool(task_types.intersection(skill.task_types))
        and not orchestrator.experimental_domain_packs
    ]
    domain_selections: list[dict[str, Any]] = []
    for skill in selected_domains:
        reference_selection = select_reference_slices(
            skill.root,
            fingerprint,
            max_tokens=skill.max_injected_tokens,
        )
        orchestrator.selected_skill_references[skill.name] = list(reference_selection["slices"])
        domain_selections.append(
            {
                "skill": skill.name,
                "status": skill.status,
                "adapters": reference_selection["adapters"],
                "slices": reference_selection["slices"],
                "estimatedTokens": reference_selection["estimatedTokens"],
                "proposedObligations": list(skill.adds),
                "gatingObligationsActivated": skill.status in {"VERIFIED", "DEFAULT"},
            }
        )
    write_json(
        orchestrator.run_dir / "domain-selection.json",
        {
            "schemaVersion": "1.0",
            "fingerprint": str(orchestrator.run_dir / "repository-fingerprint.json"),
            "selected": domain_selections,
            "skipped": skipped_domains,
            "policy": {"primary": 1, "maxAdjunct": 2, "technologyAdaptersAreConditional": True},
        },
    )
    write_json(
        orchestrator.run_dir / "skill-resolution.json",
        {
            "schemaVersion": "1.0",
            "mode": resolution_mode,
            "tier": orchestrator.strategy.tier,
            "tokenBudget": budget,
            "skillsEnabled": orchestrator.skills_enabled,
            "selected": [item.to_dict() for item in selected],
            "processProtocols": [item.name for item in selected_protocols],
            "domainPacks": [item.name for item in selected_domains],
            "experimentalDomainPacks": orchestrator.experimental_domain_packs,
        },
    )
    orchestrator._emit(
        "budget.updated",
        phase="CLASSIFY",
        message=f"Hard run token budget set for {orchestrator.strategy.tier}.",
        data={"tier": orchestrator.strategy.tier, "maxTokens": budget},
    )
    if not selected:
        orchestrator._emit(
            "skill.skipped",
            phase="CLASSIFY",
            message=(
                "Skill selection is disabled for this ablation run."
                if not orchestrator.skills_enabled
                else "No installed skill contract matched the current proof gaps and budget."
            ),
            data={"tier": orchestrator.strategy.tier, "skillsEnabled": orchestrator.skills_enabled, "openObligations": [item.obligation_id for item in orchestrator.proof_graph.obligations]},
        )
    for skill in selected:
        selection_description = (
            "selected as a repository-compatible domain workflow"
            if skill.kind == "DOMAIN_PACK"
            else "selected to close an open proof gap"
        )
        orchestrator._emit(
            "skill.selected",
            phase="CLASSIFY",
            message=f"Skill {skill.name} {selection_description}.",
            data={
                "skill": skill.name,
                "kind": skill.kind,
                "version": skill.version,
                "contentHash": skill.content_hash,
                "closes": list(skill.closes),
                "proposedObligations": list(skill.adds),
            },
        )
        orchestrator._emit(
            "skill.reference_loaded",
            phase="CLASSIFY",
            message=f"Skill contract and instructions loaded for {skill.name}.",
            data={
                "skill": skill.name,
                "skillPath": str(skill.root / "SKILL.md"),
                "contractPath": str(skill.root / "proofloop.skill.json"),
                "references": orchestrator.selected_skill_references.get(skill.name, []),
            },
        )
    for skipped in skipped_domains:
        orchestrator._emit(
            "skill.skipped",
            phase="CLASSIFY",
            message=f"Experimental domain pack {skipped['skill']} was not auto-selected.",
            data=skipped,
        )
