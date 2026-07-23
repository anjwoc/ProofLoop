from __future__ import annotations

from types import SimpleNamespace

from proofloop_core.context.io import read_json, write_json
from proofloop_core.engine.roles import materialize_plan, run_plan_review


def test_materialize_plan_uses_the_planner_result_path(tmp_path):
    result_path = tmp_path / "plan.json"
    write_json(
        result_path,
        {
            "verdict": "READY",
            "summary": "bounded plan",
            "tasks": [
                {
                    "id": "TASK-001",
                    "objective": "repair orchestration wiring",
                    "allowedPaths": ["proofloop_core/engine/"],
                    "protectedPaths": [],
                    "requiredChecks": [{"command": ["pytest"]}],
                    "changeBudget": {
                        "maxChangedFiles": 4,
                        "maxAddedLines": 80,
                        "maxNewFiles": 1,
                        "allowDependencyChanges": False,
                    },
                    "simplicity": {
                        "selectedRung": "REUSE_EXISTING",
                        "rationale": "wire the extracted modules",
                        "considered": [],
                    },
                }
            ],
        },
    )
    events = []
    orchestrator = SimpleNamespace(
        run_dir=tmp_path,
        intent=SimpleNamespace(acceptance_criteria=(SimpleNamespace(criterion_id="AC-1"),)),
        _emit=lambda event_type, **data: events.append((event_type, data)),
    )

    tasks = materialize_plan(orchestrator, result_path)

    assert tasks[0].criterion_ids == ("AC-1",)
    assert read_json(tmp_path / "tasks" / "TASK-001.json")["criterion_ids"] == ["AC-1"]
    assert events[-1][0] == "criterion_mapping.inferred"


def test_plan_review_reads_the_review_artifact(tmp_path):
    def invoke(_role, _prompt, *, result_path, **_kwargs):
        write_json(result_path, {"verdict": "APPROVED", "findings": []})

    orchestrator = SimpleNamespace(
        run_dir=tmp_path,
        transition=lambda *_args, **_kwargs: None,
        _render_prompt=lambda _ir: "review",
        _invoke=invoke,
        _emit=lambda *_args, **_kwargs: None,
    )

    run_plan_review(orchestrator)
