#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
    meta = frontmatter(path)
    for field in ("name", "description"):
        if not meta.get(field):
            errors.append(f"{path.relative_to(ROOT)}: missing {field}")

expected_models = {
    "planner-deep.md": "opus",
    "implementer-fast.md": "haiku",
    "implementer-recovery.md": "sonnet",
    "reviewer-deep.md": "fable",
}
for name, model in expected_models.items():
    path = ROOT / "agents" / name
    meta = frontmatter(path)
    if meta.get("model") != model:
        errors.append(f"agents/{name}: expected model {model}, got {meta.get('model')}")

for path in (ROOT / "plugin" / "plugin.json", ROOT / "plugin" / "marketplace.json"):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
        continue
    if not value.get("description"):
        errors.append(f"{path.relative_to(ROOT)}: description required")

source_files = [p for p in ROOT.rglob("*") if p.is_file() and "dist" not in p.parts and "__pycache__" not in p.parts]
runtime_roots = {"proofloop_core", "scripts", "skills", "agents", "hooks", "plugin"}
runtime_files = [p for p in source_files if p.relative_to(ROOT).parts[0] in runtime_roots]
runtime_file_budget = 80
if len(runtime_files) > runtime_file_budget:
    errors.append(f"runtime source file budget exceeded: {len(runtime_files)} > {runtime_file_budget}")


required_fragments = {
    ROOT / "skills" / "proofloop" / "SKILL.md": [
        "proofloop-core goal",
        "Do not synthesize",
        "--output-format human",
        "--verbosity info",
        "--color auto",
        "truth-report.json",
    ],
    ROOT / "skills" / "using-proofloop" / "SKILL.md": ["Compatibility alias", "proofloop"],
    ROOT / "skills" / "proofloop-planning" / "SKILL.md": ["Minimum-solution ladder", "change budget"],
    ROOT / "skills" / "proofloop-truth-gate" / "SKILL.md": ["FACT", "INFERENCE", "UNKNOWN", "simplicityVerdict"],
    ROOT / "agents" / "reviewer-deep.md": ["OVERBUILT", "deletionCandidates"],
}
for path, fragments in required_fragments.items():
    text = path.read_text(encoding="utf-8")
    for fragment in fragments:
        if fragment not in text:
            errors.append(f"{path.relative_to(ROOT)}: missing required fragment {fragment!r}")

if not (ROOT / "proofloop_core" / "assurance.py").exists():
    errors.append("proofloop_core/assurance.py: missing assurance layer")

try:
    sample = json.loads((ROOT / "examples" / "task-briefs" / "python-example.json").read_text(encoding="utf-8"))
    if not sample.get("changeBudget"):
        errors.append("examples/task-briefs/python-example.json: changeBudget required")
    if not (sample.get("simplicity") or {}).get("selectedRung"):
        errors.append("examples/task-briefs/python-example.json: simplicity.selectedRung required")
except Exception as exc:
    errors.append(f"examples/task-briefs/python-example.json: invalid JSON: {exc}")

manual_pass_pattern = re.compile(r"verify\s+--status|--status\s+pass", re.I)
for path in list((ROOT / "skills").rglob("*.md")) + list((ROOT / "proofloop_core").rglob("*.py")):
    if manual_pass_pattern.search(path.read_text(encoding="utf-8")):
        errors.append(f"{path.relative_to(ROOT)}: manual PASS interface is forbidden")


required_host_files = [
    ROOT / "proofloop_core" / "hosts.py",
    ROOT / "proofloop_core" / "host_runner.py",
    ROOT / "scripts" / "build_host_adapter.py",
    ROOT / "scripts" / "host_trace_hook.py",
    ROOT / "scripts" / "truth_stop_hook.py",
    ROOT / "scripts" / "run_host_live.py",
]
for path in required_host_files:
    if not path.exists():
        errors.append(f"{path.relative_to(ROOT)}: required host adapter file missing")

for path in (ROOT / "skills").rglob("SKILL.md"):
    text = path.read_text(encoding="utf-8")
    if "python3 scripts/" in text:
        errors.append(f"{path.relative_to(ROOT)}: installed skill must use proofloop-core sidecar, not repository-relative scripts")

entry_text = (ROOT / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
if "invoke-role" in entry_text and "Do not manually call `invoke-role`" not in entry_text:
    errors.append("skills/proofloop/SKILL.md: invoke-role must not be exposed as a user workflow")
for path in (ROOT / "proofloop_core" / "orchestrator.py", ROOT / "proofloop_core" / "adapters.py", ROOT / "proofloop_core" / "strategy.py"):
    if not path.exists():
        errors.append(f"{path.relative_to(ROOT)}: automatic orchestrator component missing")

if errors:
    print("PACKAGE VALIDATION: FAIL", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)
print(f"PACKAGE VALIDATION: PASS ({len(runtime_files)} runtime files, {len(source_files)} total files)")
