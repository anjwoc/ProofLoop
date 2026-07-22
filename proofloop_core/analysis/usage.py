from __future__ import annotations

import json
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from proofloop_core.context.io import write_json


TOKEN_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "reasoning")
# Cache reads remain fully visible in ``rawTotal``. They are deliberately
# discounted only for the run budget: unlike new prompt/output work, they
# generally cost less and do not represent new agent work.
CACHE_READ_BUDGET_WEIGHT_NUMERATOR = 1
CACHE_READ_BUDGET_WEIGHT_DENOMINATOR = 10

_TOKEN_ALIASES = {
    "input": ("input", "input_tokens", "inputTokens", "promptTokenCount", "inputTokenCount", "input_other"),
    "output": ("output", "output_tokens", "outputTokens", "candidatesTokenCount", "outputTokenCount"),
        "cacheRead": (
        "cacheRead",
        "cache_read",
        "cache_read_input_tokens",
        "cached_input_tokens",
        "cacheReadInputTokens",
        "cached",
        "cachedContentTokenCount",
        "input_cache_read",
    ),
    "cacheWrite": (
        "cacheWrite",
        "cache_write",
        "cache_creation_input_tokens",
        "cacheCreationInputTokens",
        "cacheCreate",
        "input_cache_creation",
    ),
    "reasoning": (
        "reasoning",
        "reasoning_output_tokens",
        "reasoningTokens",
        "thoughts",
        "thoughtsTokenCount",
        "thinkingOutputTokens",
    ),
}


def normalize_tokens(value: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for field, aliases in _TOKEN_ALIASES.items():
        for alias in aliases:
            candidate = value.get(alias)
            if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
                continue
            amount = int(candidate)
            if amount < 0:
                continue
            result[field] = amount
            break
    cache = value.get("cache")
    if isinstance(cache, dict):
        if "cacheRead" not in result and isinstance(cache.get("read"), (int, float)):
            result["cacheRead"] = max(0, int(cache["read"]))
        if "cacheWrite" not in result and isinstance(cache.get("write"), (int, float)):
            result["cacheWrite"] = max(0, int(cache["write"]))
    return result


def budgeted_token_total(value: dict[str, Any]) -> int:
    """Return the conservative total used by ProofLoop hard token budgets.

    ``rawTotal`` remains the fully reported and benchmarked quantity. When a
    provider exposes a field-level breakdown, cache reads count at 10% for
    scheduling while new input, output, cache creation, and reasoning count in
    full. A legacy result with only ``rawTotal`` counts in full, so unknown
    usage never silently buys extra budget.
    """
    nested = value.get("tokens")
    tokens = nested if isinstance(nested, dict) else value
    fields = {
        field: int(tokens[field])
        for field in TOKEN_FIELDS
        if isinstance(tokens.get(field), int) and not isinstance(tokens.get(field), bool)
    }
    if not fields:
        raw_total = value.get("rawTotal")
        return int(raw_total) if isinstance(raw_total, int) and not isinstance(raw_total, bool) else 0
    cache_read = fields.get("cacheRead", 0)
    direct = sum(amount for field, amount in fields.items() if field != "cacheRead")
    discounted_cache_read = (
        cache_read * CACHE_READ_BUDGET_WEIGHT_NUMERATOR + CACHE_READ_BUDGET_WEIGHT_DENOMINATOR - 1
    ) // CACHE_READ_BUDGET_WEIGHT_DENOMINATOR
    return direct + discounted_cache_read


@dataclass(frozen=True)
class UsageObservation:
    run_id: str
    invocation_id: str
    role: str
    runtime: str
    model: str | None
    tokens: dict[str, int]
    source: str
    measurement_kind: str
    task_id: str | None = None
    phase: str | None = None
    attempt: int | None = None
    session_id: str | None = None
    workload_tier: str | None = None
    requested_model: str | None = None
    evidence_level: str = "PROVIDER_REPORTED"
    source_event_id: str | None = None
    cost_usd: float | None = None
    cost_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "schemaVersion": "1.0",
            "runId": self.run_id,
            "invocationId": self.invocation_id,
            "role": self.role,
            "runtime": self.runtime,
            "model": self.model,
            "requestedModel": self.requested_model,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "workloadTier": self.workload_tier,
            "phase": self.phase,
            "attempt": self.attempt,
            "tokens": {field: self.tokens[field] for field in TOKEN_FIELDS if field in self.tokens},
            "source": self.source,
            "measurementKind": self.measurement_kind,
            "evidenceLevel": self.evidence_level,
            "sourceEventId": self.source_event_id,
            "costUsd": self.cost_usd,
            "costSource": self.cost_source,
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        }
        item["dedupKey"] = self.dedup_key(item)
        return item

    def dedup_key(self, item: dict[str, Any] | None = None) -> str:
        value = item or {}
        if self.source_event_id:
            suffix = self.source_event_id
        else:
            suffix = json.dumps(value.get("tokens") or self.tokens, sort_keys=True, separators=(",", ":"))
        return ":".join(
            (
                self.source,
                self.runtime,
                self.session_id or "no-session",
                self.invocation_id,
                self.measurement_kind,
                suffix,
            )
        )


class TokenLedger:
    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.root = self.run_dir / "usage"
        self.path = self.root / "usage-events.jsonl"
        self._lock = threading.RLock()
        self._dedup_keys: set[str] | None = None

    def record(self, observation: UsageObservation) -> dict[str, Any] | None:
        if observation.measurement_kind not in {"delta", "cumulative", "final"}:
            raise ValueError("unsupported usage measurement kind")
        if not observation.tokens:
            return None
        if any(field not in TOKEN_FIELDS for field in observation.tokens):
            raise ValueError("unsupported token field")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in observation.tokens.values()):
            raise ValueError("token values must be non-negative integers")
        item = observation.to_dict()
        with self._lock:
            keys = self._load_dedup_keys()
            if item["dedupKey"] in keys:
                return None
            self.root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
            keys.add(item["dedupKey"])
        return item

    def observations(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def summarize(self, invocations: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        invocation_rows = list(invocations)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self.observations():
            grouped[str(item["invocationId"])].append(item)

        invocation_summaries: list[dict[str, Any]] = []
        totals = _zero_tokens()
        total_cost = 0.0
        cost_coverage = 0
        for invocation_id, items in grouped.items():
            selected = _aggregate_observations(items)
            for field in TOKEN_FIELDS:
                totals[field] += selected["tokens"].get(field, 0)
            if selected.get("costUsd") is not None:
                total_cost += float(selected["costUsd"])
                cost_coverage += 1
            invocation_summaries.append({"invocationId": invocation_id, **selected})

        invocation_summaries.sort(key=lambda item: item["invocationId"])
        model_groups = _group_summaries(invocation_summaries, "model")
        role_groups = _group_summaries(invocation_summaries, "role")
        task_groups = _group_summaries(invocation_summaries, "taskId")
        tier_groups = _group_summaries(invocation_summaries, "workloadTier")
        known_ids = set(grouped)
        expected_ids = {str(item.get("invocationId")) for item in invocation_rows if item.get("invocationId")}
        expected_count = len(expected_ids or known_ids)
        measured_count = len(known_ids & expected_ids) if expected_ids else len(known_ids)
        raw_total = sum(totals.values())
        summary = {
            "schemaVersion": "1.0",
            "totals": {
                **totals,
                "rawTotal": raw_total,
                "budgetedTotal": budgeted_token_total(totals),
                "costUsd": round(total_cost, 8),
            },
            "coverage": {
                "expectedInvocations": expected_count,
                "measuredInvocations": measured_count,
                "tokenCoverageRatio": round(measured_count / expected_count, 6) if expected_count else 0.0,
                "costedInvocations": cost_coverage,
            },
            "byInvocation": invocation_summaries,
            "byModel": model_groups,
            "byRole": role_groups,
            "byTask": task_groups,
            "byTier": tier_groups,
        }
        from proofloop_core.analysis.tokscale import enrich_usage_costs
        enrich_usage_costs(summary)
        write_json(self.root / "usage-summary.json", summary)
        return summary

    def _load_dedup_keys(self) -> set[str]:
        if self._dedup_keys is None:
            self._dedup_keys = {
                str(item.get("dedupKey"))
                for item in self.observations()
                if isinstance(item.get("dedupKey"), str)
            }
        return self._dedup_keys


def load_invocations(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "invocations.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_usage_summary(run_dir: str | Path) -> dict[str, Any]:
    return TokenLedger(run_dir).summarize(load_invocations(run_dir))


def record_normalized_usage(
    run_dir: str | Path,
    *,
    run_id: str,
    invocation_id: str,
    role: str,
    runtime: str,
    model: str | None,
    data: dict[str, Any],
    source: str,
    task_id: str | None = None,
    phase: str | None = None,
    attempt: int | None = None,
    requested_model: str | None = None,
) -> dict[str, Any] | None:
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    normalized = {
        field: int(tokens[field])
        for field in TOKEN_FIELDS
        if isinstance(tokens.get(field), int)
        and not isinstance(tokens.get(field), bool)
        and tokens[field] >= 0
    }
    if not normalized:
        return None
    return TokenLedger(run_dir).record(
        UsageObservation(
            run_id=run_id,
            invocation_id=invocation_id,
            role=role,
            runtime=runtime,
            model=model,
            requested_model=requested_model,
            session_id=str(data.get("sessionId")) if data.get("sessionId") else None,
            workload_tier=str(data.get("workloadTier")) if data.get("workloadTier") else None,
            task_id=task_id,
            phase=phase,
            attempt=attempt,
            tokens=normalized,
            source=source,
            measurement_kind=str(data.get("measurementKind") or "delta"),
            evidence_level=str(data.get("evidenceLevel") or "PROVIDER_REPORTED"),
            source_event_id=str(data.get("sourceEventId")) if data.get("sourceEventId") else None,
        )
    )


def _aggregate_observations(items: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [item for item in items if item.get("source") != "tokscale"] or items
    finals = [item for item in primary if item.get("measurementKind") == "final"]
    if finals:
        chosen = finals[-1]
        tokens = dict(chosen.get("tokens") or {})
    else:
        cumulative = [item for item in primary if item.get("measurementKind") == "cumulative"]
        deltas = [item for item in primary if item.get("measurementKind") == "delta"]
        tokens = _zero_tokens()
        for field in TOKEN_FIELDS:
            tokens[field] = max((int(item.get("tokens", {}).get(field, 0)) for item in cumulative), default=0)
            tokens[field] += sum(int(item.get("tokens", {}).get(field, 0)) for item in deltas)
        tokens = {field: value for field, value in tokens.items() if value}
        chosen = primary[-1]
    cost_items = [item for item in items if isinstance(item.get("costUsd"), (int, float)) and item.get("costUsd") > 0]
    cost_item = cost_items[-1] if cost_items else None
    if cost_item:
        cost_usd = float(cost_item["costUsd"])
        cost_source = cost_item.get("costSource")
    else:
        from proofloop_core.analysis.tokscale import calculate_invocation_cost
        model_name = chosen.get("model") or chosen.get("requestedModel") or "unknown"
        cost_usd = calculate_invocation_cost(model_name, tokens)
        cost_source = "tokscale_native" if cost_usd > 0 else None
    return {
        "taskId": chosen.get("taskId"),
        "role": chosen.get("role"),
        "phase": chosen.get("phase"),
        "attempt": chosen.get("attempt"),
        "runtime": chosen.get("runtime"),
        "workloadTier": chosen.get("workloadTier"),
        "sessionId": chosen.get("sessionId"),
        "model": chosen.get("model") or chosen.get("requestedModel") or "unknown",
        "tokens": tokens,
        "rawTotal": sum(tokens.values()),
        "budgetedTotal": budgeted_token_total(tokens),
        "costUsd": cost_usd,
        "costSource": cost_source,
        "evidenceLevel": chosen.get("evidenceLevel", "UNAVAILABLE"),
    }


def _group_summaries(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        label = str(item.get(key) or "unattributed")
        group = groups.setdefault(label, {key: label, "tokens": _zero_tokens(), "costUsd": 0.0, "invocations": 0})
        group["invocations"] += 1
        for field in TOKEN_FIELDS:
            group["tokens"][field] += int(item.get("tokens", {}).get(field, 0))
        if item.get("costUsd") is not None:
            group["costUsd"] += float(item["costUsd"])
    result = []
    for group in groups.values():
        group["rawTotal"] = sum(group["tokens"].values())
        group["budgetedTotal"] = budgeted_token_total(group["tokens"])
        group["costUsd"] = round(group["costUsd"], 8)
        result.append(group)
    return sorted(result, key=lambda item: item[key])


def _zero_tokens() -> dict[str, int]:
    return {field: 0 for field in TOKEN_FIELDS}
