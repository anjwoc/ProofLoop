from __future__ import annotations

import http.server
import json
import socketserver
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

from proofloop_core.context.io import read_json
from proofloop_core.analysis.usage import build_usage_summary, TOKEN_FIELDS


def scan_runs(repo_root: Path) -> list[dict[str, Any]]:
    runs_dir = repo_root / ".proofloop" / "runs"
    if not runs_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for run_path in sorted(runs_dir.iterdir(), reverse=True):
        if not run_path.is_dir():
            continue
        run_id = run_path.name
        # Request string and timestamp
        request_str = ""
        timestamp = ""
        req_file = run_path / "request.json"
        if req_file.exists():
            req_data = read_json(req_file)
            request_str = str(req_data.get("prompt") or req_data.get("request") or "")
            timestamp = str(req_data.get("timestamp") or "")

        if not request_str or not timestamp:
            events_file = run_path / "events.jsonl"
            if events_file.exists():
                for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                        if ev.get("type") == "run.started":
                            if not timestamp:
                                timestamp = str(ev.get("timestamp") or "")
                            data = ev.get("data", {})
                            if not request_str:
                                request_str = str(data.get("request") or ev.get("message") or "")
                            break
                    except json.JSONDecodeError:
                        continue

        # Load or compute usage summary
        usage_summary_path = run_path / "usage" / "usage-summary.json"
        if usage_summary_path.exists():
            usage_data = read_json(usage_summary_path)
        else:
            try:
                usage_data = build_usage_summary(run_path)
            except Exception:
                usage_data = {"totals": {}, "byInvocation": []}

        from proofloop_core.analysis.tokscale import enrich_usage_costs
        enrich_usage_costs(usage_data)
        if usage_summary_path.exists() and (usage_data.get("totals", {}).get("costUsd") or 0.0) > 0.0 and (read_json(usage_summary_path).get("totals", {}).get("costUsd") or 0.0) == 0.0:
            try:
                from proofloop_core.context.io import write_json
                write_json(usage_summary_path, usage_data)
            except Exception:
                pass

        # Load truth report
        truth_file = run_path / "truth-report.json"
        truth_report = read_json(truth_file) if truth_file.exists() else {}

        # Load strategy
        strategy_file = run_path / "strategy.json"
        strategy = read_json(strategy_file) if strategy_file.exists() else {}

        # Load model trace summary
        model_trace_file = run_path / "model-trace-summary.json"
        model_trace = read_json(model_trace_file) if model_trace_file.exists() else {}

        # Load run.json for status / timestamps
        run_file = run_path / "run.json"
        run_meta = read_json(run_file) if run_file.exists() else {}

        # Load invocations log (lightweight: skip large fields)
        invocations_log: list[dict[str, Any]] = []
        inv_log_file = run_path / "invocations.jsonl"
        if inv_log_file.exists():
            for line in inv_log_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    # Strip heavy nested fields to keep payload lean
                    entry.pop("usage", None)
                    invocations_log.append(entry)
                except json.JSONDecodeError:
                    continue

        # Analyze models used & multi-model routing
        invocations = usage_data.get("byInvocation") or []
        models_used = sorted({
            str(inv.get("model"))
            for inv in invocations
            if inv.get("model") and inv.get("model") != "unknown"
        })

        if len(models_used) > 1:
            routing_type = "MULTI_MODEL_ROUTING"
        elif len(models_used) == 1:
            routing_type = "SINGLE_MODEL"
        else:
            routing_type = "NO_INVOCATION"

        runs.append({
            "runId": run_id,
            "timestamp": timestamp,
            "request": request_str,
            "routingType": routing_type,
            "modelsUsed": models_used,
            "usage": usage_data,
            "truthReport": truth_report,
            "strategy": strategy,
            "modelTrace": model_trace,
            "runMeta": run_meta,
            "invocationsLog": invocations_log,
        })

    return runs


def aggregate_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost = 0.0
    totals: dict[str, int] = {f: 0 for f in TOKEN_FIELDS}
    totals["rawTotal"] = 0

    by_model: dict[str, dict[str, Any]] = {}
    by_role: dict[str, dict[str, Any]] = {}

    for r in runs:
        u = r.get("usage") or {}
        t = u.get("totals") or {}
        total_cost += float(t.get("costUsd") or 0.0)
        for f in TOKEN_FIELDS:
            totals[f] += int(t.get(f) or 0)
        totals["rawTotal"] += int(t.get("rawTotal") or 0)

        # Models
        for m in (u.get("byModel") or []):
            m_name = str(m.get("model") or "unknown")
            if m_name not in by_model:
                by_model[m_name] = {
                    "model": m_name,
                    "invocations": 0,
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "reasoning": 0,
                    "rawTotal": 0,
                    "costUsd": 0.0,
                }
            bm = by_model[m_name]
            bm["invocations"] += int(m.get("invocations") or 0)
            bm["costUsd"] += float(m.get("costUsd") or 0.0)
            bm["rawTotal"] += int(m.get("rawTotal") or 0)
            mt = m.get("tokens") or {}
            for f in TOKEN_FIELDS:
                bm[f] = bm.get(f, 0) + int(mt.get(f) or 0)

        # Roles
        for role_item in (u.get("byRole") or []):
            r_name = str(role_item.get("role") or "unknown")
            if r_name not in by_role:
                by_role[r_name] = {
                    "role": r_name,
                    "invocations": 0,
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "reasoning": 0,
                    "rawTotal": 0,
                    "costUsd": 0.0,
                }
            br = by_role[r_name]
            br["invocations"] += int(role_item.get("invocations") or 0)
            br["costUsd"] += float(role_item.get("costUsd") or 0.0)
            br["rawTotal"] += int(role_item.get("rawTotal") or 0)
            rt = role_item.get("tokens") or {}
            for f in TOKEN_FIELDS:
                br[f] = br.get(f, 0) + int(rt.get(f) or 0)

    return {
        "totalCostUsd": round(total_cost, 8),
        "totalTokens": totals,
        "byModel": by_model,
        "byRole": by_role,
    }


class UsageViewerHandler(http.server.BaseHTTPRequestHandler):
    repo_root: Path = Path(".")
    dist_dir: Path = Path(".") / "tokscale_viewer" / "dist"
    template_path: Path = Path(__file__).resolve().parent / "viewer_template.html"

    def do_GET(self) -> None:
        if self.path == "/api/data":
            runs = scan_runs(self.repo_root)
            summary = aggregate_summary(runs)
            payload = {"runs": runs, "summary": summary}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Check static files in dist_dir first
        target_path = self.path.lstrip("/")
        if not target_path or target_path == "index.html":
            file_to_serve = self.dist_dir / "index.html"
            if not file_to_serve.exists():
                file_to_serve = self.template_path
        else:
            file_to_serve = self.dist_dir / target_path

        if file_to_serve.exists() and file_to_serve.is_file():
            content = file_to_serve.read_bytes()
            content_type = "text/html; charset=utf-8"
            if file_to_serve.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif file_to_serve.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif file_to_serve.suffix == ".json":
                content_type = "application/json; charset=utf-8"
            elif file_to_serve.suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
                content_type = f"image/{file_to_serve.suffix.lstrip('.')}"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Quiet HTTP logs


def start_usage_viewer(
    repo_root: str | Path = ".",
    port: int = 8400,
    open_browser: bool = True,
    block: bool = True,
) -> int:
    resolved_root = Path(repo_root).resolve()
    UsageViewerHandler.repo_root = resolved_root
    UsageViewerHandler.dist_dir = resolved_root / "tokscale_viewer" / "dist"
    UsageViewerHandler.template_path = Path(__file__).resolve().parent / "viewer_template.html"

    # Find open port if desired taken
    class ReusableTCPServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    try:
        httpd = ReusableTCPServer(("127.0.0.1", port), UsageViewerHandler)
    except OSError:
        httpd = ReusableTCPServer(("127.0.0.1", 0), UsageViewerHandler)
    port = httpd.server_address[1]

    url = f"http://127.0.0.1:{port}"
    print(f"ProofLoop TokScale & Model Routing Viewer running at: {url}")
    print(f"Scanning runs inside: {resolved_root / '.proofloop' / 'runs'}")
    print("Press Ctrl+C to stop the server.")

    if open_browser:
        def _open() -> None:
            webbrowser.open(url)
        threading.Timer(0.5, _open).start()

    if block:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down Usage Viewer server.")
            httpd.shutdown()
            httpd.server_close()
    else:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return port
    return 0
