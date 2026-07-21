from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .events import EventBus, ProofLoopEvent


class ProofLoopTUI:
    """Core state projection and screen rendering engine for the ProofLoop TUI.

    Implements the layout and tab specifications from architecture section 20.7
    (TUI 화면), 20.8 (TUI 상세 탭), and 20.9 (Prompt Inspector).
    """

    def __init__(self, run_id: str = "unknown") -> None:
        self.run_id = run_id
        self.status = "PENDING"
        self.request = "No request recorded"
        self.intent_kind = "UNKNOWN"
        self.authority_level = "REPOSITORY_READ"
        self.tier = "T1"
        self.host = "auto"
        self.strategy = "direct"
        self.start_time = time.time()
        self.active_role: dict[str, Any] = {}
        self.roles: dict[str, dict[str, Any]] = {}
        self.timeline: list[dict[str, str]] = []
        self.proof: dict[str, Any] = {
            "closureRatio": 0.0,
            "satisfied": ["request fidelity", "authority preserved"],
            "open": ["focused tests", "public contract unchanged", "surface scenario", "independent review"],
            "failed": [],
        }
        self.budget: dict[str, Any] = {
            "consumedTokens": 0,
            "maxTokens": 120000,
            "remainingTokens": 120000,
            "retries": 0,
            "maxRetries": 2,
            "rawTotal": 0,
            "tokenCoverageRatio": 1.0,
        }
        self.prompts: list[dict[str, Any]] = []
        self.files: dict[str, str] = {}
        self.diff_metrics: dict[str, Any] = {}
        self.commands: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.current_tab = "summary"

    def consume(self, event: ProofLoopEvent) -> None:
        data = event.payload
        t_str = self._format_timestamp(event.timestamp)

        if event.event_type == "run.created":
            self.run_id = event.run_id or self.run_id
            if data.get("request"):
                self.request = str(data["request"])
            if data.get("host"):
                self.host = str(data["host"])
        elif event.event_type == "run.started":
            self.status = "RUNNING"
            self.run_id = event.run_id or self.run_id
            if data.get("request"):
                self.request = str(data["request"])
            if data.get("host"):
                self.host = str(data["host"])
        elif event.event_type == "run.completed":
            self.status = str(data.get("verdict") or "COMPLETED")
            self._add_timeline(t_str, f"run completed: {self.status}")
        elif event.event_type == "run.failed":
            self.status = "FAILED"
            self._add_timeline(t_str, f"run failed: {event.summary}")
            self.errors.append({"timestamp": t_str, "type": "run.failed", "message": event.summary})
        elif event.event_type == "run.blocked":
            self.status = "BLOCKED"
            self._add_timeline(t_str, f"run blocked: {event.summary}")
            self.errors.append({"timestamp": t_str, "type": "run.blocked", "message": event.summary})
        elif event.event_type == "request.received":
            if data.get("rawText"):
                self.request = str(data["rawText"])
            if data.get("invocationSource"):
                self.host = str(data["invocationSource"])
            if data.get("explicitAuthority"):
                self.authority_level = str(data["explicitAuthority"])
            self._add_timeline(t_str, f"authority detected: {self.authority_level}")
        elif event.event_type == "intent_gate.completed":
            if data.get("intentKind"):
                self.intent_kind = str(data["intentKind"])
            if data.get("authorityLevel"):
                self.authority_level = str(data["authorityLevel"])
            self._add_timeline(t_str, f"intent classified: {self.intent_kind}")
        elif event.event_type == "workload.classified":
            if data.get("tier"):
                self.tier = str(data["tier"])
            self._add_timeline(t_str, f"workload classified: {self.tier}")
        elif event.event_type == "strategy.selected":
            if data.get("tier"):
                self.tier = str(data["tier"])
            if data.get("strategy"):
                self.strategy = str(data["strategy"])
            self._add_timeline(t_str, f"strategy selected: {self.strategy}")
        elif event.event_type == "role.started":
            role_name = str(data.get("role") or event.role or "unknown")
            model = str(data.get("requestedModel") or data.get("observedModel") or event.model or "unknown-model")
            attempt = data.get("attempt", 1)
            task = str(data.get("taskId") or event.task_id or event.summary or f"{role_name} task")
            self.active_role = {
                "role": role_name,
                "model": model,
                "task": task,
                "attempt": attempt,
                "started_at": time.time(),
                "status": "RUNNING",
            }
            self.roles[role_name] = dict(self.active_role)
            self._add_timeline(t_str, f"started role: {role_name} ({model})")
        elif event.event_type in {"role.model_observed", "model.changed"}:
            role_name = str(data.get("role") or event.role or "unknown")
            model = str(data.get("observedModel") or event.model or "unknown-model")
            if self.active_role.get("role") == role_name:
                self.active_role["model"] = model
            if role_name in self.roles:
                self.roles[role_name]["model"] = model
        elif event.event_type == "role.progress":
            role_name = str(data.get("role") or event.role or "unknown")
            elapsed = data.get("elapsedSeconds", 0)
            if self.active_role.get("role") == role_name:
                self.active_role["elapsedSeconds"] = elapsed
        elif event.event_type == "role.completed":
            role_name = str(data.get("role") or event.role or "unknown")
            if self.active_role.get("role") == role_name:
                self.active_role["status"] = "COMPLETED"
            if role_name in self.roles:
                self.roles[role_name]["status"] = "COMPLETED"
            self._add_timeline(t_str, f"completed role: {role_name}")
        elif event.event_type in {"role.failed", "role.cancelled"}:
            role_name = str(data.get("role") or event.role or "unknown")
            if self.active_role.get("role") == role_name:
                self.active_role["status"] = "FAILED"
            if role_name in self.roles:
                self.roles[role_name]["status"] = "FAILED"
            self._add_timeline(t_str, f"failed role: {role_name}")
            self.errors.append({"timestamp": t_str, "type": event.event_type, "message": event.summary})
        elif event.event_type == "role_prompt.rendered":
            prompt_entry = {
                "irVersion": data.get("irVersion", "v1"),
                "renderer": data.get("renderer", "default"),
                "role": data.get("role") or event.role or "unknown",
                "promptHash": data.get("promptHash", "sha256:unknown"),
                "dispatchedAt": t_str,
                "promptText": str(data.get("promptText") or ""),
                "removedContext": data.get("removedContext", []),
                "appliedSkillSlice": data.get("appliedSkillSlice", []),
            }
            self.prompts.append(prompt_entry)
            if self.active_role.get("role") == prompt_entry["role"]:
                self.active_role["model"] = str(data.get("model") or self.active_role.get("model"))
        elif event.event_type in {"grounding.file_read", "file.read"}:
            file_path = str(data.get("path") or data.get("file") or event.summary)
            self.files[file_path] = "read"
            self._add_timeline(t_str, f"read {file_path}")
        elif event.event_type == "file.changed":
            file_path = str(data.get("path") or data.get("file") or event.summary)
            self.files[file_path] = "changed"
            self._add_timeline(t_str, f"changed {file_path}")
        elif event.event_type == "diff_guard.completed":
            self.diff_metrics = dict(data.get("metrics") or {})
            verdict = data.get("verdict", "UNKNOWN")
            self._add_timeline(t_str, f"diff guard: {verdict}")
        elif event.event_type == "check.completed":
            cmd = " ".join(str(p) for p in data.get("command", []))
            self.commands.append({"timestamp": t_str, "command": cmd, "verdict": "PASSED", "output": data.get("outputTail", [])})
            self._add_timeline(t_str, f"{cmd} PASSED")
        elif event.event_type == "check.failed":
            cmd = " ".join(str(p) for p in data.get("command", []))
            self.commands.append({"timestamp": t_str, "command": cmd, "verdict": "FAILED", "output": data.get("outputTail", [])})
            self._add_timeline(t_str, f"{cmd} FAILED")
            self.errors.append({"timestamp": t_str, "type": "check.failed", "message": f"{cmd} failed"})
        elif event.event_type == "failure.fingerprinted":
            fingerprint = str(data.get("fingerprint") or event.summary)
            self._add_timeline(t_str, f"failure fingerprint: {fingerprint}")
            self.errors.append({"timestamp": t_str, "type": "fingerprint", "message": fingerprint})
        elif event.event_type == "recovery.started":
            self._add_timeline(t_str, "recovery route selected")
            self.budget["retries"] = self.budget.get("retries", 0) + 1
        elif event.event_type == "evidence.collected":
            self.evidence.append({"timestamp": t_str, "type": data.get("type", "unknown"), "evidenceLevel": data.get("evidenceLevel", "verified"), "refs": event.artifact_refs})
            self._add_timeline(t_str, f"evidence collected: {data.get('type')}")
        elif event.event_type == "proof.updated":
            ratio = data.get("closureRatio")
            if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
                self.proof["closureRatio"] = ratio
            if isinstance(data.get("open"), list):
                self.proof["open"] = [str(item) for item in data["open"]]
            if isinstance(data.get("satisfied"), list):
                self.proof["satisfied"] = [str(item) for item in data["satisfied"]]
            if isinstance(data.get("failed"), list):
                self.proof["failed"] = [str(item) for item in data["failed"]]
        elif event.event_type == "budget.updated":
            for field in ("consumedTokens", "remainingTokens", "maxTokens"):
                val = data.get(field)
                if isinstance(val, int) and not isinstance(val, bool):
                    self.budget[field] = val
        elif event.event_type == "usage.finalized":
            summary = data.get("summary")
            if isinstance(summary, dict):
                totals = summary.get("totals")
                if isinstance(totals, dict) and isinstance(totals.get("rawTotal"), int):
                    self.budget["rawTotal"] = totals["rawTotal"]
                    self.budget["consumedTokens"] = totals["rawTotal"]
                coverage = summary.get("coverage")
                if isinstance(coverage, dict) and isinstance(coverage.get("tokenCoverageRatio"), (int, float)):
                    self.budget["tokenCoverageRatio"] = coverage["tokenCoverageRatio"]

    def _add_timeline(self, timestamp_str: str, message: str) -> None:
        self.timeline.append({"time": timestamp_str, "message": message})
        if len(self.timeline) > 50:
            self.timeline = self.timeline[-50:]

    def _format_timestamp(self, ts: str) -> str:
        try:
            if "T" in ts:
                time_part = ts.split("T", 1)[1]
                return time_part[:5]
            return ts[:5]
        except Exception:
            return "00:00"

    def snapshot(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "status": self.status,
            "request": self.request,
            "intentKind": self.intent_kind,
            "authorityLevel": self.authority_level,
            "tier": self.tier,
            "host": self.host,
            "strategy": self.strategy,
            "activeRole": dict(self.active_role),
            "roles": {k: dict(v) for k, v in self.roles.items()},
            "timeline": list(self.timeline),
            "proof": dict(self.proof),
            "budget": dict(self.budget),
            "prompts": list(self.prompts),
            "files": dict(self.files),
            "diffMetrics": dict(self.diff_metrics),
            "commands": list(self.commands),
            "evidence": list(self.evidence),
            "errors": list(self.errors),
        }

    def render_tui_screen(self, width: int = 68) -> str:
        inner_width = max(40, width - 2)
        lines = [self._header("ProofLoop Run", width)]
        lines.append(self._row("Run", self.run_id, inner_width))
        lines.append(self._row("Request", self._truncate(self.request, inner_width - 11), inner_width))
        lines.append(self._row("Intent", f"{self.intent_kind} · {self.authority_level}", inner_width))
        lines.append(self._row("Tier", self.tier, inner_width))
        lines.append(self._row("Host", self.host, inner_width))
        lines.append(self._row("Strategy", self.strategy, inner_width))
        lines.append(self._row("Status", self.status, inner_width))

        lines.append(self._divider("Active Role", width))
        if self.active_role:
            role_text = f"{self.active_role.get('role', 'unknown')} · {self.active_role.get('model', 'unknown')}"
            lines.append(self._line(role_text, inner_width))
            task_text = f"Task: {self._truncate(str(self.active_role.get('task', '')), inner_width - 8)}"
            lines.append(self._line(task_text, inner_width))
            elapsed = int(time.time() - self.active_role.get("started_at", self.start_time))
            elapsed_str = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
            attempt_text = f"Elapsed {elapsed_str} · Attempt {self.active_role.get('attempt', 1)}/{self.budget.get('maxRetries', 2)}"
            lines.append(self._line(attempt_text, inner_width))
        else:
            lines.append(self._line("none active", inner_width))

        lines.append(self._divider("Timeline", width))
        recent_timeline = self.timeline[-7:] if self.timeline else []
        if recent_timeline:
            for item in recent_timeline:
                t_msg = f"{item['time']} {item['message']}"
                lines.append(self._line(self._truncate(t_msg, inner_width), inner_width))
        else:
            lines.append(self._line("no timeline events yet", inner_width))

        lines.append(self._divider("Proof Obligations", width))
        satisfied = self.proof.get("satisfied", [])
        failed = self.proof.get("failed", [])
        open_obs = self.proof.get("open", [])
        if satisfied or failed or open_obs:
            for item in satisfied[:4]:
                lines.append(self._line(f"✓ {self._truncate(item, inner_width - 3)}", inner_width))
            for item in failed[:2]:
                lines.append(self._line(f"✗ {self._truncate(item, inner_width - 3)}", inner_width))
            for item in open_obs[:3]:
                lines.append(self._line(f"○ {self._truncate(item, inner_width - 3)}", inner_width))
        else:
            lines.append(self._line("none recorded", inner_width))

        lines.append(self._divider("Budget", width))
        tokens_consumed = self.budget.get("consumedTokens", 0)
        tokens_max = self.budget.get("maxTokens", 120000)
        retries = self.budget.get("retries", 0)
        retries_max = self.budget.get("maxRetries", 2)
        total_elapsed = int(time.time() - self.start_time)
        t_str = f"{total_elapsed // 60:02d}:{total_elapsed % 60:02d}"
        budget_line = f"Tokens {tokens_consumed:,} / {tokens_max:,} · Retries {retries} / {retries_max} · Time {t_str}"
        lines.append(self._line(self._truncate(budget_line, inner_width), inner_width))
        lines.append(self._footer(width))
        return "\n".join(lines)

    def render_tab(self, tab_name: str, width: int = 68) -> str:
        tab = tab_name.lower()
        if tab in {"summary", "1"}:
            return self.render_tui_screen(width)

        inner_width = max(40, width - 2)
        lines = [self._header(f"ProofLoop TUI Tab: {tab_name.upper()}", width)]

        if tab in {"timeline", "2"}:
            if not self.timeline:
                lines.append(self._line("no timeline events recorded", inner_width))
            else:
                for item in self.timeline[-20:]:
                    t_msg = f"{item['time']} {item['message']}"
                    lines.append(self._line(self._truncate(t_msg, inner_width), inner_width))
        elif tab in {"roles", "3"}:
            if not self.roles:
                lines.append(self._line("no roles executed yet", inner_width))
            else:
                for rname, rdata in self.roles.items():
                    r_line = f"{rname}: {rdata.get('status')} · {rdata.get('model')} (attempt {rdata.get('attempt')})"
                    lines.append(self._line(self._truncate(r_line, inner_width), inner_width))
        elif tab in {"prompts", "4"}:
            if not self.prompts:
                lines.append(self._line("no prompts compiled yet", inner_width))
            else:
                latest = self.prompts[-1]
                lines.append(self._row("Prompt IR", str(latest.get("irVersion")), inner_width))
                lines.append(self._row("Renderer", str(latest.get("renderer")), inner_width))
                lines.append(self._row("Role", str(latest.get("role")), inner_width))
                lines.append(self._row("Hash", str(latest.get("promptHash")), inner_width))
                lines.append(self._row("Dispatched", str(latest.get("dispatchedAt")), inner_width))
                lines.append(self._divider("Prompt Preview", width))
                p_lines = str(latest.get("promptText", "")).splitlines()[:8]
                for pl in p_lines:
                    lines.append(self._line(self._truncate(pl, inner_width), inner_width))
        elif tab in {"files", "5"}:
            if not self.files:
                lines.append(self._line("no file operations observed", inner_width))
            else:
                for fpath, faction in self.files.items():
                    lines.append(self._line(self._truncate(f"{fpath}: {faction}", inner_width), inner_width))
        elif tab in {"diff", "6"}:
            if not self.diff_metrics:
                lines.append(self._line("no diff guard metrics recorded", inner_width))
            else:
                lines.append(self._line(f"Metrics: {json.dumps(self.diff_metrics, ensure_ascii=False)}", inner_width))
        elif tab in {"commands", "7"}:
            if not self.commands:
                lines.append(self._line("no verification checks executed", inner_width))
            else:
                for cmd_item in self.commands[-10:]:
                    c_line = f"[{cmd_item['verdict']}] {cmd_item['command']}"
                    lines.append(self._line(self._truncate(c_line, inner_width), inner_width))
        elif tab in {"evidence", "8"}:
            if not self.evidence:
                lines.append(self._line("no evidence items collected", inner_width))
            else:
                for ev in self.evidence[-10:]:
                    e_line = f"{ev['type']} ({ev['evidenceLevel']})"
                    lines.append(self._line(self._truncate(e_line, inner_width), inner_width))
        elif tab in {"proof", "9"}:
            ratio_str = f"{self.proof.get('closureRatio', 0.0):.0%}"
            lines.append(self._row("Closure", ratio_str, inner_width))
            lines.append(self._divider("Satisfied", width))
            for item in self.proof.get("satisfied", []):
                lines.append(self._line(f"✓ {item}", inner_width))
            lines.append(self._divider("Open Obligations", width))
            for item in self.proof.get("open", []):
                lines.append(self._line(f"○ {item}", inner_width))
        elif tab in {"budget", "0"}:
            lines.append(self._row("Consumed", f"{self.budget.get('consumedTokens', 0):,}", inner_width))
            lines.append(self._row("Remaining", f"{self.budget.get('remainingTokens', 0):,}", inner_width))
            lines.append(self._row("Max Tokens", f"{self.budget.get('maxTokens', 0):,}", inner_width))
            lines.append(self._row("Raw Total", f"{self.budget.get('rawTotal', 0):,}", inner_width))
            lines.append(self._row("Coverage", f"{self.budget.get('tokenCoverageRatio', 1.0):.2f}", inner_width))
        elif tab in {"errors", "e"}:
            if not self.errors:
                lines.append(self._line("no errors or failures recorded", inner_width))
            else:
                for err in self.errors[-10:]:
                    e_line = f"[{err['type']}] {err['message']}"
                    lines.append(self._line(self._truncate(e_line, inner_width), inner_width))
        else:
            lines.append(self._line(f"unknown tab: {tab_name}", inner_width))

        lines.append(self._footer(width))
        return "\n".join(lines)

    def _header(self, title: str, width: int) -> str:
        prefix = f"┌─ {title} "
        remaining = max(0, width - len(prefix) - 1)
        return f"{prefix}{'─' * remaining}┐"

    def _divider(self, title: str, width: int) -> str:
        prefix = f"├─ {title} "
        remaining = max(0, width - len(prefix) - 1)
        return f"{prefix}{'─' * remaining}┤"

    def _footer(self, width: int) -> str:
        return f"└{'─' * (width - 2)}┘"

    def _line(self, text: str, inner_width: int) -> str:
        padded = text[:inner_width].ljust(inner_width)
        return f"│ {padded} │"

    def _row(self, label: str, value: str, inner_width: int) -> str:
        prefix = f"{label:<10}"
        val_width = max(0, inner_width - 10)
        truncated_val = self._truncate(str(value), val_width)
        return self._line(f"{prefix}{truncated_val}", inner_width)

    def _truncate(self, text: str, max_len: int) -> str:
        if max_len <= 0:
            return ""
        if len(text) <= max_len:
            return text
        if max_len <= 3:
            return text[:max_len]
        return text[: max_len - 1] + "…"


class TuiRenderer:
    """Renderer implementation that formats ProofLoop events into the TUI layout."""

    def __init__(self, stream: TextIO, *, tui: ProofLoopTUI | None = None, tab: str = "summary") -> None:
        self.stream = stream
        self.tui = tui if tui is not None else ProofLoopTUI()
        self.tab = tab
        self.is_tty = getattr(stream, "isatty", lambda: False)()

    def render(self, event: dict[str, Any]) -> None:
        typed = ProofLoopEvent.from_v1_dict(event)
        self.tui.consume(typed)
        # In non-tty / stream environments, only render on key lifecycle milestones
        # so logs remain clean and unflooded while still providing exact TUI snapshots.
        event_type = str(event.get("type") or "")
        milestones = {
            "run.started",
            "role.started",
            "role.completed",
            "role.failed",
            "check.completed",
            "check.failed",
            "recovery.started",
            "proof.updated",
            "run.completed",
            "run.failed",
            "run.blocked",
        }
        if self.is_tty:
            output = self.tui.render_tab(self.tab)
            self.stream.write("\x1b[2J\x1b[H" + output + "\n")
            self.stream.flush()
        elif event_type in milestones:
            output = self.tui.render_tab(self.tab)
            self.stream.write(output + "\n")
            self.stream.flush()


def watch_tui(
    run_dir: str | Path,
    *,
    stream: TextIO,
    tab: str = "summary",
    follow: bool = True,
    poll_interval: float = 0.1,
    bus: EventBus | None = None,
) -> int:
    """Connects the ProofLoopTUI engine to an active or completed run directory."""
    from .watch import watch_events

    tui = ProofLoopTUI()
    renderer = TuiRenderer(stream, tui=tui, tab=tab)
    event_bus = bus if bus is not None else EventBus()
    event_bus.subscribe(tui.consume)

    return watch_events(
        run_dir,
        stream=stream,
        output_format="tui",
        follow=follow,
        poll_interval=poll_interval,
        event_bus=event_bus,
    )


def render_relay_tui(relay_dir: str | Path, tab: str = "summary") -> str:
    """Finds the run associated with a relay directory and returns its current TUI snapshot."""
    root = Path(relay_dir).expanduser().resolve().parent.parent
    tui = ProofLoopTUI()
    active_json = root / "active-run.json"
    run_dir = None
    if active_json.is_file():
        try:
            data = json.loads(active_json.read_text(encoding="utf-8"))
            if data.get("runDir"):
                run_dir = Path(data["runDir"])
            elif data.get("runId"):
                run_dir = root / "runs" / str(data["runId"])
        except Exception:
            pass
    if run_dir is None or not (run_dir / "events.jsonl").is_file():
        runs_dir = root / "runs"
        if runs_dir.is_dir():
            candidates = sorted(
                [p for p in runs_dir.iterdir() if p.is_dir() and (p / "events.jsonl").is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                run_dir = candidates[0]
    if run_dir and (run_dir / "events.jsonl").is_file():
        text = (run_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                try:
                    ev = ProofLoopEvent.from_v1_dict(json.loads(line))
                    tui.consume(ev)
                except Exception:
                    continue
    return tui.render_tab(tab)
