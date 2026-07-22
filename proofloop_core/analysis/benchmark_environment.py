from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any


_PYTEST_COUNT = re.compile(r"(?P<count>\d+)\s+(?P<kind>passed|failed|skipped|errors?|xfailed|xpassed)")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def parse_test_output(output: str, *, exit_code: int) -> dict[str, Any]:
    clean = _ANSI.sub("", output)
    summaries = [
        line
        for line in clean.splitlines()
        if " in " in line and any(word in line for word in (" passed", " failed", " error", " skipped"))
    ]
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    if summaries:
        for match in _PYTEST_COUNT.finditer(summaries[-1]):
            kind = match.group("kind")
            if kind == "error":
                kind = "errors"
            if kind in counts:
                counts[kind] = int(match.group("count"))
    total = sum(counts.values())
    pass_rate = counts["passed"] / total if total else 0.0
    return {
        "taskPassed": exit_code == 0 and total > 0 and counts["passed"] == total,
        "testsTotal": total,
        "testsPassed": counts["passed"],
        "testsFailed": counts["failed"] + counts["errors"],
        "testsSkipped": counts["skipped"],
        "testPassRate": pass_rate,
    }


def materialize_repository(task: dict[str, Any], target: str | Path) -> Path:
    repository = task.get("repository")
    if not isinstance(repository, dict):
        raise ValueError("SWE task requires repository metadata")
    url = repository.get("url")
    commit = repository.get("commit")
    if not isinstance(url, str) or not url or not isinstance(commit, str) or len(commit) != 40:
        raise ValueError("SWE repository requires a URL and full commit")
    destination = Path(target).resolve()
    if destination.exists():
        raise ValueError(f"trial repository already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(destination)])
    _run(["git", "fetch", "--depth", "1", "origin", commit], cwd=destination)
    _run(["git", "checkout", "--detach", commit], cwd=destination)
    observed = _run(["git", "rev-parse", "HEAD"], cwd=destination).stdout.strip()
    if observed != commit:
        raise RuntimeError(f"repository commit mismatch: expected {commit}, observed {observed}")
    return destination


def preflight_swe_environment(
    suite: dict[str, Any],
    upstream_root: str | Path,
    *,
    docker_binary: str = "docker",
    pull_images: bool = False,
) -> dict[str, Any]:
    upstream = Path(upstream_root).resolve()
    raw_source = suite.get("source")
    source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
    expected_commit = source.get("commit")
    docker = _run([docker_binary, "info", "--format", "{{.ServerVersion}}"], check=False)
    observed_commit = _run(["git", "rev-parse", "HEAD"], cwd=upstream, check=False).stdout.strip()
    config_path = upstream / "config" / "benchmark_config.yaml"
    observed_config_hash = _hash_file(config_path) if config_path.is_file() else None
    expected_config_hash = source.get("configHash")
    tasks: list[dict[str, Any]] = []
    image_status: dict[str, str] = {}
    raw_tasks = suite.get("tasks")
    for task in raw_tasks if isinstance(raw_tasks, list) else []:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id", ""))
        test_path = _safe_upstream_path(upstream, task.get("upstreamTest"))
        skill_path = _safe_upstream_path(upstream, task.get("skillDocument"))
        image = task.get("dockerImage")
        failures: list[str] = []
        if not test_path.is_file():
            failures.append("TEST_MISSING")
        if not skill_path.is_file():
            failures.append("SKILL_MISSING")
        test_hash = _hash_file(test_path) if test_path.is_file() else None
        skill_hash = _hash_file(skill_path) if skill_path.is_file() else None
        expected_test_hash = task.get("testDocumentHash")
        if expected_test_hash and test_hash != expected_test_hash:
            failures.append("TEST_HASH_MISMATCH")
        expected_skill_hash = task.get("skillDocumentHash")
        if expected_skill_hash and skill_hash != expected_skill_hash:
            failures.append("SKILL_HASH_MISMATCH")
        if not isinstance(image, str) or not image:
            failures.append("IMAGE_MISSING")
        elif image not in image_status:
            inspected = _run([docker_binary, "image", "inspect", image], check=False)
            if inspected.returncode == 0:
                image_status[image] = "AVAILABLE"
            elif pull_images:
                pulled = _run([docker_binary, "pull", image], check=False)
                image_status[image] = "AVAILABLE" if pulled.returncode == 0 else "UNAVAILABLE"
            else:
                image_status[image] = "UNAVAILABLE"
        if isinstance(image, str) and image_status.get(image) != "AVAILABLE":
            failures.append("IMAGE_UNAVAILABLE")
        tasks.append(
            {
                "id": task_id,
                "status": "READY" if not failures else "BLOCKED",
                "failures": failures,
                "testPath": str(test_path),
                "testHash": test_hash,
                "skillPath": str(skill_path),
                "skillHash": skill_hash,
                "dockerImage": image,
            }
        )
    config_ready = expected_config_hash is None or expected_config_hash == observed_config_hash
    source_ready = isinstance(expected_commit, str) and expected_commit == observed_commit and config_ready
    docker_ready = docker.returncode == 0
    ready = docker_ready and source_ready and bool(tasks) and all(item["status"] == "READY" for item in tasks)
    return {
        "schemaVersion": "1.0",
        "status": "READY" if ready else "BLOCKED",
        "executionMode": "HOST_AGENT_DOCKER_EVALUATOR",
        "docker": {
            "status": "READY" if docker_ready else "BLOCKED",
            "binary": docker_binary,
            "version": docker.stdout.strip() if docker_ready else None,
            "error": docker.stderr.strip() if not docker_ready else None,
        },
        "source": {
            "expectedCommit": expected_commit,
            "observedCommit": observed_commit or None,
            "expectedConfigHash": expected_config_hash,
            "observedConfigHash": observed_config_hash,
            "status": "READY" if source_ready else "BLOCKED",
        },
        "images": image_status,
        "tasks": tasks,
    }


class SWETrialEnvironment:
    def __init__(self, upstream_root: str | Path, *, docker_binary: str = "docker") -> None:
        self.upstream_root = Path(upstream_root).resolve()
        self.docker_binary = docker_binary

    def evaluate(
        self,
        task: dict[str, Any],
        *,
        repository: str | Path,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        repo = Path(repository).resolve()
        if not repo.is_dir():
            raise ValueError(f"trial repository is missing: {repo}")
        test_path = _safe_upstream_path(self.upstream_root, task.get("upstreamTest"))
        if not test_path.is_file():
            raise ValueError(f"upstream evaluator is missing: {test_path}")
        image = task.get("dockerImage")
        if not isinstance(image, str) or not image:
            raise ValueError("SWE task requires dockerImage")
        workspace_directory = _workspace_directory(task)
        container_repository = f"/workspace/{workspace_directory}"
        before = _hash_file(test_path)
        command_results: list[dict[str, Any]] = []
        combined_output: list[str] = []
        timed_out = False
        raw_checks = task.get("checks")
        for command in raw_checks if isinstance(raw_checks, list) else []:
            if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
                raise ValueError("SWE task checks must be argv arrays")
            docker_command = [
                self.docker_binary,
                "run",
                "--rm",
                "--network",
                "none",
                "--mount",
                f"type=bind,source={repo},target={container_repository}",
                "--mount",
                f"type=bind,source={test_path.parent},target=/workspace/tests,readonly",
                "--workdir",
                container_repository,
                image,
                *command,
            ]
            try:
                completed = _run(docker_command, timeout=timeout_seconds, check=False)
                output = (completed.stdout or "") + (completed.stderr or "")
                combined_output.append(output)
                command_results.append(
                    {
                        "command": command,
                        "exitCode": completed.returncode,
                        "outputTail": output.splitlines()[-40:],
                    }
                )
            except subprocess.TimeoutExpired as error:
                timed_out = True
                output = ((error.stdout or "") + (error.stderr or "")) if isinstance(error.stdout, str) else ""
                combined_output.append(output)
                command_results.append({"command": command, "exitCode": 124, "outputTail": output.splitlines()[-40:]})
                break
        after = _hash_file(test_path)
        last_exit = command_results[-1]["exitCode"] if command_results else 1
        parsed = parse_test_output("\n".join(combined_output), exit_code=last_exit)
        all_commands_passed = bool(command_results) and all(item["exitCode"] == 0 for item in command_results)
        parsed["taskPassed"] = parsed["taskPassed"] and all_commands_passed and not timed_out and before == after
        return {
            **parsed,
            "buildPassed": all(item["exitCode"] == 0 for item in command_results[:-1]),
            "timedOut": timed_out,
            "protectedTestIntegrity": "PASS" if before == after else "FAIL",
            "testHash": before,
            "commands": command_results,
        }


def _safe_upstream_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        return root / "__missing__"
    path = (root / value).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"unsafe upstream path: {value}")
    return path


def _workspace_directory(task: dict[str, Any]) -> str:
    value = task.get("workspaceDirectory")
    if not isinstance(value, str) or not value:
        raw_repository = task.get("repository")
        repository: dict[str, Any] = raw_repository if isinstance(raw_repository, dict) else {}
        url = repository.get("url")
        value = str(url).rstrip("/").rsplit("/", 1)[-1] if isinstance(url, str) else ""
        if value.endswith(".git"):
            value = value[:-4]
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"unsafe SWE workspace directory: {value!r}")
    return value


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        timeout=timeout,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"command failed: {command[0]}")
    return completed
