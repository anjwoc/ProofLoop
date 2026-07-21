import tempfile
import unittest
import json
from pathlib import Path

from proofloop_core.task_brief import load_task_brief

class TaskBriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.brief_path = self.root / "brief.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_v1_brief_with_defaults(self):
        data = {
            "id": "T-1",
            "objective": "Do the thing",
            "allowedPaths": ["src/"],
            "protectedPaths": [],
            "requiredChecks": [{"command": ["pytest"]}],
            "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1},
            "changeBudget": {
                "maxChangedFiles": 5,
                "maxAddedLines": 500,
                "maxNewFiles": 1,
                "allowDependencyChanges": False
            },
            "simplicity": {
                "selectedRung": "STDLIB",
                "rationale": "No need for external libs",
                "considered": ["foo"]
            }
        }
        self.brief_path.write_text(json.dumps(data), encoding="utf-8")
        brief = load_task_brief(self.brief_path)
        
        self.assertEqual("T-1", brief.task_id)
        self.assertEqual("Do the thing", brief.objective)
        self.assertEqual("", brief.title)
        self.assertEqual((), brief.criterion_ids)
        self.assertEqual((), brief.deliverables)
        self.assertEqual((), brief.dependencies)
        self.assertEqual((), brief.interfaces)
        self.assertEqual((), brief.context_refs)
        self.assertEqual((), brief.tool_allowlist)
        self.assertIsNone(brief.proof_plan)
        self.assertEqual("", brief.stop_when)
        self.assertEqual((), brief.escalate_on)

    def test_loads_v2_brief_with_proof_plan_and_criterion_ids(self):
        data = {
            "id": "T-1",
            "title": "Build the feature",
            "objective": "Do the thing",
            "criterion_ids": ["C-1", "C-2"],
            "deliverables": ["bin/out"],
            "dependencies": ["T-0"],
            "interfaces": ["POST /api"],
            "allowedPaths": ["src/"],
            "protectedPaths": [],
            "context_refs": ["#docs"],
            "tool_allowlist": ["git"],
            "requiredChecks": [{"command": ["pytest"]}],
            "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1},
            "changeBudget": {
                "maxChangedFiles": 5,
                "maxAddedLines": 500,
                "maxNewFiles": 1,
                "allowDependencyChanges": False
            },
            "simplicity": {
                "selectedRung": "STDLIB",
                "rationale": "No need for external libs",
                "considered": ["foo"]
            },
            "proofPlan": {
                "baselineChecks": [{"command": ["make", "check"]}],
                "redChecks": [{"command": ["pytest", "fail.py"]}],
                "automatedChecks": [{"command": ["pytest", "pass.py"]}],
                "surfaceScenarios": [{
                    "scenario_id": "S-1",
                    "invocation": "curl /api",
                    "observable": "status 200",
                    "pass_rule": "strict match",
                    "artifact_type": "json",
                    "cleanup": "drop db",
                    "command": ["python", "-c", "raise SystemExit(0)"],
                    "timeoutSeconds": 12,
                }],
                "adversarialChecks": [],
                "cleanupChecks": []
            },
            "stop_when": "all green",
            "escalate_on": ["timeout"]
        }
        self.brief_path.write_text(json.dumps(data), encoding="utf-8")
        brief = load_task_brief(self.brief_path)
        
        self.assertEqual("Build the feature", brief.title)
        self.assertEqual(("C-1", "C-2"), brief.criterion_ids)
        self.assertEqual(("bin/out",), brief.deliverables)
        self.assertEqual(("T-0",), brief.dependencies)
        self.assertEqual(("POST /api",), brief.interfaces)
        self.assertEqual(("#docs",), brief.context_refs)
        self.assertEqual(("git",), brief.tool_allowlist)
        self.assertEqual("all green", brief.stop_when)
        self.assertEqual(("timeout",), brief.escalate_on)
        
        self.assertIsNotNone(brief.proof_plan)
        plan = brief.proof_plan
        self.assertEqual(1, len(plan.baseline_checks))
        self.assertEqual(["make", "check"], plan.baseline_checks[0].command)
        self.assertEqual(1, len(plan.red_checks))
        self.assertEqual(1, len(plan.automated_checks))
        
        self.assertEqual(1, len(plan.surface_scenarios))
        s = plan.surface_scenarios[0]
        self.assertEqual("S-1", s.scenario_id)
        self.assertEqual("curl /api", s.invocation)
        self.assertEqual("status 200", s.observable)
        self.assertEqual("strict match", s.pass_rule)
        self.assertEqual("json", s.artifact_type)
        self.assertEqual("drop db", s.cleanup)
        self.assertEqual(["python", "-c", "raise SystemExit(0)"], s.command)
        self.assertEqual(12, s.timeout_seconds)
        
        self.assertEqual((), plan.adversarial_checks)
        self.assertEqual((), plan.cleanup_checks)

    def test_rejects_non_executable_surface_scenario(self):
        data = {
            "id": "T-1", "objective": "Do the thing", "allowedPaths": ["src/"], "protectedPaths": [],
            "requiredChecks": [{"command": ["pytest"]}],
            "changeBudget": {"maxChangedFiles": 1, "maxAddedLines": 1, "maxNewFiles": 0, "allowDependencyChanges": False},
            "simplicity": {"selectedRung": "STDLIB", "rationale": "no dependency", "considered": []},
            "proofPlan": {
                "surfaceScenarios": [{
                    "scenario_id": "S-1", "invocation": "run it", "observable": "ok",
                    "pass_rule": "exit 0", "artifact_type": "text", "cleanup": None,
                }],
            },
        }
        self.brief_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "surfaceScenarios\\[0\\]\\.command"):
            load_task_brief(self.brief_path)

if __name__ == "__main__":
    unittest.main()
