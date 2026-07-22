#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for candidate in (Path.home() / ".proofloop" / "runtime", PLUGIN_ROOT):
    if str(candidate) in sys.path:
        sys.path.remove(str(candidate))
    sys.path.insert(0, str(candidate))

from proofloop_core.runtimes.hosts import detect_model, parse_codex_transcript, role_from_agent_type
from proofloop_core.context.io import write_json
from proofloop_core.contracts.run_state import load_active_run
from proofloop_core.context.trace import summarize_trace


def _append_event(run_dir: Path, event: dict[str, object]) -> None:
    trace = run_dir / "model-trace.jsonl"
    with trace.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    summary = summarize_trace(trace)
    summary["host"] = event.get("host")
    summary["capabilityMode"] = "NATIVE_MODEL_ROUTING"
    write_json(run_dir / "model-trace-summary.json", summary)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", choices=["claude-code", "codex"], default="codex")
    args, _ = parser.parse_known_args()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    active = load_active_run(payload.get("cwd", "."))
    if not active:
        return 0
    run_dir = Path(active["runDir"])
    if args.host == "claude-code":
        if payload.get("tool_name") != "Agent":
            return 0
        tool_input = payload.get("tool_input") or {}
        response = payload.get("tool_response") or {}
        event = {
            "timestampEpoch": time.time(),
            "host": "claude-code",
            "role": role_from_agent_type(tool_input.get("subagent_type")) or tool_input.get("subagent_type"),
            "expectedModel": tool_input.get("model"),
            "observedModel": response.get("resolvedModel"),
            "agentId": response.get("agentId"),
            "status": response.get("status"),
            "totalTokens": response.get("totalTokens"),
            "totalDurationMs": response.get("totalDurationMs"),
            "toolUseId": payload.get("tool_use_id"),
        }
    else:
        agent_type = payload.get("agent_type")
        transcript = parse_codex_transcript(payload.get("agent_transcript_path"))
        observed = transcript.get("observedModel") or payload.get("model") or detect_model(payload)
        event = {
            "timestampEpoch": time.time(),
            "host": "codex",
            "role": role_from_agent_type(agent_type) or agent_type,
            "expectedModel": None,
            "observedModel": observed,
            "agentId": payload.get("agent_id"),
            "agentType": agent_type,
            "turnId": payload.get("turn_id"),
            "sessionId": payload.get("session_id"),
            "transcriptPath": payload.get("agent_transcript_path"),
            "transcriptEventCount": transcript.get("eventCount"),
            "status": "stopped",
        }
    _append_event(run_dir, event)
    # Codex SubagentStop requires JSON or no stdout; {} is valid and explicit.
    if args.host == "codex":
        print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
