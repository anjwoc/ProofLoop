from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checks import run_checks
from .diff_guard import inspect_diff
from .fingerprint import fingerprint_check_report
from .io import read_json, write_json
from .repair import decide_next
from .task_brief import load_task_brief
from .trace import summarize_trace
from .truth import build_truth_report
from .assurance import build_assurance_report
from .preflight import preflight
from .external_loop import run_external_loop
from .repository_context import ensure_codegraph
from .run_state import start_run, abort_run, finalize_run
from .attempts import record_attempt
from .hosts import capability, probe
from .host_runner import invoke_role
from .orchestrator import converge_goal, orchestrate
from .watch import resolve_run_dir, watch_events
from .tokscale import TokScaleAdapter
from .usage import build_usage_summary
from .benchmark import compare_benchmark, run_benchmark


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))



def _resolve_host(value: str) -> str:
    if value != "auto":
        return value
    import os
    import shutil

    explicit = os.environ.get("PROOFLOOP_HOST")
    if explicit in {"claude-code", "codex", "antigravity"}:
        return explicit
    signals = [
        ("codex", os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")),
        ("claude-code", os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDECODE")),
        ("antigravity", os.environ.get("ANTIGRAVITY_SESSION_ID") or os.environ.get("AGY_SESSION_ID")),
    ]
    detected = [host for host, signal in signals if signal]
    if len(detected) == 1:
        return detected[0]
    installed = [host for host, binary in (("codex", "codex"), ("antigravity", "agy"), ("claude-code", "claude")) if shutil.which(binary)]
    if len(installed) == 1:
        return installed[0]
    raise ValueError("cannot auto-detect host; pass --host or set PROOFLOOP_HOST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proofloop-core")
    sub = parser.add_subparsers(dest="command", required=True)


    p_orchestrate = sub.add_parser("orchestrate")
    p_orchestrate.add_argument("--host", choices=["auto", "claude-code", "codex", "antigravity"], default="auto")
    p_orchestrate.add_argument("--repo", default=".")
    request_group = p_orchestrate.add_mutually_exclusive_group(required=True)
    request_group.add_argument("--request")
    request_group.add_argument("--request-file")
    p_orchestrate.add_argument("--strategy", choices=["direct", "planned", "high-risk", "analysis"])
    p_orchestrate.add_argument("--timeout-seconds", type=int, default=1200)
    p_orchestrate.add_argument("--output-format", choices=["human", "jsonl", "quiet"], default="quiet")
    p_orchestrate.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_orchestrate.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    p_goal = sub.add_parser("goal")
    p_goal.add_argument("--host", choices=["auto", "claude-code", "codex", "antigravity"], default="auto")
    p_goal.add_argument("--repo", default=".")
    goal_request_group = p_goal.add_mutually_exclusive_group(required=True)
    goal_request_group.add_argument("--request")
    goal_request_group.add_argument("--request-file")
    p_goal.add_argument("--strategy", choices=["direct", "planned", "high-risk"])
    p_goal.add_argument("--timeout-seconds", type=int, default=1200)
    p_goal.add_argument("--max-cycles", type=int, default=8)
    p_goal.add_argument("--max-replans", type=int, default=2)
    p_goal.add_argument("--output-format", choices=["human", "jsonl", "quiet"], default="human")
    p_goal.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_goal.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    p_watch = sub.add_parser("watch")
    watch_source = p_watch.add_mutually_exclusive_group(required=True)
    watch_source.add_argument("--run")
    watch_source.add_argument("--run-dir")
    p_watch.add_argument("--repo", default=".")
    p_watch.add_argument("--format", choices=["human", "jsonl"], default="human")
    p_watch.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_watch.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p_watch.add_argument("--task")
    p_watch.add_argument("--level", choices=["debug", "info", "warning", "error"])
    p_watch.add_argument("--no-follow", action="store_true")

    p_usage = sub.add_parser("usage")
    usage_source = p_usage.add_mutually_exclusive_group(required=True)
    usage_source.add_argument("--run")
    usage_source.add_argument("--run-dir")
    p_usage.add_argument("--repo", default=".")
    p_usage.add_argument("--reconcile", action="store_true")
    p_usage.add_argument("--tokscale-binary")

    p_benchmark = sub.add_parser("benchmark")
    p_benchmark.add_argument("--suite", required=True)
    p_benchmark.add_argument("--repo", default=".")
    p_benchmark.add_argument("--mode", choices=["routing", "system", "both"], default="both")
    p_benchmark.add_argument("--repetitions", type=int, default=5)
    p_benchmark.add_argument("--baseline-host", choices=["claude-code", "codex", "gemini", "antigravity"], required=True)
    p_benchmark.add_argument("--baseline-model", required=True)
    p_benchmark.add_argument("--proofloop-host", choices=["auto", "claude-code", "codex", "antigravity"], default="auto")
    p_benchmark.add_argument("--timeout-seconds", type=int, default=1200)
    p_benchmark.add_argument("--seed", type=int, default=0)

    p_compare = sub.add_parser("compare")
    p_compare.add_argument("--benchmark-dir", required=True)

    p_pre = sub.add_parser("preflight")
    p_pre.add_argument("--repo", default=".")
    p_pre.add_argument("--output")

    p_record = sub.add_parser("record-attempt")
    p_record.add_argument("--task", required=True)
    p_record.add_argument("--run-dir", required=True)
    p_record.add_argument("--role", choices=["implementer_fast", "implementer_recovery"], required=True)
    p_record.add_argument("--observed-model")

    p_start = sub.add_parser("start-run")
    p_start.add_argument("--repo", default=".")
    p_start.add_argument("--request", default="")

    p_abort = sub.add_parser("abort-run")
    p_abort.add_argument("--repo", default=".")
    p_abort.add_argument("--reason", required=True)

    p_context = sub.add_parser("ensure-context")
    p_context.add_argument("--repo", default=".")
    p_context.add_argument("--output", required=True)
    p_context.add_argument("--optional", action="store_true")
    p_context.add_argument("--mock", action="store_true")

    p_loop = sub.add_parser("external-loop")
    p_loop.add_argument("--task", required=True)
    p_loop.add_argument("--repo", default=".")
    p_loop.add_argument("--run-dir", required=True)
    p_loop.add_argument("--fast-command-json", required=True)
    p_loop.add_argument("--recovery-command-json")
    p_loop.add_argument("--baseline", default="HEAD")
    p_loop.add_argument("--timeout-seconds", type=int, default=900)

    p_checks = sub.add_parser("run-checks")
    p_checks.add_argument("--task", required=True)
    p_checks.add_argument("--repo", default=".")
    p_checks.add_argument("--output", required=True)

    p_diff = sub.add_parser("diff-guard")
    p_diff.add_argument("--task", required=True)
    p_diff.add_argument("--repo", default=".")
    p_diff.add_argument("--baseline", default="HEAD")
    p_diff.add_argument("--output", required=True)

    p_fp = sub.add_parser("fingerprint")
    p_fp.add_argument("--checks", required=True)

    p_repair = sub.add_parser("decide-repair")
    p_repair.add_argument("--attempts", required=True)
    p_repair.add_argument("--task", required=True)

    p_trace = sub.add_parser("summarize-trace")
    p_trace.add_argument("--trace", required=True)
    p_trace.add_argument("--output", required=True)

    p_host = sub.add_parser("host-capabilities")
    p_host.add_argument("--host", choices=["claude-code", "codex", "gemini", "antigravity"], required=True)
    p_host.add_argument("--probe", action="store_true")

    p_invoke = sub.add_parser("invoke-role")
    p_invoke.add_argument("--host", choices=["claude-code", "codex", "gemini", "antigravity"], required=True)
    p_invoke.add_argument("--role", choices=["planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"], required=True)
    p_invoke.add_argument("--repo", default=".")
    p_invoke.add_argument("--run-dir", required=True)
    p_invoke.add_argument("--task")
    p_invoke.add_argument("--prompt")
    p_invoke.add_argument("--binary")
    p_invoke.add_argument("--timeout-seconds", type=int, default=1200)

    p_truth = sub.add_parser("verify-run")
    p_truth.add_argument("--run-dir", required=True)
    p_truth.add_argument("--output")

    args = parser.parse_args(argv)
    if args.command == "watch":
        selected = resolve_run_dir(repo=args.repo, run=args.run, run_dir=args.run_dir)
        try:
            watch_events(
                selected,
                stream=sys.stdout,
                output_format=args.format,
                verbosity=args.verbosity,
                color=args.color,
                task_id=args.task,
                minimum_level=args.level,
                follow=not args.no_follow,
            )
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "usage":
        selected = resolve_run_dir(repo=args.repo, run=args.run, run_dir=args.run_dir)
        reconciliation = None
        if args.reconcile:
            reconciliation = TokScaleAdapter(args.tokscale_binary).reconcile(selected)
        result = build_usage_summary(selected)
        if reconciliation is not None:
            result["reconciliation"] = reconciliation
        _print(result)
        return 0
    if args.command == "benchmark":
        result = run_benchmark(
            args.suite,
            args.repo,
            mode=args.mode,
            repetitions=args.repetitions,
            baseline_host=args.baseline_host,
            baseline_model=args.baseline_model,
            proofloop_host=_resolve_host(args.proofloop_host),
            timeout_seconds=args.timeout_seconds,
            seed=args.seed,
        )
        _print(result)
        return 0
    if args.command == "compare":
        result = compare_benchmark(args.benchmark_dir)
        _print(result)
        return 0
    if args.command in {"orchestrate", "goal"}:
        host = _resolve_host(args.host)
        request = args.request
        if args.request_file:
            request = Path(args.request_file).read_text(encoding="utf-8")
        strategy_map = {"direct": "DIRECT_VERIFIED_CHANGE", "planned": "PLANNED_IMPLEMENTATION", "high-risk": "HIGH_RISK_ENGINEERING", "analysis": "REPOSITORY_ANALYSIS"}
        runner = converge_goal if args.command == "goal" else orchestrate
        extra = {
            "max_goal_cycles": args.max_cycles,
            "max_replans": args.max_replans,
        } if args.command == "goal" else {}
        result = runner(
            host,
            args.repo,
            request or "",
            strategy_override=strategy_map.get(args.strategy),
            timeout_seconds=args.timeout_seconds,
            output_format=args.output_format,
            verbosity=args.verbosity,
            color=args.color,
            **extra,
        )
    elif args.command == "host-capabilities":
        result = probe(args.host) if args.probe else capability(args.host)
    elif args.command == "invoke-role":
        result = invoke_role(args.host, args.role, args.repo, args.run_dir, args.prompt, args.task, args.binary, args.timeout_seconds)
    elif args.command == "record-attempt":
        result = record_attempt(args.task, args.run_dir, args.role, args.observed_model)
    elif args.command == "start-run":
        result = start_run(args.repo, args.request)
    elif args.command == "abort-run":
        result = abort_run(args.repo, args.reason)
    elif args.command == "ensure-context":
        result = ensure_codegraph(args.repo, args.output, required=not args.optional, mock=args.mock)
    elif args.command == "preflight":
        result = preflight(args.repo)
        if args.output:
            write_json(args.output, result)
    elif args.command == "external-loop":
        fast_command = json.loads(args.fast_command_json)
        recovery_command = json.loads(args.recovery_command_json) if args.recovery_command_json else None
        if not isinstance(fast_command, list) or not all(isinstance(x, str) for x in fast_command):
            parser.error("--fast-command-json must be a JSON string array")
        if recovery_command is not None and (not isinstance(recovery_command, list) or not all(isinstance(x, str) for x in recovery_command)):
            parser.error("--recovery-command-json must be a JSON string array")
        result = run_external_loop(args.task, args.repo, args.run_dir, fast_command, recovery_command, args.baseline, args.timeout_seconds)
    elif args.command == "run-checks":
        result = run_checks(load_task_brief(args.task), args.repo, args.output)
    elif args.command == "diff-guard":
        result = inspect_diff(load_task_brief(args.task), args.repo, args.baseline)
        write_json(args.output, result)
    elif args.command == "fingerprint":
        result = {"failureFingerprint": fingerprint_check_report(read_json(args.checks))}
    elif args.command == "decide-repair":
        task = load_task_brief(args.task)
        raw = Path(args.attempts).read_text(encoding="utf-8") if Path(args.attempts).exists() else ""
        attempts = [json.loads(line) for line in raw.splitlines() if line.strip()]
        result = decide_next(attempts, task.max_fast_attempts, task.max_recovery_attempts)
    elif args.command == "summarize-trace":
        result = summarize_trace(args.trace)
        write_json(args.output, result)
    else:
        assurance = build_assurance_report(args.run_dir)
        write_json(Path(args.run_dir) / "assurance-report.json", assurance)
        result = build_truth_report(args.run_dir)
        output_path = args.output or Path(args.run_dir) / "truth-report.json"
        write_json(output_path, result)
        run_path = Path(args.run_dir).resolve()
        repo = run_path
        while repo.parent != repo and not (repo / ".proofloop").exists():
            repo = repo.parent
        if (repo / ".proofloop").exists():
            finalize_run(repo, result)
    if args.command not in {"orchestrate", "goal"} or args.output_format == "quiet":
        _print(result)
    if args.command in {"orchestrate", "goal"}:
        return 0 if result.get("verdict") == "PROVEN" else 2
    return 0 if result.get("verdict") not in {"FAIL", "FAILED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
