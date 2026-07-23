from proofloop_core.runtimes.hosts import agy_workflow


def test_agy_workflow_presents_answerable_pauses_without_mislabeling_them() -> None:
    workflow = agy_workflow()

    assert "run-outcome.json" in workflow
    assert "NEEDS_INPUT" in workflow
    assert "input-request.json" in workflow
    assert "do not call it `BLOCKED`" in workflow
