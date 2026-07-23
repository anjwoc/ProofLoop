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
        event_type = event.get("type")
        if event_type == "role_prompt.rendered":
            return _VERBOSITY["debug"]
        if event_type == "check.output":
            return _VERBOSITY["debug"]
        if event_type == "session.update" and (event.get("data") or {}).get("kind") == "agent_thought_chunk":
            return _VERBOSITY["debug"]
        if event_type in {
            "role.started",
            "role.progress",
            "role.output",
            "role.completed",
            "role.model_observed",
            "session.started",
            "session.completed",
            "session.failed",
            "session.update",
            "usage.observed",
            "model.changed",
            "runtime.selected",
            "runtime.fallback",
        }:
            return _VERBOSITY["verbose"]
        if event_type == "budget.updated":
            return _VERBOSITY["verbose"]
        if event_type == "model.requested":
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
        raw_data = event.get("data")
        # Event payloads originate at the JSON boundary. Narrow once here so
        # every renderer branch can safely treat the payload as a mapping.
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        prefix = self._prefix(event)

        if event_type == "intent.compiled":
            lines = [f"{prefix} {event.get('message') or event_type}"]
            lines.extend(f"  근거: {item}" for item in data.get("basis", []) if item)
            lines.extend(f"  대상: {item}" for item in data.get("targets", []) if item)
            lines.extend(f"  제외: {item}" for item in data.get("exclusions", []) if item)
            return "\n".join(lines)

        if event_type == "strategy.selected":
            lines = [f"{prefix} {event.get('message') or event_type}"]
            lines.extend(f"  근거: {item}" for item in data.get("basis", []) if item)
            if data.get("expectedChanges"):
                lines.append(f"  예상 변경: {data['expectedChanges']}")
            if data.get("plannedChecks") is not None:
                lines.append(f"  검증 계획: {data['plannedChecks']}개")
            return "\n".join(lines)

        if event_type == "contract.frozen":
            lines = [f"{prefix} {event.get('message') or event_type}"]
            lines.extend(f"  구현: {item}" for item in data.get("deliverables", []) if item)
            lines.extend(f"  성공 조건: {item}" for item in data.get("successCriteria", []) if item)
            return "\n".join(lines)

        if event_type == "implementation.started":
            lines = [f"{prefix} {event.get('message') or event_type}"]
            lines.extend(f"  근거: {item}" for item in data.get("basis", []) if item)
            if data.get("path"):
                lines.append(f"  변경: {data['path']}")
            return "\n".join(lines)

        if event_type == "implementation.changed":
            lines = [f"{prefix} {event.get('message') or event_type}"]
            lines.extend(f"  변경: {item}" for item in data.get("changedPaths", []) if item)
            return "\n".join(lines)

        if event_type == "role_prompt.rendered":
            role = data.get("role", "unknown-role")
            model = data.get("model", "unknown-model")
            reason = data.get("reason", "role dispatch")
            prompt = str(data.get("promptText") or "").rstrip("\n")
            lines = [
                f"{prefix} Model selected",
                f"             Role: {role}",
                f"             Model: {model}",
                f"             Reason: {reason}",
                f"\n{prefix} Prompt compiled:\n{prompt}",
            ]
            return "\n".join(lines)

        if event_type == "role.started":
            role = data.get("role", "unknown-role")
            attempt = data.get("attempt")
            suffix = f" · attempt {attempt}" if attempt is not None else ""
            return f"{prefix} ▶ {role}{suffix}"

        if event_type == "role.progress":
            role = data.get("role", "unknown-role")
            elapsed = data.get("elapsedSeconds")
            elapsed_text = f" · {elapsed:.1f}s" if isinstance(elapsed, (int, float)) else ""
            process_id = data.get("processId")
            pid_text = f" · pid {process_id}" if isinstance(process_id, int) else ""
            return f"{prefix} … {role} running{elapsed_text}{pid_text}"

        if event_type == "role.output":
            role = data.get("role", "unknown-role")
            stream = data.get("stream", "output")
            text = str(data.get("text") or "").rstrip("\n")
            return f"{prefix} {role} {stream}: {text}"

        if event_type == "session.update":
            kind = str(data.get("kind") or "unknown")
            role = data.get("role", "agent")
            text = str(data.get("text") or event.get("message") or "").rstrip("\n")
            if kind == "agent_message_chunk":
                return f"{prefix} {role}: {text}"
            if kind == "tool_call_started":
                return f"{prefix} {role} tool ▶ {text}"
            if kind == "tool_call_updated":
                return f"{prefix} {role} tool ✓ {text}"
            if kind == "plan_updated":
                return f"{prefix} {role} plan: {text}"
            if kind == "agent_thought_chunk":
                return f"{prefix} {role} thought: {text}"
            return f"{prefix} {role} {kind}: {text}"

        if event_type in {"session.started", "session.completed", "session.failed"}:
            runtime = data.get("runtime") or data.get("role") or "agent"
            session_id = data.get("sessionId")
            suffix = f" · {session_id}" if session_id else ""
            state = event_type.split(".", 1)[1]
            return f"{prefix} session {state} · {runtime}{suffix}"

        if event_type == "usage.observed":
            role = data.get("role", "agent")
            raw_tokens = data.get("tokens")
            tokens: dict[str, Any] = raw_tokens if isinstance(raw_tokens, dict) else {}
            total = sum(int(value) for value in tokens.values() if isinstance(value, int))
            model = data.get("observedModel") or data.get("requestedModel") or "unknown-model"
            return f"{prefix} usage · {role} · {model} · {total:,} tokens"

        if event_type == "model.changed":
            previous = data.get("previousModel") or "none"
            active = data.get("activeModel") or "unavailable"
            evidence = data.get("evidenceLevel") or "UNAVAILABLE"
            reason = data.get("reason") or event.get("message")
            return (
                f"{prefix} model changed\n"
                f"  {previous} → {active}\n"
                f"  evidence: {evidence}\n"
                f"  reason: {reason}"
            )

        if event_type in {"runtime.selected", "runtime.fallback"}:
            runtime = data.get("runtime") or "unavailable"
            transport = data.get("transport") or "unavailable"
            reason = data.get("reason")
            suffix = f" · {reason}" if event_type == "runtime.fallback" and reason else ""
            return f"{prefix} runtime {runtime} · {transport}{suffix}"

        if event_type == "goal.state_changed":
            return f"{prefix} goal {data.get('previous')} → {data.get('state')} · {data.get('reason')}"

        if event_type == "memory.prepared":
            return f"{prefix} memory ready · {data.get('taskPath')}"

        if event_type in {"role.completed", "role.failed", "role.cancelled"}:
            role = data.get("role", "unknown-role")
            symbol = "✓" if event_type == "role.completed" else "✗"
            state = event_type.split(".", 1)[1].upper()
            lines = [f"{prefix} {symbol} {role} {state}"]
            reason = data.get("reasonCode") or data.get("reason") or data.get("error")
            if reason:
                lines.append(f"  reason: {reason}")
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
            if usage and isinstance(usage.get("rawTotal"), int):
                lines.append(f"  usage: {usage['rawTotal']:,} tokens · {usage.get('model') or 'unknown-model'}")
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
            proof = (
                "VERIFIED"
                if evidence in {"HOST_RESOLVED", "HOST_OUTPUT", "ACP_SESSION_CONFIG"}
                and data.get("observedModel")
                else "UNPROVEN"
            )
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
            names = {
                "static-web-structure": "웹 구조 검사",
                "static-web-javascript-syntax": "JavaScript 구문 검사",
                "static-web-browser-load": "브라우저 로드",
                "static-web-animation": "애니메이션 확인",
                "static-web-interaction-wiring": "확대·이동 동작",
            }
            raw_name = str(data.get("name") or "")
            name = names.get(raw_name, raw_name)
            label = raw_name if not name or name == raw_name else f"{raw_name} · {name}"
            lines = [f"{prefix} {symbol} {label}" if label else f"{prefix} {symbol} {verdict}{exit_text}"]
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
            if event_type == "review.completed" and finding:
                symbol = "✓" if verdict == "PASS" else "✗"
                return f"{prefix} {symbol} {finding}"
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
            lines = [f"{prefix} {status}"]
            if data.get("changedFiles") is not None:
                lines.append(f"  변경: {data['changedFiles']}개 파일")
            if data.get("checksPassed") is not None and data.get("checksTotal") is not None:
                lines.append(f"  검증: {data['checksPassed']}/{data['checksTotal']} 통과")
            if data.get("result"):
                lines.append(f"  결과물: {data['result']}")
            return "\n".join(lines)

        if event_type == "input.required":
            lines = [f"{prefix} 사용자 답변이 필요합니다."]
            lines.extend(f"  질문: {item}" for item in data.get("questions", []) if item)
            return "\n".join(lines)

        if event_type == "run.started":
            run_id = event.get("runId")
            return f"{prefix} ◆ ProofLoop run {run_id}"

        if event_type in {"run.completed", "run.failed", "run.blocked"}:
            verdict = data.get("verdict") or event_type.split(".", 1)[1].upper()
            return f"{prefix} ProofLoop {verdict}"

        return f"{prefix} {event.get('message') or event_type}"
