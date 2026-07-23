#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def save(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_if_present(text: str, old: str, new: str) -> str:
    return text.replace(old, new) if old in text else text


def migrate_orchestrator() -> None:
    path = "proofloop_core/engine/orchestrator.py"
    text = load(path)
    text = replace_if_present(
        text,
        "from proofloop_core.contracts.run_state import start_run, finalize_run\n",
        "from proofloop_core.contracts.run_policy import ResolvedRunPolicy, resolve_run_policy\n"
        "from proofloop_core.contracts.run_state import (\n"
        "    InvocationContext,\n"
        "    create_invocation_context,\n"
        "    start_run,\n"
        "    finalize_run,\n"
        ")\n",
    )
    text = text.replace("timeout_seconds: int = 1200,", "timeout_seconds: int | None = None,")
    text = text.replace("max_goal_cycles: int = 8,", "max_goal_cycles: int | None = None,")
    text = text.replace("max_replans: int = 2,", "max_replans: int | None = None,")
    if "run_policy: ResolvedRunPolicy | None = None" not in text:
        text = text.replace(
            "        event_bus: EventBus | None = None,\n    ) -> None:\n",
            "        event_bus: EventBus | None = None,\n"
            "        run_policy: ResolvedRunPolicy | None = None,\n"
            "        invocation_context: InvocationContext | None = None,\n"
            "    ) -> None:\n",
            1,
        )
    text = replace_if_present(
        text,
        "        self.goal_mode = goal_mode or mode == \"goal\"\n"
        "        self.max_goal_cycles = max_goal_cycles\n"
        "        self.max_replans = max_replans\n"
        "        self.adapter = adapter or ExternalCLIAdapter(host, routing_policy=\"goal\" if goal_mode else \"controller\")\n"
        "        self.strategy_override = strategy_override\n"
        "        self.timeout_seconds = timeout_seconds\n",
        "        self.goal_mode = goal_mode or mode == \"goal\"\n"
        "        policy_overrides = {\n"
        "            \"run.timeoutSeconds\": timeout_seconds,\n"
        "            \"goal.maxCycles\": max_goal_cycles,\n"
        "            \"goal.maxReplans\": max_replans,\n"
        "        }\n"
        "        self.run_policy = run_policy or resolve_run_policy(cli_overrides=policy_overrides)\n"
        "        self.invocation_context = invocation_context or create_invocation_context(\n"
        "            self.repo,\n"
        "            self.run_policy,\n"
        "            invocation_kind=\"PROGRAMMATIC\",\n"
        "            requested_host=host,\n"
        "        )\n"
        "        self.max_goal_cycles = int(self.run_policy.get(\"goal.maxCycles\"))\n"
        "        self.max_replans = int(self.run_policy.get(\"goal.maxReplans\"))\n"
        "        self.adapter = adapter or ExternalCLIAdapter(host, routing_policy=\"goal\" if goal_mode else \"controller\")\n"
        "        self.strategy_override = strategy_override\n"
        "        self.timeout_seconds = int(self.run_policy.get(\"run.timeoutSeconds\"))\n",
    )
    text = replace_if_present(
        text,
        "        started = start_run(self.repo, self.request)\n",
        "        started = start_run(\n"
        "            self.repo,\n"
        "            self.request,\n"
        "            policy=self.run_policy,\n"
        "            invocation_context=self.invocation_context,\n"
        "        )\n",
    )
    if "roles.{role}.timeoutSeconds" not in text:
        text, count = re.subn(
            r"    def _role_time_budget_seconds\(self, role: str\) -> int:\n.*?(?=\n    def )",
            "    def _role_time_budget_seconds(self, role: str) -> int:\n"
            "        configured = int(self.run_policy.get(f\"roles.{role}.timeoutSeconds\"))\n"
            "        return min(self.timeout_seconds, configured)\n",
            text,
            count=1,
            flags=re.DOTALL,
        )
        if count != 1:
            raise RuntimeError("orchestrator role time-budget method not found")
    text = replace_if_present(
        text,
        "        simplicity=SimplicityPlan(\n"
        "            selected_rung=ranked[0].simplicity.selected_rung,\n"
        "            rationale=\"; \".join(task.simplicity.rationale for task in ranked),\n"
        "            considered=tuple(dict.fromkeys(item for task in ranked for item in task.simplicity.considered)),\n"
        "        ),\n",
        "        simplicity=SimplicityPlan(\n"
        "            selected_rung=ranked[0].simplicity.selected_rung,\n"
        "            rationale=\"; \".join(task.simplicity.rationale for task in ranked),\n"
        "            considered=tuple(dict.fromkeys(item for task in ranked for item in task.simplicity.considered)),\n"
        "            evidence_refs=tuple(dict.fromkeys(item for task in ranked for item in task.simplicity.evidence_refs)),\n"
        "            permitted_new_artifacts=tuple(\n"
        "                dict.fromkeys(item for task in ranked for item in task.simplicity.permitted_new_artifacts)\n"
        "            ),\n"
        "        ),\n",
    )
    text = replace_if_present(
        text,
        "        \"simplicity\": {\n"
        "            \"selectedRung\": task.simplicity.selected_rung,\n"
        "            \"rationale\": task.simplicity.rationale,\n"
        "            \"considered\": list(task.simplicity.considered),\n"
        "        },\n",
        "        \"simplicity\": {\n"
        "            \"selectedRung\": task.simplicity.selected_rung,\n"
        "            \"rationale\": task.simplicity.rationale,\n"
        "            \"considered\": list(task.simplicity.considered),\n"
        "            \"evidenceRefs\": list(task.simplicity.evidence_refs),\n"
        "            \"permittedNewArtifacts\": list(task.simplicity.permitted_new_artifacts),\n"
        "        },\n",
    )
    signature = (
        "    experimental_domain_packs: bool = False,\n"
        ") -> dict[str, Any]:\n"
        "    return ProofLoopOrchestrator("
    )
    replacement = (
        "    experimental_domain_packs: bool = False,\n"
        "    run_policy: ResolvedRunPolicy | None = None,\n"
        "    invocation_context: InvocationContext | None = None,\n"
        ") -> dict[str, Any]:\n"
        "    return ProofLoopOrchestrator("
    )
    text = text.replace(signature, replacement)
    text = replace_if_present(
        text,
        "    event_bus: EventBus | None = None,\n"
        ") -> dict[str, Any]:\n"
        "    effective_goal_mode",
        "    event_bus: EventBus | None = None,\n"
        "    run_policy: ResolvedRunPolicy | None = None,\n"
        "    invocation_context: InvocationContext | None = None,\n"
        ") -> dict[str, Any]:\n"
        "    effective_goal_mode",
    )
    text = text.replace(
        "        experimental_domain_packs=experimental_domain_packs,\n    ).run()\n",
        "        experimental_domain_packs=experimental_domain_packs,\n"
        "        run_policy=run_policy,\n"
        "        invocation_context=invocation_context,\n"
        "    ).run()\n",
    )
    text = replace_if_present(
        text,
        "        event_bus=event_bus,\n    ).run()\n",
        "        event_bus=event_bus,\n"
        "        run_policy=run_policy,\n"
        "        invocation_context=invocation_context,\n"
        "    ).run()\n",
    )
    save(path, text)


def migrate_cli() -> None:
    path = "proofloop_core/ui/cli.py"
    text = load(path)
    text = replace_if_present(
        text,
        "from proofloop_core.contracts.run_state import start_run, abort_run, finalize_run\n",
        "from proofloop_core.contracts.run_policy import resolve_run_policy\n"
        "from proofloop_core.contracts.run_state import create_invocation_context, start_run, abort_run, finalize_run\n",
    )
    for old in ("default=1200", "default=8", "default=2", "default=3"):
        text = text.replace(old, "default=None")
    for parser_name in ("p_orch", "p_goal", "p_run"):
        needle = f'    {parser_name}.add_argument("--strategy")\n'
        if f'{parser_name}.add_argument("--policy-file")' not in text:
            text = text.replace(needle, needle + f'    {parser_name}.add_argument("--policy-file")\n')
    if "policy_overrides = {" not in text:
        text = text.replace(
            "    args = parser.parse_args()\n\n",
            "    args = parser.parse_args()\n"
            "    policy_overrides = {\n"
            "        \"run.timeoutSeconds\": getattr(args, \"timeout_seconds\", None),\n"
            "        \"goal.maxCycles\": getattr(args, \"max_goal_cycles\", None),\n"
            "        \"goal.maxReplans\": getattr(args, \"max_replans\", None),\n"
            "        \"relay.intervalSeconds\": getattr(args, \"wait_seconds\", None),\n"
            "    }\n"
            "    run_policy = resolve_run_policy(\n"
            "        policy_file=getattr(args, \"policy_file\", None),\n"
            "        cli_overrides=policy_overrides,\n"
            "    )\n\n",
            1,
        )
    text = replace_if_present(
        text,
        "        value = start_run(args.repo, request)\n",
        "        context = create_invocation_context(\n"
        "            args.repo, run_policy, invocation_kind=\"CLI\", requested_host=None\n"
        "        )\n"
        "        value = start_run(args.repo, request, policy=run_policy, invocation_context=context)\n",
    )
    text = text.replace(
        "timeout_seconds=args.timeout_seconds,",
        'timeout_seconds=int(run_policy.get("run.timeoutSeconds")),',
    )
    text = text.replace(
        "max_goal_cycles=args.max_goal_cycles,",
        'max_goal_cycles=int(run_policy.get("goal.maxCycles")),',
    )
    text = text.replace(
        "max_replans=args.max_replans,",
        'max_replans=int(run_policy.get("goal.maxReplans")),',
    )
    text = replace_if_present(
        text,
        "            wait_seconds=args.wait_seconds,\n",
        '            wait_seconds=int(run_policy.get("relay.intervalSeconds")),\n',
    )
    tail = "            experimental_domain_packs=args.experimental_domain_packs,\n        )\n"
    text = text.replace(
        tail,
        "            experimental_domain_packs=args.experimental_domain_packs,\n"
        "            run_policy=run_policy,\n"
        "            invocation_context=create_invocation_context(\n"
        "                args.repo, run_policy, invocation_kind=\"CLI\", requested_host=args.host\n"
        "            ),\n"
        "        )\n",
    )
    text = replace_if_present(
        text,
        "            event_bus=event_bus,\n        )\n",
        "            event_bus=event_bus,\n"
        "            run_policy=run_policy,\n"
        "            invocation_context=create_invocation_context(\n"
        "                args.repo, run_policy, invocation_kind=\"CLI\", requested_host=args.host\n"
        "            ),\n"
        "        )\n",
    )
    save(path, text)


def migrate_adapter() -> None:
    path = "proofloop_core/runtimes/adapters.py"
    text = load(path)
    text = text.replace("    timeout_seconds: int = 1200\n", "    timeout_seconds: int | None = None\n")
    if "RoleInvocation.timeout_seconds must come from the resolved run policy" not in text:
        marker = "        resolved = invocation.runtime or self.resolve_role(invocation.role)\n"
        text = text.replace(
            marker,
            "        if invocation.timeout_seconds is None:\n"
            "            raise ValueError(\"RoleInvocation.timeout_seconds must come from the resolved run policy\")\n"
            + marker,
        )
    save(path, text)


def migrate_tests_and_docs() -> None:
    path = "tests/deterministic/test_orchestrator_smoke.py"
    text = load(path)
    text = replace_if_present(
        text,
        '                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "test fixture", "considered": ["REUSE_EXISTING"]},\n',
        '                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "test fixture", '
        '"considered": ["REUSE_EXISTING", "STDLIB", "PLATFORM_NATIVE", "INSTALLED_DEPENDENCY"], '
        '"evidenceRefs": ["fixture#/direct-change"], "permittedNewArtifacts": []},\n',
    )
    save(path, text)
    replacements = (
        (
            "tests/deterministic/test_execution_brief.py",
            'self.assertEqual("user_explicit", shadow["riskSignals"][0]["provenance"])',
            'self.assertEqual("proof_policy", shadow["riskSignals"][0]["provenance"])',
        ),
        (
            "tests/deterministic/test_proof_graph.py",
            'self.assertEqual("INSUFFICIENT_AUTHORITY", graph.obligations[0].last_reason)',
            'self.assertEqual("EVIDENCE_AUTHORITY_NOT_ELIGIBLE", graph.obligations[0].last_reason)',
        ),
        (
            "docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md",
            "`python3 -m unittest tests.deterministic.test_direct_bootstrap -v`",
            "`python3 -m pytest tests/deterministic/test_orchestrator_smoke.py -q`",
        ),
        (
            "docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md",
            "`python3 -m unittest tests.deterministic.test_static_web -v`",
            "`python3 -m pytest tests/deterministic/test_ponytail_enforcement.py -q`",
        ),
    )
    for file_name, old, new in replacements:
        save(file_name, replace_if_present(load(file_name), old, new))


def validate_migration() -> None:
    orchestrator = load("proofloop_core/engine/orchestrator.py")
    cli = load("proofloop_core/ui/cli.py")
    adapter = load("proofloop_core/runtimes/adapters.py")
    assertions = {
        "orchestrator policy state": "self.run_policy = run_policy or resolve_run_policy" in orchestrator,
        "start_run policy binding": "policy=self.run_policy" in orchestrator,
        "role timeout policy": "roles.{role}.timeoutSeconds" in orchestrator,
        "simplicity evidence serialization": '"evidenceRefs": list(task.simplicity.evidence_refs)' in orchestrator,
        "artifact permission serialization": '"permittedNewArtifacts": list(task.simplicity.permitted_new_artifacts)' in orchestrator,
        "CLI policy resolver": "run_policy = resolve_run_policy(" in cli,
        "CLI timeout default removed": "default=1200" not in cli,
        "adapter timeout default removed": "timeout_seconds: int = 1200" not in adapter,
    }
    missing = [name for name, valid in assertions.items() if not valid]
    if missing:
        raise RuntimeError("migration assertions failed: " + ", ".join(missing))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(ROOT / "proofloop_core/engine/orchestrator.py"),
            str(ROOT / "proofloop_core/ui/cli.py"),
            str(ROOT / "proofloop_core/runtimes/adapters.py"),
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    migrate_orchestrator()
    migrate_cli()
    migrate_adapter()
    migrate_tests_and_docs()
    validate_migration()
    print("ULW_POLICY_MIGRATION_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
