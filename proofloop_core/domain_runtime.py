from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from .io import write_json
from .skill_registry import _satisfies_version


_SKIP_DIRS = {".git", ".proofloop", "node_modules", ".venv", "venv", "dist", "build", "vendor"}
_BACKEND = re.compile(r"\b(api|backend|server|endpoint|route|controller|service|database|model|migration|command handler|response compatibility|django|spring boot|ghost admin)\b|백엔드|서버|엔드포인트|데이터베이스|커맨드 핸들러", re.I)
_FRONTEND = re.compile(r"\b(frontend|ui|component|page|react|vue|svelte|css|browser|analytics event|keyboard navigation|dialog|loading and error state|retry button|posthog)\b|프론트엔드|화면|컴포넌트|페이지|키보드 탐색|다이얼로그", re.I)
_DEVOPS = re.compile(r"\b(devops|ci|cd|deploy|deployment|workflow|github actions|kubernetes|k8s|gitops|manifest|infrastructure|promotion|rollback)\b|데브옵스|배포|워크플로|쿠버네티스|인프라|롤백|프로모션", re.I)
_TEST = re.compile(r"\b(tests?|testing|pytest|jest|junit|coverage|tdd|regression)\b|테스트|검증|회귀", re.I)
_REVIEW = re.compile(r"\b(review|audit|inspect|quality|intent alignment|overbuild)\b|리뷰|감사|검토|품질|의도 정렬|과잉 구현", re.I)
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}")


def build_repository_fingerprint(
    repository: str | Path,
    request: str,
    targets: tuple[str, ...] = (),
) -> dict[str, Any]:
    root = Path(repository).resolve()
    if not root.is_dir():
        raise ValueError(f"repository does not exist: {root}")
    languages: set[str] = set()
    frameworks: dict[str, str] = {}
    package_managers: set[str] = set()
    signals: set[str] = set()
    verifiers: set[str] = set()
    config_files: list[str] = []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        languages.add("python")
        config_files.append("pyproject.toml")
        package_managers.add("python")
        _read_python_dependencies(pyproject, frameworks)
        verifiers.add("python -m unittest")
    for requirement in sorted(root.glob("requirements*.txt")):
        if requirement.is_file() and requirement.stat().st_size <= 512_000:
            languages.add("python")
            config_files.append(requirement.relative_to(root).as_posix())
            _read_requirement_lines(requirement.read_text(encoding="utf-8", errors="replace").splitlines(), frameworks)

    package_json = root / "package.json"
    if package_json.is_file():
        languages.add("javascript")
        config_files.append("package.json")
        package_managers.add(_node_package_manager(root))
        _read_node_dependencies(package_json, frameworks, verifiers)
        if (root / "tsconfig.json").is_file():
            languages.add("typescript")
            config_files.append("tsconfig.json")

    pom = root / "pom.xml"
    if pom.is_file():
        languages.add("java")
        package_managers.add("maven")
        config_files.append("pom.xml")
        text = _bounded_text(pom)
        if "spring-boot" in text:
            frameworks["spring"] = _xml_property_version(text, "spring-boot.version") or _first_version(text) or "0.0.0"
        if "junit" in text.casefold():
            frameworks["junit"] = _dependency_version(text, "junit") or "0.0.0"
        verifiers.add("./mvnw test" if (root / "mvnw").is_file() else "mvn test")

    go_mod = root / "go.mod"
    if go_mod.is_file():
        languages.add("go")
        package_managers.add("go")
        config_files.append("go.mod")
        text = _bounded_text(go_mod)
        if "sigs.k8s.io/kustomize" in text:
            frameworks["kustomize"] = _module_version(text, "sigs.k8s.io/kustomize")
        if "github.com/fluxcd/" in text:
            frameworks["flux"] = _module_version(text, "github.com/fluxcd/")
        verifiers.add("go test ./...")

    workflow_root = root / ".github" / "workflows"
    if workflow_root.is_dir() and any(path.is_file() for path in workflow_root.glob("*.y*ml")):
        languages.add("yaml")
        signals.add("delivery:github-actions")
        signals.add("path:.github/workflows")
        config_files.append(".github/workflows")

    kustomizations = _find_named(root, {"kustomization.yaml", "kustomization.yml"})
    if kustomizations:
        languages.add("yaml")
        frameworks.setdefault("kustomize", _command_version("kustomize"))
        signals.add("framework:kustomize")
        signals.add("delivery:kubernetes")
        config_files.extend(kustomizations[:20])
        if shutil.which("kustomize"):
            verifiers.add("kustomize build")

    if (root / "clusters").is_dir() or (root / "flux-system").is_dir():
        signals.add("framework:flux")
        signals.add("delivery:gitops")
        frameworks.setdefault("flux", _command_version("flux"))

    safe_targets: list[str] = []
    for target in targets:
        candidate = (root / target).resolve()
        if candidate.is_file() and root in candidate.parents:
            relative = candidate.relative_to(root).as_posix()
            safe_targets.append(relative)
            _language_from_suffix(candidate.suffix, languages)

    for name in frameworks:
        signals.add(f"framework:{name}")
    for manager in package_managers:
        signals.add(f"package-manager:{manager}")

    joined_targets = "\n".join(safe_targets)
    if re.search(r"(?:^|/)(?:api|routes?|controllers?|schemas?|proto)(?:/|\.|$)", joined_targets, re.I):
        signals.add("surface:public-contract")
    if re.search(r"(?:^|/)(?:db|database|models?|migrations?|storage)(?:/|\.|$)", joined_targets, re.I):
        signals.add("surface:persistent-state")
    if re.search(r"auth|permission|security|secret", request + "\n" + joined_targets, re.I):
        signals.add("surface:security")

    task_types = classify_task_types(request)
    payload: dict[str, Any] = {
        "schemaVersion": "1.0",
        "repository": str(root),
        "taskTypes": list(task_types),
        "languages": sorted(languages),
        "frameworks": dict(sorted(frameworks.items())),
        "packageManagers": sorted(package_managers),
        "signals": sorted(signals),
        "verifiers": sorted(verifiers),
        "configFiles": sorted(dict.fromkeys(config_files)),
        "targets": safe_targets,
    }
    stable = {key: value for key, value in payload.items() if key != "repository"}
    payload["fingerprintSha256"] = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return payload


def select_reference_slices(
    pack_root: str | Path,
    fingerprint: dict[str, Any],
    *,
    max_tokens: int,
) -> dict[str, Any]:
    root = Path(pack_root).resolve()
    if max_tokens <= 0:
        raise ValueError("context budget must be positive")
    signals = {str(value) for value in fingerprint.get("signals", [])}
    frameworks = {
        str(name).casefold(): str(version)
        for name, version in (fingerprint.get("frameworks") or {}).items()
    }
    task_types = {str(value) for value in fingerprint.get("taskTypes", [])}
    adapter_ids: list[str] = []
    adapter_path = root / "adapters" / "index.json"
    if adapter_path.is_file():
        adapter_index = _load_index(adapter_path, "adapters")
        for adapter in adapter_index["adapters"]:
            adapter_id = _entry_string(adapter, "id", adapter_path)
            required_signals = {str(value) for value in adapter.get("signals", [])}
            if required_signals and not required_signals.issubset(signals):
                continue
            framework = adapter.get("framework")
            if framework is not None:
                if not isinstance(framework, dict):
                    raise ValueError(f"{adapter_path}: adapter framework must be an object")
                name = _entry_string(framework, "name", adapter_path).casefold()
                version_range = str(framework.get("range", "*"))
                if name not in frameworks or not _satisfies_version(frameworks[name], version_range):
                    continue
            adapter_ids.append(adapter_id)

    reference_path = root / "references" / "index.json"
    if not reference_path.is_file():
        return {"schemaVersion": "1.0", "adapters": adapter_ids, "slices": [], "estimatedTokens": 0}
    reference_index = _load_index(reference_path, "slices")
    selected: list[dict[str, Any]] = []
    estimated_total = 0
    for item in reference_index["slices"]:
        slice_id = _entry_string(item, "id", reference_path)
        adapter = item.get("adapter")
        required_tasks = {str(value) for value in item.get("taskTypes", [])}
        required_signals = {str(value) for value in item.get("signals", [])}
        active = bool(item.get("always"))
        active = active or (isinstance(adapter, str) and adapter in adapter_ids)
        active = active or (bool(required_tasks) and bool(required_tasks.intersection(task_types)))
        if not active:
            continue
        if required_signals and not required_signals.issubset(signals):
            continue
        relative = _entry_string(item, "path", reference_path)
        resolved = _confined_file(root, relative)
        estimate = item.get("estimatedTokens")
        if not isinstance(estimate, int) or isinstance(estimate, bool) or estimate <= 0:
            raise ValueError(f"{reference_path}: slice {slice_id} needs positive estimatedTokens")
        estimated_total += estimate
        if estimated_total > max_tokens:
            raise ValueError(f"{root}: selected references exceed context budget {max_tokens}")
        selected.append({"id": slice_id, "path": str(resolved), "estimatedTokens": estimate})
    return {
        "schemaVersion": "1.0",
        "adapters": adapter_ids,
        "slices": selected,
        "estimatedTokens": estimated_total,
    }


def run_pack_helper(
    pack_root: str | Path,
    helper_path: str,
    repository: str | Path,
    output_path: str | Path,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("helper timeout must be positive")
    root = Path(pack_root).resolve()
    helper = _confined_file(root, helper_path)
    if helper.is_symlink():
        raise ValueError(f"helper symlink is forbidden: {helper}")
    if not os.access(helper, os.X_OK):
        raise ValueError(f"helper is not executable: {helper}")
    repo = Path(repository).resolve()
    if not repo.is_dir():
        raise ValueError(f"repository does not exist: {repo}")
    try:
        completed = subprocess.run(
            [str(helper), "--repo", str(repo)],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"domain helper timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        tail = completed.stderr[-2000:] if completed.stderr else completed.stdout[-2000:]
        raise RuntimeError(f"domain helper failed with exit {completed.returncode}: {tail}")
    try:
        artifact = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("domain helper stdout must be one JSON document") from exc
    if not isinstance(artifact, dict):
        raise ValueError("domain helper JSON must be an object")
    destination = Path(output_path)
    write_json(destination, artifact)
    return {
        "schemaVersion": "1.0",
        "artifactOwner": "PARENT_PROCESS",
        "artifact": str(destination.resolve()),
        "helper": str(helper),
        "helperSha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
        "exitCode": completed.returncode,
    }


def classify_task_types(request: str) -> tuple[str, ...]:
    result: list[str] = []
    for name, pattern in (
        ("backend-development", _BACKEND),
        ("frontend-development", _FRONTEND),
        ("devops-delivery", _DEVOPS),
        ("test-engineering", _TEST),
        ("code-review", _REVIEW),
    ):
        if pattern.search(request):
            result.append(name)
    return tuple(result)


def _read_python_dependencies(path: Path, frameworks: dict[str, str]) -> None:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return
    dependencies: list[str] = []
    project = raw.get("project")
    if isinstance(project, dict) and isinstance(project.get("dependencies"), list):
        dependencies.extend(str(value) for value in project["dependencies"])
    poetry = ((raw.get("tool") or {}).get("poetry") if isinstance(raw.get("tool"), dict) else None)
    if isinstance(poetry, dict) and isinstance(poetry.get("dependencies"), dict):
        dependencies.extend(f"{name}{value}" for name, value in poetry["dependencies"].items())
    _read_requirement_lines(dependencies, frameworks)


def _read_requirement_lines(lines: list[str], frameworks: dict[str, str]) -> None:
    for line in lines:
        value = line.strip()
        match = re.match(r"(?i)^django(?:\[[^]]+\])?\s*(?:==|~=|>=)?\s*([0-9][0-9.]*)", value)
        if match:
            frameworks["django"] = _normalize_version(match.group(1))
        pytest_match = re.match(r"(?i)^pytest(?:-[a-z0-9-]+)?\s*(?:==|~=|>=)?\s*([0-9][0-9.]*)", value)
        if pytest_match:
            frameworks["pytest"] = _normalize_version(pytest_match.group(1))


def _read_node_dependencies(path: Path, frameworks: dict[str, str], verifiers: set[str]) -> None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    dependencies: dict[str, Any] = {}
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        value = raw.get(field)
        if isinstance(value, dict):
            dependencies.update(value)
    for package, framework in (
        ("react", "react"),
        ("next", "next"),
        ("vue", "vue"),
        ("@angular/core", "angular"),
        ("svelte", "svelte"),
        ("jest", "jest"),
    ):
        if package in dependencies:
            frameworks[framework] = _normalize_version(str(dependencies[package]))
    package_name = str(raw.get("name", "")).casefold()
    ghost_versions = [
        str(version)
        for name, version in dependencies.items()
        if str(name).casefold().startswith("@tryghost/")
    ]
    if package_name == "ghost" or ghost_versions:
        frameworks["ghost"] = _normalize_version(ghost_versions[0] if ghost_versions else str(raw.get("version", "0.0.0")))
    scripts = raw.get("scripts")
    if isinstance(scripts, dict):
        for name in ("test", "lint", "typecheck", "build"):
            if name in scripts:
                verifiers.add(f"npm run {name}")


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "bun.lockb").is_file() or (root / "bun.lock").is_file():
        return "bun"
    return "npm"


def _find_named(root: Path, names: set[str], limit: int = 2000) -> list[str]:
    found: list[str] = []
    visited = 0
    for current, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in _SKIP_DIRS)
        for name in sorted(files):
            visited += 1
            if name in names:
                found.append((Path(current) / name).relative_to(root).as_posix())
            if visited >= limit:
                return found
    return found


def _language_from_suffix(suffix: str, languages: set[str]) -> None:
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    if suffix.casefold() in mapping:
        languages.add(mapping[suffix.casefold()])


def _bounded_text(path: Path, limit: int = 512_000) -> str:
    with path.open("rb") as handle:
        return handle.read(limit).decode("utf-8", errors="replace")


def _xml_property_version(text: str, name: str) -> str | None:
    match = re.search(rf"<{re.escape(name)}>\s*([^<]+)\s*</{re.escape(name)}>", text)
    return _normalize_version(match.group(1)) if match else None


def _dependency_version(text: str, name: str) -> str | None:
    pattern = rf"<artifactId>[^<]*{re.escape(name)}[^<]*</artifactId>[\s\S]{{0,300}}?<version>\s*([^<]+)\s*</version>"
    match = re.search(pattern, text, re.I)
    return _normalize_version(match.group(1)) if match else None


def _first_version(text: str) -> str | None:
    match = _VERSION.search(text)
    return _normalize_version(match.group(0)) if match else None


def _module_version(text: str, module_prefix: str) -> str:
    match = re.search(rf"{re.escape(module_prefix)}[^\s]*\s+v?([0-9]+(?:\.[0-9]+){{0,2}})", text)
    return _normalize_version(match.group(1)) if match else "0.0.0"


def _command_version(command: str) -> str:
    binary = shutil.which(command)
    if not binary:
        return "0.0.0"
    try:
        completed = subprocess.run([binary, "version", "--short"], text=True, capture_output=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "0.0.0"
    return _normalize_version(completed.stdout or completed.stderr)


def _normalize_version(value: str) -> str:
    match = _VERSION.search(value)
    if not match:
        return "0.0.0"
    parts = match.group(0).split(".")
    return ".".join((*parts, *("0" for _ in range(3 - len(parts)))))


def _load_index(path: Path, collection: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON") from exc
    if not isinstance(raw, dict) or raw.get("schemaVersion") != "1.0" or not isinstance(raw.get(collection), list):
        raise ValueError(f"{path}: invalid {collection} index")
    if any(not isinstance(item, dict) for item in raw[collection]):
        raise ValueError(f"{path}: {collection} entries must be objects")
    return raw


def _entry_string(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {key} must be a non-empty string")
    return value.strip()


def _confined_file(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute():
        raise ValueError(f"{relative}: absolute pack path is forbidden")
    candidate = root / value
    if candidate.is_symlink():
        raise ValueError(f"{relative}: symlink is forbidden")
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"{relative}: path escapes pack root")
    if not resolved.is_file():
        raise ValueError(f"{relative}: pack file does not exist")
    return resolved
