from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


WORKFLOW_LIMIT = 12 * 1024
TASK_LIMIT = 16 * 1024


@dataclass(frozen=True)
class MemoryContext:
    directory: Path
    workflow_path: Path
    task_path: Path
    workflow_needs_compaction: bool
    task_needs_compaction: bool


def _safe_task_name(task_id: str) -> str:
    value = task_id.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("task_id must be a single safe path segment")
    return value


def _write_if_missing(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def prepare_memory(repository: str | Path, task_id: str) -> MemoryContext:
    root = Path(repository).resolve() / ".proofloop" / "memory"
    safe = _safe_task_name(task_id)
    workflow = root / "MEMORY.md"
    task = root / "tasks" / f"{safe}.md"
    _write_if_missing(
        workflow,
        "# Workflow Memory\n\nKeep only durable, review-approved cross-task context here.\n\n"
        "## Current State\n\n## Shared Decisions\n\n## Shared Learnings\n\n## Open Risks\n\n## Handoffs\n",
    )
    _write_if_missing(
        task,
        f"# Task Memory: {safe}\n\nKeep only task-local execution context here.\n\n"
        "## Objective Snapshot\n\n## Important Decisions\n\n## Learnings\n\n"
        "## Files / Surfaces\n\n## Errors / Corrections\n\n## Ready for Next Run\n",
    )
    return MemoryContext(
        root,
        workflow,
        task,
        workflow.stat().st_size > WORKFLOW_LIMIT,
        task.stat().st_size > TASK_LIMIT,
    )


def write_memory(path: str | Path, content: str, *, append: bool = False) -> int:
    target = Path(path).resolve()
    memory_root = target
    while memory_root.name != "memory" and memory_root.parent != memory_root:
        memory_root = memory_root.parent
    if memory_root.name != "memory" or (target != memory_root and memory_root not in target.parents):
        raise ValueError("memory target must stay inside a memory directory")
    previous = target.read_text(encoding="utf-8") if append and target.exists() else ""
    rendered = previous.rstrip("\n") + ("\n\n" if previous.strip() else "") + content.rstrip("\n") + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return len(rendered.encode("utf-8"))
