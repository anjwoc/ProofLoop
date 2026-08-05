#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    ROOT / "proofloop_core" / "contracts" / "prompt_contract.py",
    ROOT / "proofloop_core" / "prompting" / "algebra.py",
    ROOT / "proofloop_core" / "contracts" / "role_view.py",
    ROOT / "proofloop_core" / "engine" / "roles.py",
    ROOT / "proofloop_core" / "engine" / "task_executor.py",
)


def _calls(tree: ast.AST, function_name: str) -> int:
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == function_name:
            total += 1
        elif isinstance(func, ast.Attribute) and func.attr == function_name:
            total += 1
    return total


def main() -> int:
    failures: list[str] = []
    for path in REQUIRED_FILES:
        if not path.is_file():
            failures.append(f"missing required prompt-pipeline file: {path.relative_to(ROOT)}")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"syntax error in {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")

    roles_path = ROOT / "proofloop_core" / "engine" / "roles.py"
    executor_path = ROOT / "proofloop_core" / "engine" / "task_executor.py"
    if roles_path.is_file():
        roles_text = roles_path.read_text(encoding="utf-8")
        roles_tree = ast.parse(roles_text)
        if _calls(roles_tree, "compile_role_ir") < 3:
            failures.append("roles.py does not compile explorer, planner, and reviewer through compile_role_ir")
        for forbidden in ('request_id="todo"', 'contract_id="todo"', 'compiler_version="todo"'):
            if forbidden in roles_text:
                failures.append(f"roles.py retains forbidden placeholder: {forbidden}")
        if _calls(roles_tree, "PromptIR"):
            failures.append("roles.py constructs PromptIR directly instead of using the prompt contract")
    if executor_path.is_file():
        executor_text = executor_path.read_text(encoding="utf-8")
        executor_tree = ast.parse(executor_text)
        if _calls(executor_tree, "compile_role_ir") < 1:
            failures.append("task_executor.py bypasses compile_role_ir")
        if _calls(executor_tree, "PromptIR"):
            failures.append("task_executor.py constructs PromptIR directly")

    algebra = (ROOT / "proofloop_core" / "prompting" / "algebra.py").read_text(encoding="utf-8")
    if "set.intersection" not in algebra:
        failures.append("template algebra does not use restrictive allowed-scope intersection")
    if "time.time" in algebra:
        failures.append("template algebra still uses time-based prompt identity")
    prompt_contract = (ROOT / "proofloop_core" / "contracts" / "prompt_contract.py").read_text(encoding="utf-8")
    for tier in ("T0", "T1", "T2", "T3"):
        if tier not in (ROOT / "proofloop_core" / "config" / "default-run-policy.json").read_text(encoding="utf-8"):
            failures.append(f"run policy omits prompt compiler tier {tier}")
    if "prompt-compilation.json" not in prompt_contract or "execution-brief.json" not in prompt_contract:
        failures.append("prompt contract does not persist both compilation and active brief artifacts")

    if failures:
        print("PROMPT_PIPELINE_INVALID")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PROMPT_PIPELINE_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
