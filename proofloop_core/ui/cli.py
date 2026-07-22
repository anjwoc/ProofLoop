from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from proofloop_core.assurance.checks import run_checks
from proofloop_core.assurance.diff_guard import inspect_diff
from proofloop_core.context.fingerprint import fingerprint_check_report
from proofloop_core.context.redact import redact_secrets
from proofloop_core.context.io import read_json, write_json
from proofloop_core.engine.repair import decide_next
from proofloop_core.contracts.task_brief import load_task_brief
from proofloop_core.context.trace import summarize_trace
from proofloop_core.assurance.truth import build_truth_report
from proofloop_core.assurance.assurance import build_assurance_report
from proofloop_core.assurance.preflight import preflight
from proofloop_core.engine.external_loop import run_external_loop
from proofloop_core.context.repository_context import ensure_codegraph
from proofloop_core.contracts.run_state import start_run, abort_run, finalize_run
from proofloop_core.engine.attempts import record_attempt
from proofloop_core.runtimes.hosts import capability, probe
from proofloop_core.runtimes.host_runner import invoke_role
from proofloop_core.engine.orchestrator import converge_goal, orchestrate, run_proofloop
from proofloop_core.context.events import EventBus
from proofloop_core.ui.watch import WatchPanels, render_watch_panels, resolve_run_dir, watch_events
from proofloop_core.ui.relay import wait_and_poll_relay
from proofloop_core.analysis.tokscale import TokScaleAdapter
from proofloop_core.analysis.usage import build_usage_summary
from proofloop_core.analysis.benchmark import compare_benchmark, resume_benchmark, run_benchmark
from proofloop_core.analysis.benchmark_environment import preflight_swe_environment
from proofloop_core.analysis.swe_skills_bench import REQUIRED_DOMAINS, build_swe_suite, inspect_swe_suite
from proofloop_core.engine.skill_qualification import build_behavior_trial_schedule, qualify_domain_packs


def _print(value: object) -> None:
    print(json.dumps(redact_secrets(value), indent=2, ensure_ascii=False))


def _render_run_report(run_dir: Path) -> str:
    """Return a human-readable run report string for agent display."""

    def _rj(p: Path) -> dict:
        try:
            return read_json(p) if p.exists() else {}
        except Exception:
            return {}

    def _fmt(n: object) -> str:
        if n is None:
            return "–"
        v = int(n)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.2f}M"
        if v >= 1_000:
            return f"{v / 1_000:.1f}K"
        return str(v)

    def _cost(v: object) -> str:
        if not v and v != 0:
            return "–"
        return f"${float(v):.4f}"

    truth = _rj(run_dir / "truth-report.json")
    strategy = _rj(run_dir / "strategy.json")
    run_meta = _rj(run_dir / "run.json")
    model_trace = _rj(run_dir / "model-trace-summary.json")
    usage_path = run_dir / "usage" / "usage-summary.json"
    usage: dict = _rj(usage_path)
    if not usage:
        try:
            usage = build_usage_summary(run_dir)
        except Exception:
            usage = {}

    request_str = run_meta.get("request") or _rj(run_dir / "request.json").get("request", "")
    verdict = truth.get("verdict", "UNKNOWN")
    totals = usage.get("totals") or {}
    by_model = usage.get("byModel") or []
    by_role = usage.get("byRole") or []
    by_inv = usage.get("byInvocation") or []

    req_by_role = model_trace.get("requestedModelsByRole") or {}
    obs_by_role = model_trace.get("observedModelsByRole") or {}
    missing_roles = model_trace.get("missingRoles") or []

    # Duration
    duration = ""
    if run_meta.get("createdAtEpoch") and run_meta.get("finalizedAtEpoch"):
        secs = int(run_meta["finalizedAtEpoch"] - run_meta["createdAtEpoch"])
        duration = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"

    VERDICT_ICON = {"PROVEN": "✅", "PASS": "✅", "BLOCKED": "🚫", "FAILED": "❌", "UNPROVEN": "⚠️"}
    icon = VERDICT_ICON.get(verdict, "❓")

    lines: list[str] = []
    sep = "─" * 60

    lines.append(sep)
    lines.append(f"  {icon}  ProofLoop Run Report  —  {verdict}")
    lines.append(sep)

    if request_str:
        lines.append(f"\n📋 Request\n   {request_str[:200]}{'…' if len(request_str) > 200 else ''}")

    msg = truth.get("message", "")
    if msg:
        lines.append(f"\n   {msg}")

    blockers = truth.get("blockers") or []
    if blockers:
        lines.append(f"\n🚫 Blockers")
        for b in blockers:
            lines.append(f"   • {b}")

    # Run info
    lines.append(f"\n📊 Run Info")
    lines.append(f"   Run ID    : {run_meta.get('runId', run_dir.name)}")
    lines.append(f"   Strategy  : {strategy.get('strategy', '–')}  (risk: {strategy.get('risk', '–')})")
    lines.append(f"   Host      : {model_trace.get('host', '–')}")
    lines.append(f"   Duration  : {duration or '–'}")
    lines.append(f"   Status    : {run_meta.get('status', '–')}")

    # Models table
    if by_model:
        lines.append(f"\n🤖 Token Usage by Model")
        col = [18, 5, 8, 8, 10, 10, 10, 9]
        hdr = ["Model", "Inv", "Input", "Output", "CacheRead", "CacheWrite", "Total", "Cost"]
        lines.append("   " + "  ".join(h.ljust(col[i]) for i, h in enumerate(hdr)))
        lines.append("   " + "  ".join("─" * c for c in col))
        for m in by_model:
            tk = m.get("tokens") or {}
            row = [
                str(m.get("model", "?"))[:18],
                str(m.get("invocations", 0)),
                _fmt(tk.get("input")),
                _fmt(tk.get("output")),
                _fmt(tk.get("cacheRead")),
                _fmt(tk.get("cacheWrite")),
                _fmt(m.get("rawTotal")),
                _cost(m.get("costUsd")),
            ]
            lines.append("   " + "  ".join(v.ljust(col[i]) for i, v in enumerate(row)))

    # Routing table
    all_roles = sorted(set(list(req_by_role) + list(obs_by_role) + missing_roles))
    if all_roles:
        lines.append(f"\n🔀 Model Routing by Role")
        for role in all_roles:
            req = ", ".join(req_by_role.get(role) or ["–"])
            obs = ", ".join(obs_by_role.get(role) or ["–"])
            status = "❌ MISSING" if role in missing_roles else "✅"
            lines.append(f"   {role:<22}  requested={req:<20}  observed={obs:<30}  {status}")

    # Invocation timeline
    inv_log_file = run_dir / "invocations.jsonl"
    inv_log: list[dict] = []
    if inv_log_file.exists():
        for raw in inv_log_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.strip():
                try:
                    inv_log.append(json.loads(raw))
                except Exception:
                    pass

    if inv_log:
        lines.append(f"\n⏱  Invocation Timeline")
        for inv in inv_log:
            role = inv.get("role", "?")
            phase = inv.get("phase", "")
            verd = inv.get("verdict", "?")
            req_m = inv.get("requestedModel", "?")
            obs_m = inv.get("observedModel", "?")
            inv_id = inv.get("invocationId", "")
            usage_entry = next((b for b in by_inv if b.get("invocationId") == inv_id), {})
            tok_str = f"{_fmt(usage_entry.get('rawTotal'))} tok, {_cost(usage_entry.get('costUsd'))}" if usage_entry else ""
            status_icon = "✅" if verd == "PASS" else "❌"
            lines.append(f"   {status_icon} [{phase}] {role:<22}  {req_m} → {obs_m}  {tok_str}")

    # Totals
    if totals:
        lines.append(f"\n💰 Totals")
        lines.append(f"   Input      : {_fmt(totals.get('input'))}")
        lines.append(f"   Output     : {_fmt(totals.get('output'))}")
        lines.append(f"   Cache Read : {_fmt(totals.get('cacheRead'))}")
        lines.append(f"   Cache Write: {_fmt(totals.get('cacheWrite'))}")
        lines.append(f"   Reasoning  : {_fmt(totals.get('reasoning'))}")
        lines.append(f"   Raw Total  : {_fmt(totals.get('rawTotal'))}")
        lines.append(f"   Total Cost : {_cost(totals.get('costUsd'))}")

    lines.append("\n" + sep)
    return "\n".join(lines)


def _resolve_host(value: str) -> str:
    if value != "auto":
        return value
    import os
    import shutil

    explicit = os.environ.get("PROOFLOOP_HOST")
    if explicit in {"claude-code", "codex", "agy"}:
        return explicit
    signals = [
        ("codex", os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")),
        ("claude-code", os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDECODE")),
        ("agy", os.environ.get("ANTIGRAVITY_SESSION_ID") or os.environ.get("AGY_SESSION_ID")),
    ]
    detected = [host for host, signal in signals if signal]
    if len(detected) == 1:
        return detected[0]
    installed = [host for host, binary in (("codex", "codex"), ("agy", "agy"), ("claude-code", "claude")) if shutil.which(binary)]
    if len(installed) == 1:
        return installed[0]
    raise ValueError("cannot auto-detect host; pass --host or set PROOFLOOP_HOST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proofloop-core")
    sub = parser.add_subparsers(dest="command", required=True)


    p_orchestrate = sub.add_parser("orchestrate")
    p_orchestrate.add_argument("--host", choices=["auto", "claude-code", "codex", "agy"], default="auto")
    p_orchestrate.add_argument("--repo", default=".")
    request_group = p_orchestrate.add_mutually_exclusive_group(required=True)
    request_group.add_argument("--request")
    request_group.add_argument("--request-file")
    p_orchestrate.add_argument("--strategy", choices=["direct", "planned", "high-risk", "analysis"])
    p_orchestrate.add_argument("--timeout-seconds", type=int, default=1200)
    p_orchestrate.add_argument("--output-format", choices=["human", "jsonl", "quiet", "tui"], default="quiet")
    p_orchestrate.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_orchestrate.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p_orchestrate.add_argument("--experimental-domain-packs", action="store_true")

    p_goal = sub.add_parser("goal")
    p_goal.add_argument("--host", choices=["auto", "claude-code", "codex", "agy"], default="auto")
    p_goal.add_argument("--repo", default=".")
    goal_request_group = p_goal.add_mutually_exclusive_group(required=True)
    goal_request_group.add_argument("--request")
    goal_request_group.add_argument("--request-file")
    p_goal.add_argument("--strategy", choices=["direct", "planned", "high-risk"])
    p_goal.add_argument("--timeout-seconds", type=int, default=1200)
    p_goal.add_argument("--max-cycles", type=int, default=8)
    p_goal.add_argument("--max-replans", type=int, default=2)
    p_goal.add_argument("--output-format", choices=["human", "jsonl", "quiet", "tui"], default="human")
    p_goal.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_goal.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p_goal.add_argument("--experimental-domain-packs", action="store_true")

    p_run = sub.add_parser("run")
    p_run.add_argument("--mode", choices=["adaptive", "goal", "audit"], default="adaptive")
    p_run.add_argument("--host", choices=["auto", "claude-code", "codex", "agy"], default="auto")
    p_run.add_argument("--repo", default=".")
    run_request_group = p_run.add_mutually_exclusive_group(required=True)
    run_request_group.add_argument("--request")
    run_request_group.add_argument("--request-file")
    p_run.add_argument("--strategy", choices=["direct", "planned", "high-risk", "analysis"])
    p_run.add_argument("--timeout-seconds", type=int, default=1200)
    p_run.add_argument("--max-cycles", type=int, default=8)
    p_run.add_argument("--max-replans", type=int, default=2)
    p_run.add_argument("--output-format", choices=["human", "jsonl", "quiet", "tui"], default="human")
    p_run.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_run.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p_run.add_argument("--skills", choices=["enabled", "disabled"], default="enabled")
    p_run.add_argument("--experimental-domain-packs", action="store_true")
    p_run.add_argument("--watch", action="store_true")

    p_watch = sub.add_parser("watch")
    watch_source = p_watch.add_mutually_exclusive_group(required=True)
    watch_source.add_argument("--run")
    watch_source.add_argument("--run-dir")
    p_watch.add_argument("--repo", default=".")
    p_watch.add_argument("--format", choices=["human", "jsonl", "tui"], default="human")
    p_watch.add_argument("--verbosity", choices=["info", "verbose", "debug"], default="info")
    p_watch.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p_watch.add_argument("--task")
    p_watch.add_argument("--level", choices=["debug", "info", "warning", "error"])
    p_watch.add_argument("--no-follow", action="store_true")
    p_watch.add_argument("--panels", action="store_true")
    p_watch.add_argument("--tab", default="summary")

    p_tui = sub.add_parser("tui")
    tui_source = p_tui.add_mutually_exclusive_group(required=False)
    tui_source.add_argument("--run")
    tui_source.add_argument("--run-dir")
    p_tui.add_argument("--repo", default=".")
    p_tui.add_argument("--tab", default="summary")
    p_tui.add_argument("--no-follow", action="store_true")

    p_relay = sub.add_parser("relay")
    p_relay.add_argument("--relay-dir", required=True)
    p_relay.add_argument("--wait-seconds", type=float, default=3.0)
    p_relay.add_argument("--tui", action="store_true")
    p_relay.add_argument("--tab", default="summary")

    p_usage = sub.add_parser("usage")
    usage_source = p_usage.add_mutually_exclusive_group(required=False)
    usage_source.add_argument("--run")
    usage_source.add_argument("--run-dir")
    p_usage.add_argument("--repo", default=".")
    p_usage.add_argument("--reconcile", action="store_true")
    p_usage.add_argument("--tokscale-binary")
    p_usage.add_argument("--web", action="store_true")

    p_viewer = sub.add_parser("usage-viewer")
    p_viewer.add_argument("--repo", default=".")
    p_viewer.add_argument("--port", type=int, default=8400)
    p_viewer.add_argument("--no-browser", action="store_true")

    p_benchmark = sub.add_parser("benchmark")
    p_benchmark.add_argument("--suite")
    p_benchmark.add_argument("--repo", default=".")
    p_benchmark.add_argument("--mode", choices=["routing", "system", "both"], default="both")
    p_benchmark.add_argument("--repetitions", type=int, default=5)
    p_benchmark.add_argument("--baseline-host", choices=["claude-code", "codex", "agy"])
    p_benchmark.add_argument("--baseline-model")
    p_benchmark.add_argument("--proofloop-host", choices=["auto", "claude-code", "codex", "agy"], default="auto")
    p_benchmark.add_argument("--timeout-seconds", type=int, default=1200)
    p_benchmark.add_argument("--seed", type=int, default=0)
    p_benchmark.add_argument("--policy", choices=["core", "adaptive", "full", "both", "all"], default="both")
    p_benchmark.add_argument("--environment", choices=["local", "swe-skills"], default="local")
    p_benchmark.add_argument("--swe-upstream")
    p_benchmark.add_argument("--docker-binary", default="docker")
    p_benchmark.add_argument("--include-official-skill", action="store_true")
    p_benchmark.add_argument("--dry-run", action="store_true")
    p_benchmark.add_argument("--resume")
    p_benchmark.add_argument("--only", action="append")

    p_swe_preflight = sub.add_parser("swe-preflight")
    p_swe_preflight.add_argument("--suite", required=True)
    p_swe_preflight.add_argument("--upstream", required=True)
    p_swe_preflight.add_argument("--docker-binary", default="docker")
    p_swe_preflight.add_argument("--pull-images", action="store_true")

    p_swe_import = sub.add_parser("import-swe-bench")
    p_swe_import.add_argument("--upstream", required=True)
    p_swe_import.add_argument(
        "--catalog",
        default=str(Path(__file__).resolve().parents[1] / "benchmarks" / "swe-skills-bench" / "catalog.json"),
    )
    p_swe_import.add_argument("--domain", action="append", choices=list(REQUIRED_DOMAINS))
    p_swe_import.add_argument("--output", required=True)

    p_swe_inspect = sub.add_parser("inspect-swe-bench")
    p_swe_inspect.add_argument("--suite", required=True)

    p_compare = sub.add_parser("compare")
    p_compare.add_argument("--benchmark-dir", required=True)

    p_qualify = sub.add_parser("qualify-skills")
    p_qualify.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1] / "proofloop_domain_packs"),
    )
    p_qualify.add_argument("--pack", action="append")
    p_qualify.add_argument("--external-catalog")
    p_qualify.add_argument("--behavior-repetitions", type=int, default=0)
    p_qualify.add_argument("--seed", type=int, default=0)
    p_qualify.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "reports" / "domain-skill-qualification.json"),
    )

    p_pre = sub.add_parser("preflight")
    p_pre.add_argument("--repo", default=".")
    p_pre.add_argument("--output")

    p_record = sub.add_parser("record-attempt")
    p_record.add_argument("--task", required=True)
    p_record.add_argument("--run-dir", required=True)
    p_record.add_argument("--role", choices=["implementer_fast", "implementer_recovery"], required=True)
    p_record.add_argument("--observed-model")
    p_record.add_argument("--classification", choices=["DESIGN_CONFLICT", "SPEC_AMBIGUITY", "CONTRACT_CHANGE"])

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
    p_host.add_argument("--host", choices=["claude-code", "codex", "agy"], required=True)
    p_host.add_argument("--probe", action="store_true")

    p_invoke = sub.add_parser("invoke-role")
    p_invoke.add_argument("--host", choices=["claude-code", "codex", "agy"], required=True)
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

    p_report = sub.add_parser("report", help="Print a human-readable run report after relay finishes")
    p_report.add_argument("--run-dir", required=True)
    p_report.add_argument("--run", default=None, help="Run ID (alternative to --run-dir)")
    p_report.add_argument("--repo", default=".")

    args = parser.parse_args(argv)
    if args.command == "relay":
        try:
            poll = wait_and_poll_relay(args.relay_dir, wait_seconds=args.wait_seconds)
        except ValueError as exc:
            parser.error(str(exc))
        if getattr(args, "tui", False):
            from proofloop_core.ui.tui import render_relay_tui

            print(render_relay_tui(args.relay_dir, tab=getattr(args, "tab", "summary")))
        else:
            for line in poll.lines:
                print(line)
        print("PROOFLOOP_RELAY_ACTIVE" if poll.active else "PROOFLOOP_RELAY_FINISHED")
        return 0
    if args.command == "tui":
        from proofloop_core.ui.tui import watch_tui

        selected = resolve_run_dir(repo=args.repo, run=args.run, run_dir=args.run_dir)
        try:
            watch_tui(
                selected,
                stream=sys.stdout,
                tab=getattr(args, "tab", "summary"),
                follow=not args.no_follow,
            )
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "watch":
        selected = resolve_run_dir(repo=args.repo, run=args.run, run_dir=args.run_dir)
        if args.format == "tui":
            from proofloop_core.ui.tui import watch_tui

            try:
                watch_tui(
                    selected,
                    stream=sys.stdout,
                    tab=getattr(args, "tab", "summary"),
                    follow=not args.no_follow,
                )
            except KeyboardInterrupt:
                pass
            return 0
        event_bus = None
        if args.panels:
            event_bus = EventBus()
            panels = WatchPanels()
            event_bus.subscribe(panels.consume)
            panel_stream = sys.stderr if args.format == "jsonl" else sys.stdout

            def render_panels(_: object) -> None:
                panel_stream.write(render_watch_panels(panels) + "\n")
                panel_stream.flush()

            event_bus.subscribe(render_panels)
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
                event_bus=event_bus,
            )
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "qualify-skills":
        result = qualify_domain_packs(
            args.root,
            only=tuple(args.pack or ()),
            external_catalog=args.external_catalog,
        )
        if args.behavior_repetitions:
            result["behaviorBenchmark"] = build_behavior_trial_schedule(
                result,
                repetitions=args.behavior_repetitions,
                seed=args.seed,
            )
        output = Path(args.output).resolve()
        write_json(output, result)
        _print({"status": result["status"], "report": str(output), "qualificationHash": result["qualificationHash"]})
        return 0 if result["status"] == "READY_FOR_BEHAVIOR_EVAL" else 2
    if args.command == "usage-viewer" or (args.command == "usage" and getattr(args, "web", False)):
        from proofloop_core.analysis.usage_viewer import start_usage_viewer

        return start_usage_viewer(
            repo_root=args.repo,
            port=getattr(args, "port", 8400),
            open_browser=not getattr(args, "no_browser", False),
            block=True,
        )
    if args.command == "usage":
        if not args.run and not args.run_dir:
            parser.error("usage command requires --run, --run-dir, or --web")
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
        if args.resume:
            result = resume_benchmark(args.resume, timeout_seconds=args.timeout_seconds)
            _print(result)
            return 0
        if not args.suite or not args.baseline_host or not args.baseline_model:
            parser.error("benchmark requires --suite, --baseline-host, and --baseline-model unless --resume is used")
        policies = (
            ("core", "adaptive", "full")
            if args.policy == "all"
            else ("adaptive", "full")
            if args.policy == "both"
            else (args.policy,)
        )
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
            policies=policies,
            include_official_skill=args.include_official_skill,
            dry_run=args.dry_run,
            environment=args.environment,
            swe_upstream=args.swe_upstream,
            docker_binary=args.docker_binary,
            only_task_ids=tuple(args.only or ()),
        )
        _print(result)
        return 0
    if args.command == "swe-preflight":
        result = preflight_swe_environment(
            read_json(args.suite),
            args.upstream,
            docker_binary=args.docker_binary,
            pull_images=args.pull_images,
        )
        _print(result)
        return 0 if result["status"] == "READY" else 2
    if args.command == "import-swe-bench":
        result = build_swe_suite(
            args.upstream,
            args.catalog,
            domains=tuple(args.domain or REQUIRED_DOMAINS),
        )
        write_json(args.output, result)
        _print({"suite": str(Path(args.output).resolve()), "inspection": inspect_swe_suite(result)})
        return 0
    if args.command == "inspect-swe-bench":
        result = inspect_swe_suite(read_json(args.suite))
        _print(result)
        return 0 if result["status"] == "READY" else 2
    if args.command == "compare":
        result = compare_benchmark(args.benchmark_dir)
        _print(result)
        return 0
    if args.command in {"orchestrate", "goal", "run"}:
        host = _resolve_host(args.host)
        request = args.request
        if args.request_file:
            request = Path(args.request_file).read_text(encoding="utf-8")
        strategy_map = {"direct": "DIRECT_VERIFIED_CHANGE", "planned": "PLANNED_IMPLEMENTATION", "high-risk": "HIGH_RISK_ENGINEERING", "analysis": "REPOSITORY_ANALYSIS"}
        runner = run_proofloop if args.command == "run" else converge_goal if args.command == "goal" else orchestrate
        extra = {
            "max_goal_cycles": args.max_cycles,
            "max_replans": args.max_replans,
        } if args.command in {"goal", "run"} else {}
        if args.command == "run":
            extra["mode"] = args.mode
            extra["skills_enabled"] = args.skills == "enabled"
            if args.watch:
                event_bus = EventBus()
                panels = WatchPanels()
                event_bus.subscribe(panels.consume)
                panel_stream = sys.stderr if args.output_format == "jsonl" else sys.stdout

                def render_panels(_: object) -> None:
                    panel_stream.write(render_watch_panels(panels) + "\n")
                    panel_stream.flush()

                event_bus.subscribe(render_panels)
                extra["event_bus"] = event_bus
        result = runner(
            host,
            args.repo,
            request or "",
            strategy_override=strategy_map.get(args.strategy),
            timeout_seconds=args.timeout_seconds,
            output_format=args.output_format,
            verbosity=args.verbosity,
            color=args.color,
            experimental_domain_packs=args.experimental_domain_packs,
            **extra,
        )
    elif args.command == "host-capabilities":
        result = probe(args.host) if args.probe else capability(args.host)
    elif args.command == "report":
        run_dir = args.run_dir
        if not run_dir and args.run:
            repo_path = Path(getattr(args, 'repo', '.')).resolve()
            run_dir = str(repo_path / ".proofloop" / "runs" / args.run)
        print(_render_run_report(Path(run_dir)))
        return 0
    elif args.command == "invoke-role":
        result = invoke_role(args.host, args.role, args.repo, args.run_dir, args.prompt, args.task, args.binary, args.timeout_seconds)
    elif args.command == "record-attempt":
        result = record_attempt(args.task, args.run_dir, args.role, args.observed_model, args.classification)
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
    if (
        args.command not in {"orchestrate", "goal"}
        or args.output_format == "quiet"
    ) and not (args.command == "run" and args.watch and args.output_format == "jsonl"):
        _print(result)
    if args.command in {"orchestrate", "goal"}:
        return 0 if result.get("verdict") == "PROVEN" else 2
    return 0 if result.get("verdict") not in {"FAIL", "FAILED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
