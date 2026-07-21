import os
import sys
import unittest
from unittest import mock
import tempfile
import json
from pathlib import Path
from tests.orchestration.test_orchestrator import make_repo, ScriptedAdapter, load_events
from proofloop_core.orchestrator import orchestrate

def run():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_repo(root)
        adapter = ScriptedAdapter()
        with mock.patch.dict(os.environ, {"PROOFLOOP_COMPILER_ACTIVE_TIERS": "T2,T3"}):
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior",
                adapter=adapter,
                strategy_override="HIGH_RISK_ENGINEERING",
            )
        print("Verdict:", result["verdict"])
        if "code" in result:
            print("Code:", result["code"])
        events = load_events(result["runDir"])
        for e in events[-5:]:
            print(e["type"], e.get("message"))

if __name__ == "__main__":
    run()
