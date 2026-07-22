from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from proofloop_core.context.io import read_json as _read_json


_STATUSES = {"EXPERIMENTAL", "CANARY", "VERIFIED", "DEFAULT", "STALE", "QUARANTINED"}
_KINDS = {"PROCESS_PROTOCOL", "DOMAIN_PACK"}
_EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3", "E4"}
_AUTHORITIES = {"MODEL_CLAIM", "MODEL_REVIEW", "STATIC_INSPECTION", "DIFF_GUARD", "DETERMINISTIC_CHECK", "EXTERNAL_OBSERVATION"}
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
_MAX_BUNDLE_FILES = 256
_MAX_BUNDLE_FILE_BYTES = 2 * 1024 * 1024
_MAX_BUNDLE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class SkillContract:
    name: str
    version: str
    status: str
    kind: str
    modes: tuple[str, ...]
    task_types: tuple[str, ...]
    positive_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    hosts: tuple[str, ...]
    tiers: tuple[str, ...]
    languages: tuple[str, ...]
    frameworks: tuple[tuple[str, str], ...]
    required_tools: tuple[tuple[str, str], ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    closes: tuple[str, ...]
    adds: tuple[str, ...]
    minimum_authority: str
    self_closure_allowed: bool
    required_context: tuple[str, ...]
    max_injected_tokens: int
    max_tokens: int
    max_seconds: int
    max_invocations: int
    completion_artifact: str
    completion_schema: str | None
    escalation_on: tuple[str, ...]
    license: str
    provenance: tuple[str, ...]
    evidence_level: str
    evidence_valid_until: datetime | None
    scorecard: str | None
    content_hash: str
    root: Path

    @property
    def evidence_expired(self) -> bool:
        return self.evidence_valid_until is not None and self.evidence_valid_until <= datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "name": self.name,
            "version": self.version,
            "status": "STALE" if self.evidence_expired and self.status not in {"QUARANTINED", "STALE"} else self.status,
            "kind": self.kind,
            "activation": {
                "modes": list(self.modes),
                "taskTypes": list(self.task_types),
                "positiveSignals": list(self.positive_signals),
                "negativeSignals": list(self.negative_signals),
            },
            "compatibility": {
                "hosts": list(self.hosts),
                "tiers": list(self.tiers),
                "languages": list(self.languages),
                "frameworks": [
                    {"name": name, "range": version_range}
                    for name, version_range in self.frameworks
                ],
                "requiredTools": [
                    {"name": name, "range": version_range}
                    for name, version_range in self.required_tools
                ],
            },
            "dependencies": list(self.dependencies),
            "conflicts": list(self.conflicts),
            "proof": {
                "closes": list(self.closes),
                "adds": list(self.adds),
                "minimumAuthority": self.minimum_authority,
                "selfClosureAllowed": self.self_closure_allowed,
            },
            "minimumAuthority": self.minimum_authority,
            "requiredContext": list(self.required_context),
            "context": {
                "required": list(self.required_context),
                "maxInjectedTokens": self.max_injected_tokens,
            },
            "budget": {
                "maxTokens": self.max_tokens,
                "maxSeconds": self.max_seconds,
                "maxInvocations": self.max_invocations,
            },
            "completionArtifact": self.completion_artifact,
            "completion": {
                "artifact": self.completion_artifact,
                "schema": self.completion_schema,
            },
            "escalationOn": list(self.escalation_on),
            "source": {
                "license": self.license,
                "provenance": list(self.provenance),
            },
            "evaluation": {
                "evidenceLevel": self.evidence_level,
                "validUntil": _format_timestamp(self.evidence_valid_until),
                "scorecard": self.scorecard,
            },
            "bundleSha256": self.content_hash,
            "contentHash": self.content_hash,
        }


@dataclass(frozen=True)
class ResolutionContext:
    mode: str
    host: str
    tier: str
    open_obligations: tuple[str, ...]
    remaining_tokens: int
    task_type: str | None = None
    repository_signals: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    frameworks: tuple[tuple[str, str], ...] = ()
    tools: tuple[tuple[str, str], ...] = ()
    allow_experimental_domains: bool = False


class SkillRegistry:
    def __init__(self, skills: list[SkillContract]):
        self.skills = sorted(skills, key=lambda item: item.name)
        self._by_name = {skill.name: skill for skill in self.skills}
        if len(self._by_name) != len(self.skills):
            raise ValueError("duplicate protocol id")
        self._validate_dependencies()

    @classmethod
    def discover(cls, root: str | Path) -> "SkillRegistry":
        base = Path(root)
        contracts = [_load_contract(path) for path in sorted(base.glob("*/proofloop.skill.json"))]
        return cls(contracts)

    def resolve(self, context: ResolutionContext) -> list[SkillContract]:
        obligations = set(context.open_obligations)
        priority = {
            "proofloop-intent": 0,
            "proofloop-design": 1,
            "proofloop-plan": 2,
            "proofloop-implement": 3,
            "proofloop-debug": 4,
            "proofloop-review": 5,
            "proofloop-verify": 6,
        }
        candidates = {
            skill.name: skill
            for skill in self.skills
            if _eligible(skill, context, obligations)
        }
        selected: list[SkillContract] = []
        selected_names: set[str] = set()
        reserved = 0

        def add_with_dependencies(skill: SkillContract, stack: tuple[str, ...] = ()) -> bool:
            nonlocal reserved
            if skill.name in selected_names:
                return True
            if skill.name in stack:
                return False
            dependencies: list[SkillContract] = []
            for dependency_name in skill.dependencies:
                dependency = self._by_name.get(dependency_name)
                if dependency is None or not _compatible(dependency, context):
                    return False
                dependencies.append(dependency)
            required = [item for item in dependencies if item.name not in selected_names]
            required.append(skill)
            incremental_tokens = sum(item.max_tokens for item in required if item.name not in selected_names)
            if reserved + incremental_tokens > context.remaining_tokens:
                return False
            conflict_names = {item.name for item in selected}
            for item in required:
                if conflict_names.intersection(item.conflicts) or any(item.name in other.conflicts for other in selected):
                    return False
            for dependency in dependencies:
                if not add_with_dependencies(dependency, (*stack, skill.name)):
                    return False
            if any(other.name in skill.conflicts or skill.name in other.conflicts for other in selected):
                return False
            if skill.name not in selected_names:
                selected.append(skill)
                selected_names.add(skill.name)
                reserved += skill.max_tokens
            return True

        for skill in sorted(candidates.values(), key=lambda item: (priority.get(item.name, 100), item.name)):
            add_with_dependencies(skill)
        return selected

    def to_dict(self) -> dict[str, Any]:
        return {"schemaVersion": "2.0", "skills": [item.to_dict() for item in self.skills]}

    def _validate_dependencies(self) -> None:
        for skill in self.skills:
            for dependency in skill.dependencies:
                if dependency not in self._by_name:
                    raise ValueError(f"{skill.name}: missing dependency {dependency}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str, path: tuple[str, ...]) -> None:
            if name in visiting:
                chain = " -> ".join((*path, name))
                raise ValueError(f"dependency cycle: {chain}")
            if name in visited:
                return
            visiting.add(name)
            for dependency in self._by_name[name].dependencies:
                visit(dependency, (*path, name))
            visiting.remove(name)
            visited.add(name)

        for name in sorted(self._by_name):
            visit(name, ())


def _eligible(skill: SkillContract, context: ResolutionContext, obligations: set[str]) -> bool:
    if not _compatible(skill, context):
        return False
    if skill.kind == "PROCESS_PROTOCOL" and not obligations.intersection((*skill.closes, *skill.adds)):
        return False
    if skill.kind == "DOMAIN_PACK" and not skill.task_types and not skill.positive_signals:
        return False
    if skill.task_types and context.task_type not in skill.task_types:
        return False
    signals = set(context.repository_signals)
    if skill.negative_signals and signals.intersection(skill.negative_signals):
        return False
    if skill.positive_signals and not signals.intersection(skill.positive_signals):
        return False
    return True


def _compatible(skill: SkillContract, context: ResolutionContext) -> bool:
    if skill.status in {"QUARANTINED", "STALE"} or skill.evidence_expired:
        return False
    if skill.kind == "DOMAIN_PACK" and skill.status == "EXPERIMENTAL" and not context.allow_experimental_domains:
        return False
    if context.mode not in skill.modes or context.host not in skill.hosts or context.tier not in skill.tiers:
        return False
    if skill.max_tokens > context.remaining_tokens:
        return False
    if skill.languages and not set(value.casefold() for value in context.languages).intersection(
        value.casefold() for value in skill.languages
    ):
        return False
    if not _requirements_match(skill.frameworks, context.frameworks):
        return False
    if not _requirements_match(skill.required_tools, context.tools):
        return False
    return True


def _requirements_match(requirements: tuple[tuple[str, str], ...], observed: tuple[tuple[str, str], ...]) -> bool:
    available = {name.casefold(): version for name, version in observed}
    return all(
        name.casefold() in available and _satisfies_version(available[name.casefold()], version_range)
        for name, version_range in requirements
    )


def _satisfies_version(version: str, version_range: str) -> bool:
    actual = _version_tuple(version)
    if not version_range.strip() or version_range.strip() == "*":
        return True
    for condition in version_range.split():
        match = re.fullmatch(r"(>=|<=|>|<|=)?\s*([0-9]+(?:\.[0-9]+){0,2})", condition)
        if not match:
            return False
        operator = match.group(1) or "="
        expected = _version_tuple(match.group(2))
        if operator == ">=" and not actual >= expected:
            return False
        if operator == "<=" and not actual <= expected:
            return False
        if operator == ">" and not actual > expected:
            return False
        if operator == "<" and not actual < expected:
            return False
        if operator == "=" and not actual == expected:
            return False
    return True


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?", value.strip())
    if not match:
        return (-1, -1, -1)
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def _load_contract(path: Path) -> SkillContract:
    try:
        raw = _read_json(path)
    except (ValueError, OSError) as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    required = (
        "schemaVersion",
        "id",
        "version",
        "status",
        "kind",
        "source",
        "activation",
        "compatibility",
        "dependencies",
        "conflicts",
        "proof",
        "context",
        "budget",
        "completion",
        "escalation",
        "evaluation",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"{path}: missing fields: {', '.join(missing)}")
    if raw["schemaVersion"] != "2.0":
        raise ValueError(f"{path}: unsupported schemaVersion {raw['schemaVersion']}")
    name = _required_string(raw, "id", path)
    if name != path.parent.name:
        raise ValueError(f"{path}: id must match directory name")
    version = _required_string(raw, "version", path)
    if not _SEMVER.fullmatch(version):
        raise ValueError(f"{path}: invalid semantic version {version}")
    status = _required_string(raw, "status", path)
    if status not in _STATUSES:
        raise ValueError(f"{path}: unsupported status {status}")
    kind = _required_string(raw, "kind", path)
    if kind not in _KINDS:
        raise ValueError(f"{path}: unsupported kind {kind}")
    skill_md = path.parent / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"{path}: SKILL.md is required")

    source = _mapping(raw, "source", path)
    activation = _mapping(raw, "activation", path)
    compatibility = _mapping(raw, "compatibility", path)
    proof = _mapping(raw, "proof", path)
    context = _mapping(raw, "context", path)
    budget = _mapping(raw, "budget", path)
    completion = _mapping(raw, "completion", path)
    escalation = _mapping(raw, "escalation", path)
    evaluation = _mapping(raw, "evaluation", path)
    evidence_level = str(evaluation.get("evidenceLevel", ""))
    if evidence_level not in _EVIDENCE_LEVELS:
        raise ValueError(f"{path}: unsupported evidence level {evidence_level}")
    valid_until = _parse_timestamp(evaluation.get("validUntil"), path)
    scorecard = _optional_string(evaluation.get("scorecard"), path, "evaluation.scorecard")
    if status in {"VERIFIED", "DEFAULT"}:
        if evidence_level not in {"E2", "E3", "E4"} or not scorecard:
            raise ValueError(f"{path}: {status} requires E2+ evidence and a scorecard")
        if valid_until is None:
            raise ValueError(f"{path}: {status} requires evaluation.validUntil")
        scorecard_path = _bundle_member(path.parent, scorecard, "scorecard")
        try:
            scorecard_payload = _read_json(scorecard_path)
        except (ValueError, OSError) as exc:
            raise ValueError(f"{path}: scorecard must be valid JSON") from exc
        if not isinstance(scorecard_payload, dict) or scorecard_payload.get("schemaVersion") != "1.0":
            raise ValueError(f"{path}: scorecard requires schemaVersion 1.0")

    minimum_authority = proof.get("minimumAuthority")
    if not isinstance(minimum_authority, str) or minimum_authority not in _AUTHORITIES:
        raise ValueError(f"{path}: unsupported proof authority {minimum_authority!r}")
    self_closure_allowed = proof.get("selfClosureAllowed")
    if not isinstance(self_closure_allowed, bool):
        raise ValueError(f"{path}: proof.selfClosureAllowed must be boolean")

    return SkillContract(
        name=name,
        version=version,
        status=status,
        kind=kind,
        modes=_string_tuple(activation.get("modes"), path, "activation.modes"),
        task_types=_string_tuple(activation.get("taskTypes", []), path, "activation.taskTypes"),
        positive_signals=_string_tuple(activation.get("positiveSignals", []), path, "activation.positiveSignals"),
        negative_signals=_string_tuple(activation.get("negativeSignals", []), path, "activation.negativeSignals"),
        hosts=_string_tuple(compatibility.get("hosts"), path, "compatibility.hosts"),
        tiers=_string_tuple(compatibility.get("tiers"), path, "compatibility.tiers"),
        languages=_string_tuple(compatibility.get("languages", []), path, "compatibility.languages"),
        frameworks=_requirements(compatibility.get("frameworks", []), path, "compatibility.frameworks"),
        required_tools=_requirements(compatibility.get("requiredTools", []), path, "compatibility.requiredTools"),
        dependencies=_string_tuple(raw["dependencies"], path, "dependencies"),
        conflicts=_string_tuple(raw["conflicts"], path, "conflicts"),
        closes=_string_tuple(proof.get("closes", []), path, "proof.closes"),
        adds=_string_tuple(proof.get("adds", []), path, "proof.adds"),
        minimum_authority=minimum_authority,
        self_closure_allowed=self_closure_allowed,
        required_context=_string_tuple(context.get("required"), path, "context.required"),
        max_injected_tokens=_positive_int(context.get("maxInjectedTokens"), path, "context.maxInjectedTokens"),
        max_tokens=_positive_int(budget.get("maxTokens"), path, "budget.maxTokens"),
        max_seconds=_positive_int(budget.get("maxSeconds"), path, "budget.maxSeconds"),
        max_invocations=_positive_int(budget.get("maxInvocations"), path, "budget.maxInvocations"),
        completion_artifact=_required_string(completion, "artifact", path),
        completion_schema=_optional_string(completion.get("schema"), path, "completion.schema"),
        escalation_on=_string_tuple(escalation.get("on"), path, "escalation.on"),
        license=_required_string(source, "license", path),
        provenance=_string_tuple(source.get("provenance"), path, "source.provenance"),
        evidence_level=evidence_level,
        evidence_valid_until=valid_until,
        scorecard=scorecard,
        content_hash=_bundle_hash(path.parent),
        root=path.parent,
    )


def _bundle_hash(root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    total_bytes = 0
    for candidate in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if candidate.is_symlink():
            raise ValueError(f"{candidate}: symlink is forbidden in protocol bundle")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError(f"{candidate}: non-regular bundle entry")
        size = candidate.stat().st_size
        if size > _MAX_BUNDLE_FILE_BYTES:
            raise ValueError(f"{candidate}: bundle file exceeds size limit")
        total_bytes += size
        if total_bytes > _MAX_BUNDLE_BYTES:
            raise ValueError(f"{root}: bundle exceeds total size limit")
        files.append(candidate)
    if len(files) > _MAX_BUNDLE_FILES:
        raise ValueError(f"{root}: bundle exceeds file count limit")
    for candidate in files:
        relative = candidate.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = candidate.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _bundle_member(root: Path, relative: str, label: str) -> Path:
    value = Path(relative)
    if value.is_absolute():
        raise ValueError(f"{root}: {label} path must be relative")
    candidate = root / value
    if candidate.is_symlink():
        raise ValueError(f"{root}: {label} symlink is forbidden")
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved_root != resolved and resolved_root not in resolved.parents:
        raise ValueError(f"{root}: {label} path escapes bundle")
    if not resolved.is_file():
        raise ValueError(f"{root}: {label} file does not exist: {relative}")
    return resolved


def _mapping(raw: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: {key} must be an object")
    return value


def _required_string(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {key} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {field} must be null or a non-empty string")
    return value.strip()


def _string_tuple(value: Any, path: Path, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path}: {field} must be an array of non-empty strings")
    return tuple(item.strip() for item in value)


def _requirements(value: Any, path: Path, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path}: {field} must be an array")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: {field} entries must be objects")
        name = item.get("name")
        version_range = item.get("range", "*")
        if not isinstance(name, str) or not name.strip() or not isinstance(version_range, str):
            raise ValueError(f"{path}: invalid {field} entry")
        result.append((name.strip(), version_range.strip()))
    return tuple(result)


def _positive_int(value: Any, path: Path, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{path}: {field} must be a positive integer")
    return value


def _parse_timestamp(value: Any, path: Path) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path}: evaluation.validUntil must be an ISO timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path}: invalid evaluation.validUntil") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path}: evaluation.validUntil must include timezone")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
