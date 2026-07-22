from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TextIO

from proofloop_core.context.events import EventBus, ProofLoopEvent, validate_event
from proofloop_core.renderers import build_renderer


_LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3}


class WatchPanels:
    """Read-only panel projection fed exclusively by typed EventBus events.

    The projection deliberately owns no artifact paths and never reads a run
    directory. ``watch_events`` remains the replay adapter for persisted v1
    events; a live run subscribes this object directly to its EventBus.
    """

    def __init__(self) -> None:
        self._status = "PENDING"
        self._tier: str | None = None
        self._strategy: str | None = None
        self._roles: dict[str, dict[str, Any]] = {}
        self._proof: dict[str, Any] = {"closureRatio": None, "open": []}
        self._budget: dict[str, Any] = {
            "consumedTokens": 0,
            "remainingTokens": None,
            "maxTokens": None,
            "tokenCoverageRatio": None,
        }

    def consume(self, event: ProofLoopEvent) -> None:
        data = event.payload
        if event.event_type == "run.started":
            self._status = "RUNNING"
        elif event.event_type == "run.completed":
            self._status = str(data.get("verdict") or "COMPLETED")
        elif event.event_type == "run.failed":
            self._status = "FAILED"
        elif event.event_type == "run.blocked":
            self._status = "BLOCKED"
        elif event.event_type == "strategy.selected":
            tier = data.get("tier")
            strategy = data.get("strategy")
            self._tier = str(tier) if isinstance(tier, str) else self._tier
            self._strategy = str(strategy) if isinstance(strategy, str) else self._strategy
        elif event.event_type == "role.started":
            self._update_role(event, "RUNNING")
        elif event.event_type == "role.completed":
            self._update_role(event, "COMPLETED")
        elif event.event_type in {"role.failed", "role.cancelled"}:
            self._update_role(event, "FAILED")
        elif event.event_type in {"role.model_observed", "model.changed"}:
            self._update_role(event, None)
        elif event.event_type == "proof.updated":
            ratio = data.get("closureRatio")
            if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
                self._proof["closureRatio"] = ratio
            open_obligations = data.get("open")
            if isinstance(open_obligations, list) and all(isinstance(item, str) for item in open_obligations):
                self._proof["open"] = list(open_obligations)
        elif event.event_type == "budget.updated":
            self._update_budget(data)
        elif event.event_type == "usage.finalized":
            self._update_final_usage(data)

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "tier": self._tier,
            "strategy": self._strategy,
            "roles": {role: dict(self._roles[role]) for role in sorted(self._roles)},
            "proof": {"closureRatio": self._proof["closureRatio"], "open": list(self._proof["open"])},
            "budget": dict(self._budget),
        }

    def _update_role(self, event: ProofLoopEvent, status: str | None) -> None:
        data = event.payload
        role_value = data.get("role") or event.role
        if not isinstance(role_value, str) or not role_value:
            return
        current = dict(self._roles.get(role_value) or {})
        if status is not None:
            current["status"] = status
        attempt = data.get("attempt")
        if isinstance(attempt, int) and not isinstance(attempt, bool):
            current["attempt"] = attempt
        model = data.get("observedModel") or data.get("activeModel") or data.get("requestedModel") or event.model
        if isinstance(model, str) and model:
            current["model"] = model
        task_id = event.task_id
        if isinstance(task_id, str) and task_id:
            current["taskId"] = task_id
        self._roles[role_value] = current

    def _update_budget(self, data: dict[str, Any]) -> None:
        for field in ("consumedTokens", "remainingTokens", "maxTokens"):
            value = data.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                self._budget[field] = value

    def _update_final_usage(self, data: dict[str, Any]) -> None:
        summary = data.get("summary")
        if not isinstance(summary, dict):
            return
        totals = summary.get("totals")
        if isinstance(totals, dict):
            raw_total = totals.get("rawTotal")
            if isinstance(raw_total, int) and not isinstance(raw_total, bool):
                self._budget["consumedTokens"] = raw_total
        coverage = summary.get("coverage")
        if isinstance(coverage, dict):
            ratio = coverage.get("tokenCoverageRatio")
            if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
                self._budget["tokenCoverageRatio"] = ratio


def render_watch_panels(panels: WatchPanels) -> str:
    """Render the current role, proof, and budget projections deterministically."""

    snapshot = panels.snapshot()
    proof = snapshot["proof"]
    budget = snapshot["budget"]
    lines = [
        "[ProofLoop Watch]",
        f"status: {snapshot['status']}",
        f"tier: {snapshot['tier'] or 'unknown'} · strategy: {snapshot['strategy'] or 'unknown'}",
        "roles:",
    ]
    roles = snapshot["roles"]
    if roles:
        for role, state in roles.items():
            model = state.get("model") or "unknown-model"
            task = state.get("taskId") or "no-task"
            attempt = state.get("attempt")
            suffix = f" · attempt {attempt}" if attempt is not None else ""
            lines.append(f"  {role}: {state.get('status', 'UNKNOWN')} · {model} · {task}{suffix}")
    else:
        lines.append("  none")
    ratio = proof["closureRatio"]
    ratio_text = f"{ratio:.0%}" if isinstance(ratio, (int, float)) else "unknown"
    open_text = ", ".join(proof["open"]) if proof["open"] else "none"
    lines.extend(
        [
            f"proof: {ratio_text} closed · open: {open_text}",
            "budget: "
            f"{budget['consumedTokens']} tokens · remaining {budget['remainingTokens'] if budget['remainingTokens'] is not None else 'unknown'}"
            f" / max {budget['maxTokens'] if budget['maxTokens'] is not None else 'unknown'}"
            f" · coverage {budget['tokenCoverageRatio'] if budget['tokenCoverageRatio'] is not None else 'unknown'}",
        ]
    )
    return "\n".join(lines)


def resolve_run_dir(
    *,
    repo: str | Path = ".",
    run: str | None = None,
    run_dir: str | Path | None = None,
) -> Path:
    if run_dir is not None:
        resolved = Path(run_dir).expanduser().resolve()
    else:
        if not run:
            raise ValueError("either run or run_dir is required")
        runs_dir = Path(repo).resolve() / ".proofloop" / "runs"
        if run == "latest":
            candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir()) if runs_dir.exists() else []
            if not candidates:
                raise ValueError(f"no ProofLoop runs found under {runs_dir}")
            resolved = candidates[-1].resolve()
        else:
            resolved = (runs_dir / run).resolve()
    if not resolved.is_dir():
        raise ValueError(f"ProofLoop run directory does not exist: {resolved}")
    return resolved


def watch_events(
    run_dir: str | Path,
    *,
    stream: TextIO,
    output_format: str = "human",
    verbosity: str = "info",
    color: str = "auto",
    task_id: str | None = None,
    minimum_level: str | None = None,
    follow: bool = True,
    poll_interval: float = 0.1,
    event_bus: EventBus | None = None,
) -> int:
    if output_format not in {"human", "jsonl", "tui"}:
        raise ValueError("watch output format must be human, jsonl, or tui")
    if minimum_level is not None and minimum_level not in _LEVELS:
        raise ValueError(f"unsupported minimum level: {minimum_level}")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")
    source = Path(run_dir).resolve() / "events.jsonl"
    if not source.is_file():
        raise ValueError(f"event stream does not exist: {source}")
    renderer = build_renderer(output_format, stream, verbosity, color)
    rendered = 0
    buffer = ""
    line_number = 0

    with source.open("r", encoding="utf-8") as handle:
        while True:
            chunk = handle.read(8192)
            if chunk:
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line_number += 1
                    if not line:
                        continue
                    event = _parse_event(line, line_number)
                    if event_bus is not None:
                        event_bus.publish(ProofLoopEvent.from_v1_dict(event))
                    if not _matches(event, task_id=task_id, minimum_level=minimum_level):
                        continue
                    renderer.render(event)
                    rendered += 1
                continue
            if not follow:
                break
            time.sleep(poll_interval)
    return rendered


def _parse_event(line: str, line_number: int) -> dict[str, Any]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid event JSON at line {line_number}: {exc.msg}") from exc
    try:
        return validate_event(event)
    except ValueError as exc:
        raise ValueError(f"invalid event schema at line {line_number}: {exc}") from exc


def _matches(
    event: dict[str, Any],
    *,
    task_id: str | None,
    minimum_level: str | None,
) -> bool:
    if task_id is not None and event.get("taskId") != task_id:
        return False
    if minimum_level is not None:
        event_level = str(event.get("level") or "info")
        if event_level not in _LEVELS or _LEVELS[event_level] < _LEVELS[minimum_level]:
            return False
    return True
