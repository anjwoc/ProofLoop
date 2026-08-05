#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def save(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def update_policy_schema(budgets: dict[str, int]) -> None:
    policy_path = ROOT / "proofloop_core/config/default-run-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["skills"] = {
        "tierTokenBudgets": {tier: int(budgets[tier]) for tier in ("T0", "T1", "T2", "T3")}
    }
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    path = "proofloop_core/contracts/run_policy.py"
    text = load(path)
    text = text.replace(
        '    "release",\n}',
        '    "release",\n    "skills",\n}',
    )
    if 'tierTokenBudgets' not in text:
        anchor = '    release = _validate_exact(value["release"], {"requiredClaimTypes"}, "release")\n'
        replacement = (
            anchor
            + '    skills = _validate_exact(value["skills"], {"tierTokenBudgets"}, "skills")\n'
            + '    tier_budgets = _validate_exact(\n'
            + '        skills["tierTokenBudgets"], {"T0", "T1", "T2", "T3"}, "skills.tierTokenBudgets"\n'
            + '    )\n'
        )
        if anchor not in text:
            raise RuntimeError("run_policy release validation anchor not found")
        text = text.replace(anchor, replacement, 1)
        positive_anchor = '        _positive_int(item, path)\n\n    roles = value.get("roles")\n'
        positive_replacement = (
            '        _positive_int(item, path)\n'
            '    for tier, budget in tier_budgets.items():\n'
            '        _positive_int(budget, f"skills.tierTokenBudgets.{tier}")\n\n'
            '    roles = value.get("roles")\n'
        )
        if positive_anchor not in text:
            raise RuntimeError("run_policy positive-int anchor not found")
        text = text.replace(positive_anchor, positive_replacement, 1)
    save(path, text)


def extract_tier_budgets(text: str) -> tuple[str, dict[str, int]]:
    tree = ast.parse(text)
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target: ast.expr | None
        value: ast.expr | None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Dict):
            continue
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, TypeError):
            continue
        if (
            isinstance(parsed, dict)
            and set(parsed) == {"T0", "T1", "T2", "T3"}
            and all(isinstance(item, int) and item > 0 for item in parsed.values())
        ):
            return target.id, {str(key): int(item) for key, item in parsed.items()}
    # Already migrated source: recover values from shipped policy.
    policy = json.loads((ROOT / "proofloop_core/config/default-run-policy.json").read_text(encoding="utf-8"))
    values = policy.get("skills", {}).get("tierTokenBudgets")
    if isinstance(values, dict) and set(values) == {"T0", "T1", "T2", "T3"}:
        return "", {str(key): int(item) for key, item in values.items()}
    raise RuntimeError("engine/skills.py tier token budget mapping not found")


def migrate_skills() -> None:
    path = "proofloop_core/engine/skills.py"
    text = load(path)
    mapping_name, budgets = extract_tier_budgets(text)
    update_policy_schema(budgets)
    if mapping_name:
        # Delete only the literal top-level mapping found by AST.
        pattern = rf"(?ms)^{re.escape(mapping_name)}(?:\s*:[^=]+)?\s*=\s*\{{.*?^\}}\s*\n"
        text, count = re.subn(pattern, "", text, count=1)
        if count != 1:
            raise RuntimeError(f"failed to remove {mapping_name} from engine/skills.py")
        function_match = re.search(r"(?m)^def resolve_skills\(([^)]*)\).*?:\n", text)
        if function_match is None or "orchestrator" not in function_match.group(1):
            raise RuntimeError("resolve_skills(orchestrator) entry point not found")
        insertion = (
            function_match.group(0)
            + "    tier_token_budgets = {\n"
            + "        tier: int(orchestrator.run_policy.get(f\"skills.tierTokenBudgets.{tier}\"))\n"
            + "        for tier in (\"T0\", \"T1\", \"T2\", \"T3\")\n"
            + "    }\n"
        )
        text = text[: function_match.start()] + insertion + text[function_match.end() :]
        text = text.replace(mapping_name, "tier_token_budgets")
    if "skills.tierTokenBudgets" not in text:
        raise RuntimeError("engine/skills.py is not bound to run policy")
    save(path, text)


def migrate_live_evidence() -> None:
    path = "proofloop_core/assurance/live_evidence.py"
    text = load(path)
    if "from proofloop_core.contracts.run_policy import resolve_run_policy" not in text:
        import_anchor = "from proofloop_core.context.io import read_json, write_json\n"
        if import_anchor not in text:
            raise RuntimeError("live_evidence io import anchor not found")
        text = text.replace(
            import_anchor,
            import_anchor
            + "from proofloop_core.contracts.host_receipt import HostReceiptError, validate_host_receipt\n"
            + "from proofloop_core.contracts.run_policy import resolve_run_policy\n",
            1,
        )
    replacements = {
        "_MAX_FILES = 256": '_MAX_FILES = int(resolve_run_policy().get("evidence.maxFiles"))',
        "_MAX_TOTAL_BYTES = 64 * 1024 * 1024": '_MAX_TOTAL_BYTES = int(resolve_run_policy().get("evidence.maxTotalBytes"))',
        "_READ_CHUNK = 65536": '_READ_CHUNK = int(resolve_run_policy().get("evidence.readChunkBytes"))',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Support equivalent literal forms without inventing a second value.
    text = re.sub(
        r"(?m)^_MAX_FILES\s*=\s*\d+\s*$",
        '_MAX_FILES = int(resolve_run_policy().get("evidence.maxFiles"))',
        text,
    )
    text = re.sub(
        r"(?m)^_MAX_TOTAL_BYTES\s*=\s*[^\n]+$",
        '_MAX_TOTAL_BYTES = int(resolve_run_policy().get("evidence.maxTotalBytes"))',
        text,
    )
    text = re.sub(
        r"(?m)^_READ_CHUNK\s*=\s*\d+\s*$",
        '_READ_CHUNK = int(resolve_run_policy().get("evidence.readChunkBytes"))',
        text,
    )
    if "_validate_core_evidence_base" not in text:
        text, count = re.subn(
            r"(?m)^def validate_core_evidence\(",
            "def _validate_core_evidence_base(",
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError("validate_core_evidence entry point not found")
        text += '''


def _effective_evidence_policy(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    policy_path = root / "run-policy.json"
    provenance_path = root / "run-provenance.json"
    if not policy_path.is_file() or not provenance_path.is_file():
        raise ValueError("RUN_POLICY_OR_PROVENANCE_MISSING")
    policy = read_json(policy_path)
    provenance = read_json(provenance_path)
    values = policy.get("values") if isinstance(policy, dict) else None
    evidence = values.get("evidence") if isinstance(values, dict) else None
    if not isinstance(evidence, dict):
        raise ValueError("RUN_POLICY_EVIDENCE_INVALID")
    if policy.get("sha256") != provenance.get("policyHash"):
        raise ValueError("POLICY_PROVENANCE_MISMATCH")
    return evidence, provenance


def validate_core_evidence(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    reasons: list[str] = []
    try:
        evidence_policy, provenance = _effective_evidence_policy(root)
    except (ValueError, OSError) as exc:
        evidence_policy = {}
        provenance = {}
        reasons.append(str(exc))
    result = _validate_core_evidence_base(root)
    if isinstance(result.get("reasons"), list):
        reasons.extend(str(item) for item in result["reasons"])
    required_claims = set(provenance.get("requiredClaimTypes") or []) if isinstance(provenance, dict) else set()
    receipt_required = bool({"HOST_EXECUTION", "MODEL_ROUTING"}.intersection(required_claims))
    receipt_paths = sorted((root / "invocations").glob("*/receipt.json")) if (root / "invocations").is_dir() else []
    if receipt_required and not receipt_paths:
        reasons.append("HOST_RECEIPT_MISSING")
    for receipt_path in receipt_paths:
        try:
            validate_host_receipt(root, receipt_path.parent.name)
        except HostReceiptError as exc:
            reasons.append(exc.code)
    if evidence_policy:
        manifest = result.get("manifest")
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if isinstance(files, list) and len(files) > int(evidence_policy["maxFiles"]):
            reasons.append("EVIDENCE_FILE_LIMIT_EXCEEDED")
        total = sum(int(item.get("size", 0)) for item in files if isinstance(item, dict)) if isinstance(files, list) else 0
        if total > int(evidence_policy["maxTotalBytes"]):
            reasons.append("EVIDENCE_BYTE_LIMIT_EXCEEDED")
    result["policyHash"] = provenance.get("policyHash") if isinstance(provenance, dict) else None
    result["provenanceHash"] = provenance.get("provenanceSha256") if isinstance(provenance, dict) else None
    result["validatedReceipts"] = [str(item) for item in receipt_paths]
    result["reasons"] = list(dict.fromkeys(reasons))
    result["status"] = "VALID" if not result["reasons"] else "INVALID"
    write_json(root / "live-evidence.json", result)
    return result
'''
    if "evidence.maxFiles" not in text or "validate_host_receipt" not in text:
        raise RuntimeError("live evidence policy/receipt migration incomplete")
    save(path, text)


def main() -> int:
    migrate_skills()
    migrate_live_evidence()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(ROOT / "proofloop_core/contracts/run_policy.py"),
            str(ROOT / "proofloop_core/engine/skills.py"),
            str(ROOT / "proofloop_core/assurance/live_evidence.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    print("ULW_INTEGRITY_MIGRATION_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
