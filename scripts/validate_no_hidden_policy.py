#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_NAMES = {
    "timeout_seconds",
    "max_goal_cycles",
    "max_replans",
    "max_fast_attempts",
    "max_recovery_attempts",
    "heartbeat_interval_seconds",
    "max_files",
    "max_total_bytes",
    "hook_timeout_seconds",
    "relay_interval_seconds",
    "token_budget",
}
TARGETS = (
    "proofloop_core/ui/cli.py",
    "proofloop_core/engine/orchestrator.py",
    "proofloop_core/engine/repair.py",
    "proofloop_core/engine/skills.py",
    "proofloop_core/contracts/task_brief.py",
    "proofloop_core/runtimes/adapters.py",
    "proofloop_core/assurance/live_evidence.py",
)


def _numeric(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _name(node: ast.arg) -> str:
    return node.arg


def _function_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef, path: str, failures: list[str]) -> None:
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
    pairs = list(zip(positional, defaults)) + list(zip(node.args.kwonlyargs, node.args.kw_defaults))
    for argument, default in pairs:
        if _name(argument) in POLICY_NAMES and _numeric(default):
            failures.append(f"{path}:{node.lineno} numeric default for policy field {_name(argument)}")


def _dataclass_defaults(tree: ast.AST, path: str, failures: list[str]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AnnAssign, ast.Assign)):
            continue
        target_name: str | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value
        if target_name in POLICY_NAMES and _numeric(value):
            failures.append(f"{path}:{node.lineno} module/dataclass numeric policy default {target_name}")


def _argparse_defaults(tree: ast.AST, path: str, failures: list[str]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        names = [item.value for item in node.args if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        relevant = any(any(token in name for token in ("timeout", "cycles", "replans", "budget", "retained")) for name in names)
        if not relevant:
            continue
        for keyword in node.keywords:
            if keyword.arg == "default" and _numeric(keyword.value):
                failures.append(f"{path}:{node.lineno} argparse operational default for {'/'.join(names)}")


def main() -> int:
    failures: list[str] = []
    for relative in TARGETS:
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing policy-sensitive module: {relative}")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{relative}:{exc.lineno} syntax error: {exc.msg}")
            continue
        _dataclass_defaults(tree, relative, failures)
        _argparse_defaults(tree, relative, failures)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _function_defaults(node, relative, failures)

    run_state = (ROOT / "proofloop_core/contracts/run_state.py").read_text(encoding="utf-8")
    if "sys.argv" in run_state or "PROOFLOOP_INVOCATION_HOST" in run_state:
        failures.append("proofloop_core/contracts/run_state.py infers provenance from argv/environment")
    if not (ROOT / "proofloop_core/config/default-run-policy.json").is_file():
        failures.append("default-run-policy.json is missing")
    if not (ROOT / "proofloop_core/contracts/run_policy.py").is_file():
        failures.append("strict run_policy.py resolver is missing")

    if failures:
        print("HIDDEN_POLICY_DETECTED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("NO_HIDDEN_OPERATIONAL_POLICY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
