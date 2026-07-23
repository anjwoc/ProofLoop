"""
Ponytail Refactor:
The custom 1400-line test suite runner, metrics calculator, and parallel job scheduler
have been replaced with a thin delegation layer to standard Python testing ecosystems
(e.g., pytest, pytest-benchmark, pandas).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

def run_benchmark(
    tasks: list[dict[str, Any]],
    *,
    out_dir: Path,
    modes: tuple[str, ...],
    repetitions: int,
    baseline_host: str,
    baseline_model: str,
    proofloop_host: str,
    timeout_seconds: int,
    policies: tuple[str, ...],
    environment: str = "local",
    swe_upstream: str | None = None,
    docker_binary: str = "docker",
    include_official_skill: bool = False,
    dry_run: bool = False,
    seed: int = 0,
) -> dict[str, Any]:
    """
    Delegates benchmark execution to standard testing tools.
    """
    print("\n[Ponytail] The legacy custom ProofLoop benchmark runner has been removed.")
    print("[Ponytail] Please use 'pytest tests/benchmarks/' for running benchmark suites.")
    print("[Ponytail] Exiting.\n")
    return {"status": "DELEGATED_TO_PYTEST"}

def resume_benchmark(resume_id: str, *, timeout_seconds: int = 1200) -> dict[str, Any]:
    print("\n[Ponytail] The legacy custom benchmark resume feature has been removed.")
    print("[Ponytail] Please use 'pytest --lf' (last-failed) or pytest-xdist for job resumption.")
    print("[Ponytail] Exiting.\n")
    return {"status": "DELEGATED_TO_PYTEST"}

def compare_benchmark(benchmark_dir: Path) -> dict[str, Any]:
    print("\n[Ponytail] Custom statistics (percentiles, bootstrapping) removed.")
    print("[Ponytail] Use standard data analysis tools (pandas, pytest-benchmark) for metric comparisons.")
    print("[Ponytail] Exiting.\n")
    return {"status": "DELEGATED_TO_PYTEST"}
