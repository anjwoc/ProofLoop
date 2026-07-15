from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .io import write_json
from .usage import TOKEN_FIELDS, TokenLedger, UsageObservation, build_usage_summary, load_invocations


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
        invocations = load_invocations(root)
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
            build_usage_summary(root)
            return result
        if status["status"] != "PASS":
            result = {"schemaVersion": "1.0", **status, "matches": []}
            write_json(root / "usage" / "usage-reconciliation.json", result)
            build_usage_summary(root)
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
        build_usage_summary(root)
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
        "antigravity": "antigravity-cli",
    }.get(runtime, runtime)


def _token_differences(provider: dict[str, Any], tokscale: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        field: {"provider": int(provider.get(field, 0)), "tokscale": tokscale.get(field, 0)}
        for field in TOKEN_FIELDS
        if int(provider.get(field, 0)) != tokscale.get(field, 0)
    }
