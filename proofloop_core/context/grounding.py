from __future__ import annotations

import hashlib
import json
import re
import shlex
import uuid
from dataclasses import dataclass
from typing import Optional, Any
from pathlib import Path

from proofloop_core.context.io import read_json
from proofloop_core.context.git_snapshot import _git, changed_source_files


_MAX_INSTRUCTION_BYTES = 1_000_000
_INJECTION_RULES = (
    ("IGNORE_AUTHORITY", re.compile(r"(?:ignore|disregard).{0,80}(?:user|previous|system|instruction)|무시하라", re.I)),
    ("FAKE_TEST_SUCCESS", re.compile(r"(?:mark|report).{0,80}tests?.{0,40}(?:pass|success)|테스트를\s*성공으로\s*표시", re.I)),
    ("UNAUTHORIZED_REMOTE_ACTION", re.compile(r"(?:auto(?:matically)?|without\s+asking).{0,80}(?:push|deploy)|자동으로\s*(?:푸시|배포)", re.I)),
    ("SECRET_EXFILTRATION", re.compile(r"(?:print|reveal|expose).{0,80}(?:secret|token|password)|시스템\s*프롬프트를\s*출력", re.I)),
)

@dataclass(frozen=True)
class GroundedFile:
    path: str
    content_hash: str
    content: Optional[str] = None

@dataclass(frozen=True)
class CommandCatalog:
    tests: tuple[str, ...]
    lint: tuple[str, ...]
    typecheck: tuple[str, ...]
    build: tuple[str, ...]

@dataclass(frozen=True)
class HostCapability:
    can_execute_tests: Optional[bool]
    can_read_logs: Optional[bool]
    can_write_files: Optional[bool]
    can_run_git: Optional[bool]


@dataclass(frozen=True)
class InjectionSignal:
    path: str
    rule_id: str
    content_hash: str

@dataclass(frozen=True)
class GroundingSnapshot:
    snapshot_id: str
    request_id: str
    repo_root: str
    
    git_branch: Optional[str]
    git_head: Optional[str]
    dirty_paths: tuple[str, ...]
    
    instruction_files: tuple[GroundedFile, ...]
    manifests: tuple[GroundedFile, ...]
    relevant_files: tuple[GroundedFile, ...]
    
    detected_commands: CommandCatalog
    detected_languages: tuple[str, ...]
    detected_frameworks: tuple[str, ...]
    detected_test_surfaces: tuple[str, ...]
    
    host_capabilities: HostCapability
    unresolved_questions: tuple[str, ...]
    injection_signals: tuple[InjectionSignal, ...]
    
    tier: str

    def to_dict(self) -> dict[str, Any]:
        def files(values: tuple[GroundedFile, ...]) -> list[dict[str, Any]]:
            return [{"path": item.path, "contentHash": item.content_hash} for item in values]

        return {
            "snapshotId": self.snapshot_id,
            "requestId": self.request_id,
            "repoRoot": self.repo_root,
            "gitBranch": self.git_branch,
            "gitHead": self.git_head,
            "dirtyPaths": list(self.dirty_paths),
            "instructionFiles": files(self.instruction_files),
            "manifests": files(self.manifests),
            "relevantFiles": files(self.relevant_files),
            "detectedCommands": {
                "tests": list(self.detected_commands.tests),
                "lint": list(self.detected_commands.lint),
                "typecheck": list(self.detected_commands.typecheck),
                "build": list(self.detected_commands.build),
            },
            "detectedLanguages": list(self.detected_languages),
            "detectedFrameworks": list(self.detected_frameworks),
            "detectedTestSurfaces": list(self.detected_test_surfaces),
            "hostCapabilities": {
                "canExecuteTests": self.host_capabilities.can_execute_tests,
                "canReadLogs": self.host_capabilities.can_read_logs,
                "canWriteFiles": self.host_capabilities.can_write_files,
                "canRunGit": self.host_capabilities.can_run_git,
            },
            "unresolvedQuestions": list(self.unresolved_questions),
            "injectionSignals": [
                {"path": item.path, "ruleId": item.rule_id, "contentHash": item.content_hash}
                for item in self.injection_signals
            ],
            "tier": self.tier,
        }

def _hash_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()

def _get_grounded_file(repo_root: Path, rel_path: str) -> Optional[GroundedFile]:
    p = (repo_root / rel_path).resolve()
    if (p != repo_root and repo_root not in p.parents) or not p.is_file():
        return None
    return GroundedFile(path=rel_path, content_hash=_hash_file(p), content=None)


def _scan_instruction_file(repo_root: Path, grounded: GroundedFile) -> tuple[InjectionSignal, ...]:
    path = (repo_root / grounded.path).resolve()
    try:
        if path.stat().st_size > _MAX_INSTRUCTION_BYTES:
            return ()
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    return tuple(
        InjectionSignal(path=grounded.path, rule_id=rule_id, content_hash=grounded.content_hash)
        for rule_id, pattern in _INJECTION_RULES
        if pattern.search(text)
    )


def _detected_commands(root: Path) -> CommandCatalog:
    tests: list[str] = []
    lint: list[str] = []
    typecheck: list[str] = []
    build: list[str] = []

    if (root / "scripts" / "run_tests.py").is_file():
        tests.append("python3 scripts/run_tests.py")
    else:
        test_files = list((root / "tests").rglob("test_*.py")) if (root / "tests").is_dir() else []
        if test_files:
            uses_pytest = any("pytest" in path.read_text(encoding="utf-8", errors="ignore") for path in test_files)
            tests.append("python3 -m pytest" if uses_pytest else "python3 -m unittest discover -s tests")

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            scripts = read_json(package_json).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        if isinstance(scripts, dict):
            if isinstance(scripts.get("test"), str):
                tests.append("npm test -- --runInBand")
            if isinstance(scripts.get("lint"), str):
                lint.append("npm run lint")
            if isinstance(scripts.get("typecheck"), str):
                typecheck.append("npm run typecheck")
            if isinstance(scripts.get("build"), str):
                build.append("npm run build")

    makefile = root / "Makefile"
    if makefile.is_file():
        make_text = makefile.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(?m)^lint\s*:", make_text):
            lint.append("make lint")
        if re.search(r"(?m)^typecheck\s*:", make_text):
            typecheck.append("make typecheck")
        if re.search(r"(?m)^build\s*:", make_text):
            build.append("make build")

    def stable(values: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if shlex.split(value)))

    return CommandCatalog(stable(tests), stable(lint), stable(typecheck), stable(build))

def collect_grounding(
    request_id: str,
    repo_root: str | Path,
    tier: str,
    request_text: str,
) -> GroundingSnapshot:
    root = Path(repo_root).resolve()
    
    try:
        git_branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        git_head = _git(root, "rev-parse", "HEAD")
        dirty_paths = tuple(changed_source_files(root, git_head))
    except Exception:
        git_branch = None
        git_head = None
        dirty_paths = ()

    manifest_names = ["package.json", "pyproject.toml", "Cargo.toml", "build.gradle", "pom.xml"]
    manifests = []
    for name in manifest_names:
        gf = _get_grounded_file(root, name)
        if gf:
            manifests.append(gf)

    instr_names = ["AGENTS.md", "CLAUDE.md", "README.md"]
    instrs = []
    injection_signals: list[InjectionSignal] = []
    for name in instr_names:
        gf = _get_grounded_file(root, name)
        if gf:
            instrs.append(gf)
            injection_signals.extend(_scan_instruction_file(root, gf))

    relevant = []
    # Very rudimentary check for relevant files mentioned in request
    # Since we are in T0/T1, we might just look for exact file names
    for word in request_text.split():
        if "/" in word or word.endswith(".py") or word.endswith(".ts") or word.endswith(".md"):
            clean = word.strip(".,;:\"'[]{}()")
            if (root / clean).is_file():
                gf = _get_grounded_file(root, clean)
                if gf:
                    relevant.append(gf)

    # Note: T-4.1 states injection strings treated as data
    # (We just collect them, don't execute or drop the snapshot)
    # The actual enforcement of "repository text is data" will be in the prompt compiler phase,
    # but for now we just make sure we capture things safely.

    return GroundingSnapshot(
        snapshot_id=str(uuid.uuid4()),
        request_id=request_id,
        repo_root=str(root),
        git_branch=git_branch,
        git_head=git_head,
        dirty_paths=dirty_paths,
        instruction_files=tuple(instrs),
        manifests=tuple(manifests),
        relevant_files=tuple(relevant),
        detected_commands=_detected_commands(root),
        detected_languages=(),
        detected_frameworks=(),
        detected_test_surfaces=(),
        host_capabilities=HostCapability(None, None, None, None),
        unresolved_questions=(),
        injection_signals=tuple(injection_signals),
        tier=tier,
    )

def is_grounding_stale(snapshot: GroundingSnapshot, repo_root: str | Path) -> bool:
    root = Path(repo_root).resolve()
    try:
        current_head = _git(root, "rev-parse", "HEAD")
        current_dirty = tuple(changed_source_files(root, current_head))
    except Exception:
        return True
    
    if current_head != snapshot.git_head:
        return True
    if current_dirty != snapshot.dirty_paths:
        return True
        
    return False
