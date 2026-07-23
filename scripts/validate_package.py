#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proofloop_core.engine.skill_registry import SkillRegistry
from proofloop_core.context.io import read_json
errors: list[str] = []


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append(f"{path.relative_to(ROOT)}: missing leading frontmatter")
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        errors.append(f"{path.relative_to(ROOT)}: unclosed frontmatter")
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


for path in sorted((ROOT / "skills").glob("*/SKILL.md")) + sorted((ROOT / "proofloop_domain_packs").glob("*/SKILL.md")):
    meta = frontmatter(path)
    for field in ("name", "description"):
        if not meta.get(field):
            errors.append(f"{path.relative_to(ROOT)}: missing {field}")

expected_models = {
    "planner-deep.md": "opus",
    "implementer-fast.md": "haiku",
    "implementer-recovery.md": "sonnet",
    "reviewer-deep.md": "opus",
}
for name, model in expected_models.items():
    path = ROOT / "agents" / name
    meta = frontmatter(path)
    if meta.get("model") != model:
        errors.append(f"agents/{name}: expected model {model}, got {meta.get('model')}")

for path in (ROOT / "plugin" / "plugin.json", ROOT / "plugin" / "marketplace.json"):
    try:
        value = read_json(path)
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
        continue
    if not value.get("description"):
        errors.append(f"{path.relative_to(ROOT)}: description required")

source_files = [p for p in ROOT.rglob("*") if p.is_file() and "dist" not in p.parts and "__pycache__" not in p.parts]
runtime_roots = {"proofloop_core", "scripts", "skills", "proofloop_protocols", "proofloop_domain_packs", "agents", "hooks", "plugin"}
runtime_files = [p for p in source_files if p.relative_to(ROOT).parts[0] in runtime_roots]
# The repository baseline already contains 183 runtime files. Static-web proof
# and verified worktree promotion add two bounded Core modules.
runtime_file_budget = 185
if len(runtime_files) > runtime_file_budget:
    errors.append(f"runtime source file budget exceeded: {len(runtime_files)} > {runtime_file_budget}")

def exists_in_core(name: str) -> bool:
    if (ROOT / "proofloop_core" / name).exists():
        return True
    return any(p.name == name for p in (ROOT / "proofloop_core").rglob("*.py"))


required_fragments = {
    ROOT / "skills" / "proofloop" / "SKILL.md": [
        "proofloop-core run",
        "--mode <adaptive-or-goal-or-audit>",
        "Do not synthesize",
        "--output-format human",
        "--verbosity info",
        "--color never",
        "truth-report.json",
    ],
    ROOT / "proofloop_protocols" / "proofloop-design" / "SKILL.md": ["Core principle", "Decision procedure", "Stop and escalate", "Completion checklist"],
    ROOT / "proofloop_protocols" / "proofloop-debug" / "SKILL.md": ["red loop", "fingerprint", "falsifiable hypothesis"],
    ROOT / "proofloop_protocols" / "proofloop-verify" / "SKILL.md": ["Evidence authority", "Freshness rules", "UNVERIFIABLE"],
    ROOT / "proofloop_domain_packs" / "backend-development" / "SKILL.md": ["public contract", "Stop and escalate", "Django"],
    ROOT / "proofloop_domain_packs" / "frontend-development" / "SKILL.md": ["accessibility", "user-observable states"],
    ROOT / "proofloop_domain_packs" / "devops-delivery" / "SKILL.md": ["rollback", "Never \"test\" by deploying"],
    ROOT / "proofloop_domain_packs" / "test-engineering" / "SKILL.md": ["red case", "nondeterminism"],
    ROOT / "proofloop_domain_packs" / "code-review" / "SKILL.md": ["real diff", "Finding contract"],
    ROOT / "agents" / "reviewer-deep.md": ["OVERBUILT", "deletionCandidates"],
}
for path, fragments in required_fragments.items():
    text = path.read_text(encoding="utf-8")
    for fragment in fragments:
        if fragment not in text:
            errors.append(f"{path.relative_to(ROOT)}: missing required fragment {fragment!r}")

if not exists_in_core("assurance.py"):
    errors.append("proofloop_core/assurance.py: missing assurance layer")

try:
    sample = read_json(ROOT / "examples" / "task-briefs" / "python-example.json")
    if not sample.get("changeBudget"):
        errors.append("examples/task-briefs/python-example.json: changeBudget required")
    if not (sample.get("simplicity") or {}).get("selectedRung"):
        errors.append("examples/task-briefs/python-example.json: simplicity.selectedRung required")
except Exception as exc:
    errors.append(f"examples/task-briefs/python-example.json: invalid JSON: {exc}")

manual_pass_pattern = re.compile(r"verify\s+--status|--status\s+pass", re.I)
for path in list((ROOT / "skills").rglob("*.md")) + list((ROOT / "proofloop_protocols").rglob("*.md")) + list((ROOT / "proofloop_domain_packs").rglob("*.md")) + list((ROOT / "proofloop_core").rglob("*.py")):
    if manual_pass_pattern.search(path.read_text(encoding="utf-8")):
        errors.append(f"{path.relative_to(ROOT)}: manual PASS interface is forbidden")


required_host_files = [
    "hosts.py",
    "host_runner.py",
]
for name in required_host_files:
    if not exists_in_core(name):
        errors.append(f"proofloop_core/{name}: required host adapter file missing")
for path in [ROOT / "scripts" / "build_host_adapter.py", ROOT / "scripts" / "host_trace_hook.py", ROOT / "scripts" / "truth_stop_hook.py", ROOT / "scripts" / "run_host_live.py"]:
    if not path.exists():
        errors.append(f"{path.relative_to(ROOT)}: required host adapter file missing")

for path in list((ROOT / "skills").rglob("SKILL.md")) + list((ROOT / "proofloop_protocols").rglob("SKILL.md")) + list((ROOT / "proofloop_domain_packs").rglob("SKILL.md")):
    text = path.read_text(encoding="utf-8")
    if "python3 scripts/" in text:
        errors.append(f"{path.relative_to(ROOT)}: installed skill must use proofloop-core sidecar, not repository-relative scripts")

try:
    registry = SkillRegistry.discover(ROOT / "proofloop_protocols")
    required_builtin = {
        "proofloop-intent",
        "proofloop-design",
        "proofloop-plan",
        "proofloop-implement",
        "proofloop-debug",
        "proofloop-review",
        "proofloop-verify",
    }
    observed_builtin = {item.name for item in registry.skills}
    if observed_builtin != required_builtin:
        errors.append(f"proofloop_protocols: built-in protocol contracts mismatch: {sorted(observed_builtin)}")
except Exception as exc:
    errors.append(f"proofloop_protocols: invalid ProofLoop skill contract: {exc}")

try:
    domain_registry = SkillRegistry.discover(ROOT / "proofloop_domain_packs")
    required_domains = {
        "backend-development",
        "frontend-development",
        "devops-delivery",
        "test-engineering",
        "code-review",
    }
    observed_domains = {item.name for item in domain_registry.skills}
    if observed_domains != required_domains:
        errors.append(f"proofloop_domain_packs: built-in domain contracts mismatch: {sorted(observed_domains)}")
    if any(item.kind != "DOMAIN_PACK" for item in domain_registry.skills):
        errors.append("proofloop_domain_packs: every built-in must be kind DOMAIN_PACK")
    for skill in domain_registry.skills:
        triggers_path = skill.root / "evals" / "triggers.json"
        behavior_path = skill.root / "evals" / "behavior.json"
        try:
            triggers = read_json(triggers_path)
            behavior = read_json(behavior_path)
        except Exception as exc:
            errors.append(f"{skill.name}: invalid or missing eval fixture: {exc}")
            continue
        if triggers.get("schemaVersion") != "1.0" or len(triggers.get("positive", [])) < 5 or len(triggers.get("negative", [])) < 5:
            errors.append(f"{skill.name}: trigger eval needs schemaVersion 1.0 and at least 5 positive/negative cases")
        scenarios = behavior.get("scenarios", [])
        if behavior.get("schemaVersion") != "1.0" or len(scenarios) < 3:
            errors.append(f"{skill.name}: behavior eval needs schemaVersion 1.0 and at least 3 scenarios")
except Exception as exc:
    errors.append(f"proofloop_domain_packs: invalid ProofLoop domain contract: {exc}")

entry_text = (ROOT / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
if "invoke-role" in entry_text and "Do not manually call `invoke-role`" not in entry_text:
    errors.append("skills/proofloop/SKILL.md: invoke-role must not be exposed as a user workflow")
for name in ("orchestrator.py", "adapters.py", "strategy.py"):
    if not exists_in_core(name):
        errors.append(f"proofloop_core/{name}: automatic orchestrator component missing")

if errors:
    print("PACKAGE VALIDATION: FAIL", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)
print(f"PACKAGE VALIDATION: PASS ({len(runtime_files)} runtime files, {len(source_files)} total files)")
