from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from proofloop_core.context.io import write_json
from proofloop_core.analysis.usage import TOKEN_FIELDS, TokenLedger, UsageObservation, build_usage_summary, load_invocations


TOKSCALE_VERSION = "4.5.3"


class TokScaleAdapter:
    def __init__(self, binary: str | None = None) -> None:
        configured = binary or os.environ.get("PROOFLOOP_TOKSCALE")
        managed = Path(os.environ.get("PROOFLOOP_HOME", Path.home() / ".proofloop")) / "bin" / "tokscale"
        self.binary = configured or shutil.which("tokscale") or (str(managed) if managed.exists() else None)

    def status(self) -> dict[str, Any]:
        if not self.binary:
            return {"status": "UNAVAILABLE", "reason": "TOKSCALE_CLI_MISSING"}
        try:
            completed = subprocess.run(
                [self.binary, "--version"],
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            return {"status": "UNAVAILABLE", "reason": "TOKSCALE_CLI_FAILED", "error": str(exc)}
        return {
            "status": "PASS" if completed.returncode == 0 else "UNAVAILABLE",
            "binary": self.binary,
            "version": (completed.stdout or completed.stderr).strip(),
            "exitCode": completed.returncode,
        }

    def report(
        self,
        run_dir: str | Path | None = None,
        clients: set[str] | None = None,
    ) -> dict[str, Any]:
        if not self.binary:
            raise RuntimeError("tokScale CLI is unavailable")
        environment = dict(os.environ)
        if run_dir is not None:
            headless = Path(run_dir) / "usage" / "tokscale-headless"
            if headless.exists():
                environment["TOKSCALE_HEADLESS_DIR"] = str(headless)
        command = [self.binary, "models", "--json", "--group-by", "client,session,model"]
        if clients:
            command.extend(["--client", ",".join(sorted(clients))])
        if run_dir is not None:
            command.extend(["--since", _run_since_date(Path(run_dir))])
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"tokScale exited {completed.returncode}")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
            raise ValueError("tokScale report did not contain entries")
        return value

    def reconcile(self, run_dir: str | Path) -> dict[str, Any]:
        root = Path(run_dir)
        result: dict[str, Any]
        invocations = load_invocations(root)
        if not invocations:
            try:
                invocations = build_usage_summary(root).get("byInvocation") or []
            except Exception:
                invocations = []
        session_map = {
            str(item["sessionId"]): item
            for item in invocations
            if isinstance(item.get("sessionId"), str) and item["sessionId"]
        }
        invocation_map = {
            str(item["invocationId"]): item
            for item in invocations
            if isinstance(item.get("invocationId"), str)
            and (root / "usage" / "tokscale-headless" / "codex" / f"{item['invocationId']}.jsonl").exists()
        }
        join_map = {**session_map, **invocation_map}
        status = self.status()
        if not join_map:
            result = {"schemaVersion": "1.0", "status": "SKIPPED", "reason": "NO_SESSION_IDS", "matches": []}
            write_json(root / "usage" / "usage-reconciliation.json", result)
            summary = build_usage_summary(root)
            enrich_usage_costs(summary)
            write_json(root / "usage" / "usage-summary.json", summary)
            return result
        if status["status"] != "PASS":
            result = {"schemaVersion": "1.0", **status, "matches": []}
            write_json(root / "usage" / "usage-reconciliation.json", result)
            summary = build_usage_summary(root)
            enrich_usage_costs(summary)
            write_json(root / "usage" / "usage-summary.json", summary)
            return result

        clients = {
            _tokscale_client(str(item.get("runtime") or ""))
            for item in invocations
            if item.get("runtime")
        }
        report = self.report(root, clients)
        matching_entries = [
            item
            for item in report["entries"]
            if isinstance(item, dict) and str(item.get("sessionId") or "") in join_map
        ]
        write_json(
            root / "usage" / "tokscale-raw.json",
            {
                "groupBy": report.get("groupBy"),
                "entries": matching_entries,
                "tokscale": status,
            },
        )
        before = {
            item["invocationId"]: item
            for item in build_usage_summary(root)["byInvocation"]
        }
        ledger = TokenLedger(root)
        matches: list[dict[str, Any]] = []
        run_id = _run_id(root)
        for entry in matching_entries:
            session_id = str(entry["sessionId"])
            invocation = join_map[session_id]
            invocation_id = str(invocation["invocationId"])
            provider_session_id = str(invocation.get("sessionId") or session_id)
            tokens = {
                field: int(entry.get(field, 0))
                for field in TOKEN_FIELDS
                if isinstance(entry.get(field), (int, float)) and not isinstance(entry.get(field), bool)
            }
            observation = UsageObservation(
                run_id=run_id,
                invocation_id=invocation_id,
                role=str(invocation.get("role") or "unknown"),
                runtime=str(invocation.get("runtime") or entry.get("client") or "unknown"),
                model=str(entry.get("model") or invocation.get("observedModel") or invocation.get("requestedModel") or "unknown"),
                requested_model=str(invocation.get("requestedModel")) if invocation.get("requestedModel") else None,
                session_id=provider_session_id,
                task_id=str(invocation.get("taskId")) if invocation.get("taskId") else None,
                phase=str(invocation.get("phase")) if invocation.get("phase") else None,
                tokens=tokens,
                source="tokscale",
                measurement_kind="final",
                evidence_level="TOKSCALE_PARSED",
                source_event_id=f"{session_id}:{entry.get('model')}",
                cost_usd=float(entry["cost"]) if isinstance(entry.get("cost"), (int, float)) else None,
                cost_source="tokscale",
            )
            ledger.record(observation)
            provider = before.get(invocation_id)
            differences = _token_differences(provider.get("tokens", {}) if provider else {}, tokens)
            matches.append(
                {
                    "invocationId": invocation_id,
                    "sessionId": provider_session_id,
                    "tokscaleSessionId": session_id,
                    "model": observation.model,
                    "status": "VERIFIED" if provider and not differences else "FILLED" if not provider else "MISMATCH",
                    "differences": differences,
                }
            )
        result = {
            "schemaVersion": "1.0",
            "status": "PASS",
            "tokscale": status,
            "matchedSessions": len({item["sessionId"] for item in matches}),
            "requestedSessions": len({str(item.get("invocationId")) for item in join_map.values()}),
            "matches": matches,
        }
        write_json(root / "usage" / "usage-reconciliation.json", result)
        summary = build_usage_summary(root)
        enrich_usage_costs(summary)
        write_json(root / "usage" / "usage-summary.json", summary)
        return result


def _run_id(run_dir: Path) -> str:
    path = run_dir / "run.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("runId"), str):
            return value["runId"]
    return run_dir.name


def _run_since_date(run_dir: Path) -> str:
    path = run_dir / "run.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("createdAtEpoch"), (int, float)):
            return time.strftime("%Y-%m-%d", time.localtime(float(value["createdAtEpoch"])))
    return time.strftime("%Y-%m-%d")


def _tokscale_client(runtime: str) -> str:
    return {
        "claude-code": "claude",
        "agy": "antigravity-cli",
    }.get(runtime, runtime)


def _token_differences(provider: dict[str, Any], tokscale: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        field: {"provider": int(provider.get(field, 0)), "tokscale": tokscale.get(field, 0)}
        for field in TOKEN_FIELDS
        if int(provider.get(field, 0)) != tokscale.get(field, 0)
    }


def calculate_invocation_cost(model: str | None, tokens: dict[str, Any] | None) -> float:
    if not tokens or not isinstance(tokens, dict):
        return 0.0

    inp = int(tokens.get("input", 0) or 0)
    out = int(tokens.get("output", 0) or 0)
    cache_read = int(tokens.get("cacheRead", 0) or 0)
    cache_write = int(tokens.get("cacheWrite", 0) or 0)

    if inp == 0 and out == 0 and cache_read == 0 and cache_write == 0:
        return 0.0

    model_lower = str(model or "").lower().strip()

    if "opus" in model_lower:
        rates = (15.0, 1.50, 18.75, 75.0)
    elif "sonnet" in model_lower:
        rates = (3.0, 0.30, 3.75, 15.0)
    elif "haiku" in model_lower:
        rates = (1.0, 0.10, 1.25, 5.0)
    elif "gpt-4o" in model_lower:
        rates = (2.50, 1.25, 0.0, 10.0)
    elif "o3-mini" in model_lower:
        rates = (1.10, 0.55, 0.0, 4.40)
    elif "o1" in model_lower:
        rates = (15.0, 7.50, 0.0, 60.0)
    elif "gemini-2.5-pro" in model_lower or "gemini-1.5-pro" in model_lower or "gemini-pro" in model_lower:
        rates = (1.25, 0.3125, 0.0, 5.0)
    elif "gemini-2.5-flash" in model_lower or "gemini-1.5-flash" in model_lower or "gemini-flash" in model_lower:
        rates = (0.075, 0.01875, 0.0, 0.30)
    elif "fable" in model_lower:
        rates = (3.0, 0.30, 3.75, 15.0)
    else:
        rates = (3.0, 0.30, 3.75, 15.0)

    cost = (inp * rates[0] + cache_read * rates[1] + cache_write * rates[2] + out * rates[3]) / 1_000_000.0
    return round(cost, 8)


def enrich_usage_costs(usage_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(usage_data, dict):
        return usage_data

    invocations = usage_data.get("byInvocation") or []
    modified = False

    for inv in invocations:
        if not isinstance(inv, dict):
            continue
        current_cost = inv.get("costUsd")
        if current_cost is None or current_cost == 0.0 or not isinstance(current_cost, (int, float)):
            tokens = inv.get("tokens") or {}
            model_name = inv.get("model") or inv.get("requestedModel") or "unknown"
            calc_cost = calculate_invocation_cost(model_name, tokens)
            if calc_cost > 0.0:
                inv["costUsd"] = calc_cost
                if not inv.get("costSource"):
                    inv["costSource"] = "tokscale_native"
                modified = True

    total_raw = usage_data.get("totals", {}).get("rawTotal", 0)
    total_cost = usage_data.get("totals", {}).get("costUsd", 0.0)

    if modified or (total_cost == 0.0 and total_raw > 0):
        new_total_cost = sum(float(inv.get("costUsd") or 0.0) for inv in invocations if isinstance(inv, dict))
        if "totals" not in usage_data or not isinstance(usage_data["totals"], dict):
            usage_data["totals"] = {}
        usage_data["totals"]["costUsd"] = round(new_total_cost, 8)

        model_groups: dict[str, float] = {}
        for inv in invocations:
            if not isinstance(inv, dict):
                continue
            m = str(inv.get("model") or "unknown")
            model_groups[m] = model_groups.get(m, 0.0) + float(inv.get("costUsd") or 0.0)
        for m_item in (usage_data.get("byModel") or []):
            if isinstance(m_item, dict):
                m_name = str(m_item.get("model") or "unknown")
                if m_name in model_groups:
                    m_item["costUsd"] = round(model_groups[m_name], 8)

        role_groups: dict[str, float] = {}
        for inv in invocations:
            if not isinstance(inv, dict):
                continue
            r = str(inv.get("role") or "unknown")
            role_groups[r] = role_groups.get(r, 0.0) + float(inv.get("costUsd") or 0.0)
        for r_item in (usage_data.get("byRole") or []):
            if isinstance(r_item, dict):
                r_name = str(r_item.get("role") or "unknown")
                if r_name in role_groups:
                    r_item["costUsd"] = round(role_groups[r_name], 8)

    return usage_data
