from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.benchmark import (
    arm_policy,
    build_builtin_domain_context,
    build_skill_scorecards,
    build_single_agent_prompt,
    build_trial_schedule,
    compare_trials,
    determine_trial_success,
    load_benchmark_suite,
    run_benchmark,
    skill_comparison_policy,
    snapshot_protected_files,
    verify_protected_files,
)


def trial(arm: str, repetition: int, tokens: int, *, proven: bool = True) -> dict:
    mode = arm.rsplit("-", 1)[1]
    return {
        "mode": mode,
        "arm": arm,
        "taskId": "task-1",
        "repetition": repetition,
        "verdict": "PROVEN" if proven else "FAILED",
        "usageAvailable": True,
        "costAvailable": True,
        "durationSeconds": 10,
        "usage": {"totals": {"rawTotal": tokens, "costUsd": tokens / 1000}},
    }


class BenchmarkTest(unittest.TestCase):
    def test_benchmark_wrapper_help_is_non_executing(self) -> None:
        completed = subprocess.run(
            ["bash", "scripts/run_benchmarks.sh", "--help"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Plan benchmark schedules by default", completed.stdout)
        self.assertIn("--execute", completed.stdout)

    def test_benchmark_wrapper_refuses_execution_without_a_pinned_baseline_model(self) -> None:
        completed = subprocess.run(
            ["bash", "scripts/run_benchmarks.sh", "--reservation", "--execute"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("--execute requires --baseline-model", completed.stderr)

    def test_official_evaluator_is_authoritative_over_agent_self_verdict(self) -> None:
        self.assertTrue(
            determine_trial_success(
                agent_verdict="BLOCKED",
                integrity_verdict="PASS",
                checks=[{"exitCode": 0}],
                evaluation={"taskPassed": True},
            )
        )
        self.assertFalse(
            determine_trial_success(
                agent_verdict="PROVEN",
                integrity_verdict="PASS",
                checks=[{"exitCode": 1}],
                evaluation={"taskPassed": False},
            )
        )
        self.assertFalse(
            determine_trial_success(
                agent_verdict="BLOCKED",
                integrity_verdict="PASS",
                checks=[{"exitCode": 0}],
                evaluation=None,
            )
        )

    def test_schedule_builds_six_paired_arms_per_task_and_repetition(self) -> None:
        tasks = [
            {"id": "backend", "request": "a", "domain": "backend"},
            {"id": "frontend", "request": "b", "domain": "frontend"},
        ]

        schedule = build_trial_schedule(
            tasks,
            modes=("system",),
            repetitions=2,
            policies=("core", "adaptive", "full"),
            include_official_skill=True,
            seed=17,
        )

        self.assertEqual(36, len(schedule))
        for task_id in ("backend", "frontend"):
            for repetition in (1, 2):
                arms = {
                    item["arm"]
                    for item in schedule
                    if item["task"]["id"] == task_id and item["repetition"] == repetition
                }
                self.assertEqual(
                    {
                        "arm-A-current-system",
                        "arm-B-deterministic-system",
                        "arm-C-raw-meta-system",
                        "arm-D-grounded-meta-system",
                        "arm-E-grounded-model-system",
                        "arm-F-large-baseline-system",
                        "proofloop-core-system",
                        "proofloop-adaptive-system",
                        "proofloop-full-system",
                    },
                    arms,
                )

    def test_ablation_arms_have_distinct_hashed_execution_policies(self) -> None:
        policies = [arm_policy(f"arm-{code}-{label}-system", "system") for code, label in (
            ("A", "current"),
            ("B", "deterministic"),
            ("C", "raw-meta"),
            ("D", "grounded-meta"),
            ("E", "grounded-model"),
            ("F", "large-baseline"),
        )]

        self.assertEqual(6, len({item["policySha256"] for item in policies}))
        self.assertEqual("proofloop-goal", policies[0]["execution"])
        self.assertEqual("proofloop-adaptive", policies[1]["execution"])
        self.assertEqual("single-agent", policies[2]["execution"])
        self.assertEqual("snapshot", policies[3]["promptGrounding"])
        self.assertEqual("model-specific", policies[4]["renderer"])
        self.assertEqual("large-directive", policies[5]["promptVariant"])

    def test_official_skill_schedule_adds_paired_external_and_domain_arms(self) -> None:
        schedule = build_trial_schedule(
            [{"id": "task-1", "request": "do it", "skillDocument": "skills/task-1/SKILL.md"}],
            modes=("system",), repetitions=1, policies=("core", "adaptive", "full"),
            include_official_skill=True, seed=3,
        )
        arms = {item["arm"] for item in schedule}
        self.assertIn("single-official-skill-system", arms)
        self.assertIn("single-proofloop-domain-system", arms)
        official = next(item["policy"] for item in schedule if item["arm"] == "single-official-skill-system")
        self.assertEqual(skill_comparison_policy("single-official-skill-system", "system"), official)
        self.assertEqual("official", official["injectedSkill"])

    def test_ablation_comparison_uses_large_directive_as_the_fixed_baseline(self) -> None:
        trials = []
        for repetition in range(1, 3):
            trials.extend(
                [
                    trial("arm-F-large-baseline-system", repetition, 1_000),
                    trial("arm-A-current-system", repetition, 700),
                    trial("arm-B-deterministic-system", repetition, 600),
                ]
            )

        comparisons = compare_trials(trials)["comparisons"]

        self.assertEqual(["arm-A-current-system", "arm-B-deterministic-system"], [item["policy"]["arm"] for item in comparisons])
        self.assertEqual(30.0, comparisons[0]["tokenEfficiencyGainPct"])
        self.assertEqual(40.0, comparisons[1]["tokenEfficiencyGainPct"])

    def test_skill_comparison_arms_are_compared_with_the_fixed_baseline(self) -> None:
        trials = [
            {**trial("arm-F-large-baseline-system", 1, 1_000), "policy": arm_policy("arm-F-large-baseline-system", "system")},
            {**trial("single-official-skill-system", 1, 900), "policy": skill_comparison_policy("single-official-skill-system", "system")},
            {**trial("single-proofloop-domain-system", 1, 800), "policy": skill_comparison_policy("single-proofloop-domain-system", "system")},
        ]

        comparisons = compare_trials(trials)["comparisons"]
        by_arm = {item["policy"]["arm"]: item for item in comparisons}
        self.assertEqual(10.0, by_arm["single-official-skill-system"]["tokenEfficiencyGainPct"])
        self.assertEqual(20.0, by_arm["single-proofloop-domain-system"]["tokenEfficiencyGainPct"])

    def test_builtin_domain_only_context_uses_generic_pack_and_matching_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "pyproject.toml").write_text(
                '[project]\nname="sample"\ndependencies=["Django==5.1.2"]\n',
                encoding="utf-8",
            )

            context, usage = build_builtin_domain_context(
                repo,
                {"id": "backend", "request": "Add a backend API endpoint", "domain": "backend"},
            )

            self.assertIn("# Backend Development", context)
            self.assertIn("# Django 5 adapter", context)
            self.assertNotIn("# Spring Boot 3 adapter", context)
            self.assertEqual(["backend-development"], usage["domainPacks"])
            self.assertEqual(["django-5"], usage["adapters"])

    def test_official_skill_is_injected_only_into_the_matching_single_agent_arm(self) -> None:
        task = {
            "id": "sample",
            "request": "Implement sample",
            "checks": [["python", "-m", "pytest", "/workspace/tests/test_sample.py"]],
        }

        plain = build_single_agent_prompt(task)
        skilled = build_single_agent_prompt(task, official_skill="# Domain skill\nUse the framework convention.")

        self.assertNotIn("Official domain skill", plain)
        self.assertIn("Official domain skill", skilled)
        self.assertIn("# Domain skill", skilled)
        self.assertIn("Implement sample", skilled)
        self.assertNotIn("/workspace/tests", plain)
        self.assertNotIn("/workspace/tests", skilled)

    def test_model_specific_benchmark_renderer_preserves_the_task_and_marks_contract_boundary(self) -> None:
        task = {"id": "sample", "request": "Implement sample", "checks": []}

        rendered = build_single_agent_prompt(task, renderer_kind="model-specific")

        self.assertIn("structured benchmark contract", rendered)
        self.assertIn("Implement sample", rendered)

    def test_swe_environment_materializes_each_catalog_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controller = self._repository(root)
            target_source = root / "target-source"
            target_source.mkdir()
            subprocess.run(["git", "init"], cwd=target_source, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "qa@example.com"], cwd=target_source, check=True)
            subprocess.run(["git", "config", "user.name", "QA"], cwd=target_source, check=True)
            (target_source / "TARGET.txt").write_text("official task repository\n", encoding="utf-8")
            subprocess.run(["git", "add", "TARGET.txt"], cwd=target_source, check=True)
            subprocess.run(["git", "commit", "-m", "target"], cwd=target_source, check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=target_source, check=True, capture_output=True, text=True
            ).stdout.strip()
            upstream = root / "upstream"
            (upstream / "tests" / "batch1").mkdir(parents=True)
            (upstream / "skills" / "task-1").mkdir(parents=True)
            (upstream / "tests" / "batch1" / "test_task_1.py").write_text("def test_ok(): pass\n")
            (upstream / "skills" / "task-1" / "SKILL.md").write_text("# Official\n")
            suite = controller / "suite.json"
            suite.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "task-1",
                                "request": "do it",
                                "checks": [],
                                "repository": {"url": str(target_source), "commit": commit},
                                "dockerImage": "fixture:latest",
                                "upstreamTest": "tests/batch1/test_task_1.py",
                                "skillDocument": "skills/task-1/SKILL.md",
                            }
                        ]
                    }
                )
            )

            def fake_execute(repository: Path, task: dict, **kwargs) -> dict:
                self.assertTrue((repository / "TARGET.txt").exists())
                self.assertFalse((repository / "README.md").exists())
                return self._fake_trial(repository, task, **kwargs)

            with patch("proofloop_core.benchmark._execute_trial", side_effect=fake_execute):
                result = run_benchmark(
                    suite,
                    controller,
                    mode="system",
                    repetitions=1,
                    baseline_host="codex",
                    baseline_model="gpt-test",
                    proofloop_host="codex",
                    environment="swe-skills",
                    swe_upstream=upstream,
                )

            self.assertEqual(9, result["completedTrials"])

    def test_dry_run_persists_schedule_without_executing_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repository(Path(tmp))
            suite = repo / "suite.json"
            suite.write_text(json.dumps({"tasks": [{"id": "task-1", "request": "do it", "checks": []}]}))

            with patch("proofloop_core.benchmark._execute_trial") as execute:
                result = run_benchmark(
                    suite,
                    repo,
                    mode="system",
                    repetitions=1,
                    baseline_host="codex",
                    baseline_model="gpt-test",
                    proofloop_host="codex",
                    policies=("core", "adaptive", "full"),
                    include_official_skill=True,
                    dry_run=True,
                )

            self.assertEqual("DRY_RUN", result["status"])
            self.assertEqual(9, result["plannedTrials"])
            execute.assert_not_called()
            schedule = json.loads((Path(result["benchmarkDir"]) / "schedule.json").read_text())
            self.assertEqual(9, len(schedule["trials"]))

    def test_resume_skips_completed_trial_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repository(Path(tmp))
            suite = repo / "suite.json"
            suite.write_text(json.dumps({"tasks": [{"id": "task-1", "request": "do it", "checks": []}]}))

            with patch("proofloop_core.benchmark._execute_trial", side_effect=self._fake_trial) as execute:
                first = run_benchmark(
                    suite,
                    repo,
                    mode="system",
                    repetitions=1,
                    baseline_host="codex",
                    baseline_model="gpt-test",
                    proofloop_host="codex",
                )
                self.assertEqual(9, execute.call_count)

            with patch("proofloop_core.benchmark._execute_trial", side_effect=AssertionError("duplicate trial")) as execute:
                resumed = run_benchmark(
                    suite,
                    repo,
                    mode="system",
                    repetitions=1,
                    baseline_host="codex",
                    baseline_model="gpt-test",
                    proofloop_host="codex",
                    benchmark_dir=first["benchmarkDir"],
                    resume=True,
                )

            execute.assert_not_called()
            self.assertEqual(9, resumed["completedTrials"])
            self.assertEqual(9, resumed["skippedTrials"])

    def test_comparison_reports_quality_adjusted_token_gain(self) -> None:
        trials = []
        for repetition in range(1, 6):
            trials.append(trial("baseline-routing", repetition, 1000))
            trials.append(trial("proofloop-routing", repetition, 500))

        result = compare_trials(trials)["comparisons"][0]

        self.assertEqual("IMPROVED", result["status"])
        self.assertEqual(50.0, result["tokenEfficiencyGainPct"])
        self.assertEqual([50.0, 50.0], result["pairedTokenGain95CI"])
        self.assertEqual(1.0, result["proofloop"]["successRate"])

    def test_missing_usage_never_becomes_zero_token_efficiency(self) -> None:
        baseline = trial("baseline-system", 1, 1000)
        candidate = trial("proofloop-system", 1, 0)
        candidate["usageAvailable"] = False

        result = compare_trials([baseline, candidate])["comparisons"][0]

        self.assertIsNone(result["tokenEfficiencyGainPct"])
        self.assertEqual("INSUFFICIENT_DATA", result["status"])
        self.assertEqual(1, result["proofloop"]["invalidUsageTrials"])
        self.assertEqual(0.0, result["proofloop"]["usageValidityRate"])

    def test_comparison_reports_task_and_official_test_pass_rates(self) -> None:
        baseline = trial("single-no-skill-system", 1, 1000, proven=False)
        baseline.update({"testsPassed": 3, "testsTotal": 5, "testPassRate": 0.6})
        candidate = trial("proofloop-adaptive-system", 1, 900)
        candidate.update({"testsPassed": 5, "testsTotal": 5, "testPassRate": 1.0})

        result = compare_trials([baseline, candidate])["comparisons"][0]

        self.assertEqual(0.0, result["baseline"]["taskPassRate"])
        self.assertEqual(0.6, result["baseline"]["officialTestPassRate"])
        self.assertEqual(1.0, result["proofloop"]["taskPassRate"])
        self.assertEqual(1.0, result["proofloop"]["officialTestPassRate"])
        self.assertEqual(100.0, result["passRateDeltaPctPoints"])

    def test_quality_noninferiority_is_checked_before_efficiency_gain(self) -> None:
        trials = []
        for repetition in range(1, 6):
            trials.append(trial("single-no-skill-system", repetition, 1000))
            trials.append(trial("proofloop-adaptive-system", repetition, 500, proven=repetition != 5))

        result = compare_trials(trials)["comparisons"][0]

        self.assertFalse(result["qualityNonInferior"])
        self.assertEqual("NO_PROVEN_GAIN", result["status"])
        self.assertLess(result["pairedPassRateDelta95CI"][0], -2.0)

    def test_comparison_separates_adaptive_and_full_proofloop_policies(self) -> None:
        trials = []
        for repetition in range(1, 3):
            trials.extend(
                [
                    trial("baseline-system", repetition, 1000),
                    trial("proofloop-adaptive-system", repetition, 600),
                    trial("proofloop-full-system", repetition, 900),
                ]
            )

        comparisons = compare_trials(trials)["comparisons"]

        self.assertEqual(["adaptive", "full"], [item["policy"] for item in comparisons])
        self.assertEqual(40.0, comparisons[0]["tokenEfficiencyGainPct"])
        self.assertEqual(10.0, comparisons[1]["tokenEfficiencyGainPct"])

    def test_policy_comparison_directly_compares_core_adaptive_and_full(self) -> None:
        trials = []
        for repetition in range(1, 4):
            trials.extend(
                [
                    trial("single-no-skill-system", repetition, 1000),
                    trial("proofloop-core-system", repetition, 800),
                    trial("proofloop-adaptive-system", repetition, 600),
                    trial("proofloop-full-system", repetition, 900),
                ]
            )

        result = compare_trials(trials)
        pairs = {(item["leftPolicy"], item["rightPolicy"]): item for item in result["policyComparisons"]}

        self.assertEqual({("core", "adaptive"), ("core", "full"), ("adaptive", "full")}, set(pairs))
        self.assertEqual(25.0, pairs[("core", "adaptive")]["tokenEfficiencyGainPct"])
        self.assertEqual(-50.0, pairs[("adaptive", "full")]["tokenEfficiencyGainPct"])

    def test_comparison_aggregates_by_domain_and_workload_tier(self) -> None:
        baseline = trial("baseline-system", 1, 1000)
        candidate = trial("proofloop-adaptive-system", 1, 500)
        for item in (baseline, candidate):
            item["domain"] = "backend"
            item["workloadTier"] = "T2"

        result = compare_trials([baseline, candidate])

        self.assertIn("backend", result["byDomain"])
        self.assertIn("T2", result["byWorkloadTier"])

    def test_comparison_aggregates_actual_domain_pack_and_adapter_usage(self) -> None:
        baseline = trial("single-no-skill-system", 1, 1000)
        candidate = trial("single-proofloop-domain-system", 1, 800)
        candidate["skillUsage"] = {
            "domainPacks": ["backend-development"],
            "adapters": ["django-5"],
            "processProtocols": [],
            "estimatedInjectedTokens": 820,
        }

        summary = compare_trials([baseline, candidate])["skillUsage"]

        self.assertEqual(1, summary["trialsWithDomainPack"])
        self.assertEqual(1, summary["domainPacks"]["backend-development"]["trials"])
        self.assertEqual(1.0, summary["domainPacks"]["backend-development"]["taskPassRate"])
        self.assertEqual(1, summary["adapters"]["django-5"])
        self.assertEqual(820, summary["estimatedInjectedTokens"])

    def test_skill_scorecard_requires_five_tasks_three_repetitions_and_quality_noninferiority(self) -> None:
        trials = []
        for task_number in range(5):
            for repetition in range(1, 4):
                baseline = trial("single-no-skill-system", repetition, 1000)
                baseline["taskId"] = f"task-{task_number}"
                candidate = trial("single-proofloop-domain-system", repetition, 800)
                candidate["taskId"] = f"task-{task_number}"
                candidate["skillUsage"] = {
                    "domainPacks": ["backend-development"],
                    "adapters": [],
                    "processProtocols": [],
                    "estimatedInjectedTokens": 500,
                }
                trials.extend([baseline, candidate])

        scorecard = build_skill_scorecards(trials)["backend-development"]

        self.assertEqual("E2", scorecard["evidenceLevel"])
        self.assertEqual(5, scorecard["distinctTasks"])
        self.assertEqual(15, scorecard["pairedTrials"])
        self.assertTrue(scorecard["qualityNonInferior"])
        self.assertTrue(scorecard["promotionReviewEligible"])
        self.assertEqual(20.0, scorecard["meanPairedTokenGainPct"])

    def test_suite_requires_argv_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "suite.json"
            path.write_text(json.dumps({"tasks": [{"id": "t", "request": "r", "checks": ["pytest"]}]}))
            with self.assertRaisesRegex(ValueError, "command arguments"):
                load_benchmark_suite(path)

    def test_protected_external_verifier_mutation_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verifier = root / "benchmark_verify.py"
            verifier.write_text("original\n")
            snapshot = snapshot_protected_files(root, ["benchmark_verify.py"])
            verifier.write_text("tampered\n")

            result = verify_protected_files(root, snapshot)

            self.assertEqual("FAIL", result["verdict"])
            self.assertEqual(["benchmark_verify.py"], result["changed"])

    def test_runner_uses_isolated_worktrees_and_persists_trials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repository(Path(tmp))
            suite = repo / "suite.json"
            suite.write_text(json.dumps({"tasks": [{"id": "task-1", "request": "do it", "checks": []}]}))

            def fake_execute(worktree: Path, task: dict, **kwargs) -> dict:
                arm = kwargs["arm"]
                run_dir = worktree / ".proofloop" / "runs" / arm
                (run_dir / "usage").mkdir(parents=True)
                (run_dir / "run.json").write_text("{}\n", encoding="utf-8")
                usage = {
                    "totals": {"rawTotal": 100 if arm.startswith("baseline") else 50, "costUsd": 0.01},
                    "coverage": {"expectedInvocations": 1, "measuredInvocations": 1, "tokenCoverageRatio": 1.0, "costedInvocations": 1},
                }
                return {
                    "verdict": "PROVEN",
                    "agentVerdict": "PROVEN",
                    "runDir": str(run_dir),
                    "durationSeconds": 1,
                    "checks": [],
                    "usage": usage,
                    "usageAvailable": True,
                    "costAvailable": True,
                }

            with patch("proofloop_core.benchmark._execute_trial", side_effect=fake_execute):
                result = run_benchmark(
                    suite,
                    repo,
                    mode="routing",
                    repetitions=1,
                    baseline_host="codex",
                    baseline_model="gpt-test",
                    proofloop_host="codex",
                )

            root = Path(result["benchmarkDir"])
            trials = (root / "trials.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(9, len(trials))
            self.assertTrue((root / "comparison.json").exists())
            self.assertEqual([], subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True).stdout.split("worktree ")[2:])

    def _repository(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "qa@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "QA"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
        return repo

    def _fake_trial(self, worktree: Path, task: dict, **kwargs) -> dict:
        arm = kwargs["arm"]
        run_dir = worktree / ".proofloop" / "runs" / arm
        (run_dir / "usage").mkdir(parents=True)
        (run_dir / "run.json").write_text("{}\n", encoding="utf-8")
        usage = {
            "totals": {"rawTotal": 100 if arm.startswith("single") else 50, "costUsd": 0.01},
            "coverage": {"expectedInvocations": 1, "measuredInvocations": 1, "tokenCoverageRatio": 1.0, "costedInvocations": 1},
        }
        return {
            "verdict": "PROVEN",
            "agentVerdict": "PROVEN",
            "runDir": str(run_dir),
            "durationSeconds": 1,
            "checks": [],
            "usage": usage,
            "usageAvailable": True,
            "costAvailable": True,
        }


if __name__ == "__main__":
    unittest.main()

    def test_evaluate_promotion_requires_minimum_trials(self) -> None:
        from proofloop_core.benchmark import evaluate_promotion
        baseline = {"trials": 30, "taskPassRate": 0.5, "tokensPerProven": 1000}
        candidate = {"trials": 29, "taskPassRate": 0.6, "tokensPerProven": 1000}
        result = evaluate_promotion(baseline, candidate)
        self.assertFalse(result["promoted"])
        self.assertIn("insufficient trials", result["reason"])

    def test_evaluate_promotion_requires_no_false_proven_increase(self) -> None:
        from proofloop_core.benchmark import evaluate_promotion
        baseline = {"trials": 30, "taskPassRate": 0.5, "tokensPerProven": 1000, "falseProvenRate": 0.05}
        candidate = {"trials": 30, "taskPassRate": 0.6, "tokensPerProven": 1000, "falseProvenRate": 0.1}
        result = evaluate_promotion(baseline, candidate)
        self.assertFalse(result["promoted"])
        self.assertIn("false PROVEN rate increased", result["reason"])

    def test_evaluate_promotion_pass_rate_improvement(self) -> None:
        from proofloop_core.benchmark import evaluate_promotion
        baseline = {"trials": 30, "taskPassRate": 0.5, "tokensPerProven": 1000}
        candidate = {"trials": 30, "taskPassRate": 0.55, "tokensPerProven": 1000}
        result = evaluate_promotion(baseline, candidate)
        self.assertTrue(result["promoted"])
        self.assertIn("pass rate improved", result["reason"])

    def test_evaluate_promotion_token_reduction(self) -> None:
        from proofloop_core.benchmark import evaluate_promotion
        baseline = {"trials": 30, "taskPassRate": 0.5, "tokensPerProven": 1000}
        candidate = {"trials": 30, "taskPassRate": 0.5, "tokensPerProven": 800}
        result = evaluate_promotion(baseline, candidate)
        self.assertTrue(result["promoted"])
        self.assertIn("tokens decreased", result["reason"])

    def test_evaluate_promotion_fails_if_tokens_decrease_but_pass_drops(self) -> None:
        from proofloop_core.benchmark import evaluate_promotion
        baseline = {"trials": 30, "taskPassRate": 0.5, "tokensPerProven": 1000}
        candidate = {"trials": 30, "taskPassRate": 0.49, "tokensPerProven": 800}
        result = evaluate_promotion(baseline, candidate)
        self.assertFalse(result["promoted"])
