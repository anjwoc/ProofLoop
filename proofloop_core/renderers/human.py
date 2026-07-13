from __future__ import annotations

from typing import Any, TextIO


_VERBOSITY = {"info": 0, "verbose": 1, "debug": 2}
_COLORS = {
    "debug": "\x1b[2m",
    "info": "\x1b[36m",
    "warning": "\x1b[33m",
    "error": "\x1b[31m",
}
_RESET = "\x1b[0m"


class HumanRenderer:
    def __init__(self, stream: TextIO, *, verbosity: str = "info", color: str = "auto") -> None:
        if verbosity not in _VERBOSITY:
            raise ValueError(f"unsupported verbosity: {verbosity}")
        if color not in {"auto", "always", "never"}:
            raise ValueError(f"unsupported color policy: {color}")
        self.stream = stream
        self.verbosity = verbosity
        self.use_color = color == "always" or (color == "auto" and bool(getattr(stream, "isatty", lambda: False)()))

    def render(self, event: dict[str, Any]) -> None:
        if _VERBOSITY[self.verbosity] < self._required_verbosity(event):
            return
        text = self._format(event)
        if not text:
            return
        self.stream.write(text.rstrip("\n") + "\n")
        self.stream.flush()

    def _required_verbosity(self, event: dict[str, Any]) -> int:
        if event.get("type") == "check.output":
            return _VERBOSITY["debug"]
        if event.get("type") == "budget.updated":
            return _VERBOSITY["verbose"]
        return _VERBOSITY["info"]

    def _prefix(self, event: dict[str, Any]) -> str:
        phase = str(event.get("phase") or "SYSTEM")
        plain = f"[ProofLoop][{phase}]"
        if not self.use_color:
            return plain
        color = _COLORS.get(str(event.get("level") or "info"), _COLORS["info"])
        return f"{color}{plain}{_RESET}"

    def _format(self, event: dict[str, Any]) -> str:
        event_type = str(event.get("type") or "")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        prefix = self._prefix(event)

        if event_type == "role.started":
            role = data.get("role", "unknown-role")
            attempt = data.get("attempt")
            suffix = f" · attempt {attempt}" if attempt is not None else ""
            return f"{prefix} ▶ {role}{suffix}"

        if event_type in {"role.completed", "role.failed", "role.cancelled"}:
            role = data.get("role", "unknown-role")
            symbol = "✓" if event_type == "role.completed" else "✗"
            state = event_type.split(".", 1)[1].upper()
            lines = [f"{prefix} {symbol} {role} {state}"]
            reason = data.get("reasonCode") or data.get("reason") or data.get("error")
            if reason:
                lines.append(f"  reason: {reason}")
            if self.verbosity == "debug":
                if data.get("invocationId"):
                    lines.append(f"  invocation: {data['invocationId']}")
                if data.get("invocationDir"):
                    lines.append(f"  artifact: {data['invocationDir']}")
            return "\n".join(lines)

        if event_type == "role.model_observed":
            requested = data.get("requestedModel") or "unavailable"
            observed = data.get("observedModel") or "unavailable"
            evidence = data.get("evidenceLevel") or "UNAVAILABLE"
            proof = "VERIFIED" if evidence in {"HOST_RESOLVED", "HOST_OUTPUT"} and data.get("observedModel") else "UNPROVEN"
            return (
                f"{prefix} model evidence\n"
                f"  requested: {requested}\n"
                f"  observed: {observed}\n"
                f"  evidence: {evidence}\n"
                f"  routing proof: {proof}"
            )

        if event_type in {"check.completed", "check.failed"}:
            passed = event_type == "check.completed"
            symbol = "✓" if passed else "✗"
            verdict = "PASS" if passed else "FAIL"
            exit_code = data.get("exitCode")
            exit_text = f" · exit {exit_code}" if exit_code is not None else ""
            lines = [f"{prefix} {symbol} {verdict}{exit_text}"]
            command = data.get("command")
            if self.verbosity in {"verbose", "debug"} and isinstance(command, list):
                lines.append("  command: " + " ".join(str(part) for part in command))
            failed_tests = data.get("failedTests")
            if self.verbosity in {"verbose", "debug"} and isinstance(failed_tests, list):
                lines.extend(f"  failed: {name}" for name in failed_tests)
            if not passed:
                if data.get("failureReason"):
                    lines.append(f"  reason: {data['failureReason']}")
                output_tail = data.get("outputTail")
                if isinstance(output_tail, list):
                    lines.extend(f"  {line}" for line in output_tail[-5:])
            if self.verbosity == "debug":
                for key in ("stdoutRef", "stderrRef"):
                    if data.get(key):
                        lines.append(f"  artifact: {data[key]}")
            return "\n".join(lines)

        if event_type == "check.output":
            stream = data.get("stream", "output")
            text = str(data.get("text") or "").rstrip("\n")
            return f"{prefix} {stream}: {text}"

        if event_type in {"diff_guard.completed", "diff_guard.failed"}:
            verdict = data.get("verdict") or ("PASS" if event_type.endswith("completed") else "FAIL")
            symbol = "✓" if verdict == "PASS" else "✗"
            lines = [f"{prefix} {symbol} DIFF GUARD {verdict}"]
            metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
            if self.verbosity in {"verbose", "debug"} and metrics:
                lines.append(
                    f"  {metrics.get('changedFiles', 0)} files · +{metrics.get('addedLines', 0)} LOC · "
                    f"{metrics.get('newFiles', 0)} new"
                )
            violations = data.get("violations")
            if isinstance(violations, list):
                for violation in violations:
                    if isinstance(violation, dict):
                        detail = " · ".join(
                            str(value)
                            for value in (violation.get("code"), violation.get("path"), violation.get("detail"))
                            if value
                        )
                        if detail:
                            lines.append(f"  violation: {detail}")
            if self.verbosity == "debug" and data.get("artifact"):
                lines.append(f"  artifact: {data['artifact']}")
            return "\n".join(lines)

        if event_type == "recovery.scheduled":
            source = data.get("fromRole", "unknown")
            target = data.get("toRole", "unknown")
            reason = data.get("reason") or event.get("message")
            lines = [f"{prefix} ⇧ {source} → {target}"]
            from_model = data.get("fromRequestedModel")
            to_model = data.get("toRequestedModel")
            if from_model or to_model:
                lines.append(f"  requested model: {from_model or 'unavailable'} → {to_model or 'unavailable'}")
            lines.append(f"  reason: {reason}")
            return "\n".join(lines)

        if event_type in {"retry.scheduled", "replan.scheduled"}:
            reason = data.get("reason") or event.get("message")
            return f"{prefix} ↻ {event_type.split('.')[0].upper()}\n  reason: {reason}"

        if event_type.startswith("review."):
            verdict = data.get("verdict") or event_type.split(".", 1)[1].upper()
            finding = data.get("finding")
            lines = [f"{prefix} REVIEW {verdict}"]
            if finding:
                lines.append(f"  finding: {finding}")
            if self.verbosity in {"verbose", "debug"}:
                findings = data.get("findings")
                if isinstance(findings, list):
                    for item in findings:
                        value = item.get("message") if isinstance(item, dict) else item
                        if value and value != finding:
                            lines.append(f"  finding: {value}")
                candidates = data.get("deletionCandidates")
                if isinstance(candidates, list):
                    lines.extend(f"  delete: {candidate}" for candidate in candidates)
            return "\n".join(lines)

        if event_type == "truth.completed":
            status = data.get("status") or data.get("verdict") or "UNKNOWN"
            return f"{prefix} ✓ TRUTH {status}"

        if event_type == "run.started":
            run_id = event.get("runId")
            return f"{prefix} ◆ ProofLoop run {run_id}"

        if event_type in {"run.completed", "run.failed", "run.blocked"}:
            verdict = data.get("verdict") or event_type.split(".", 1)[1].upper()
            return f"{prefix} ProofLoop {verdict}"

        return f"{prefix} {event.get('message') or event_type}"
