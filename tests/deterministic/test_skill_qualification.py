from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from proofloop_core.skill_qualification import (
    build_behavior_trial_schedule,
    qualify_domain_packs,
    validate_behavior_fixture,
)
from proofloop_core.cli import main


ROOT = Path(__file__).resolve().parents[2]


class SkillQualificationTest(unittest.TestCase):
    def test_builtin_authoring_trigger_fixtures_meet_routing_thresholds(self) -> None:
        report = qualify_domain_packs(ROOT / "proofloop_domain_packs")

        self.assertEqual("READY_FOR_BEHAVIOR_EVAL", report["status"])
        self.assertEqual(5, len(report["packs"]))
        for pack in report["packs"]:
            trigger = pack["triggerEvaluation"]
            self.assertGreaterEqual(trigger["f1"], 0.85, pack)
            self.assertLessEqual(trigger["irrelevantActivationRate"], 0.05, pack)
            self.assertEqual(0, trigger["falsePositiveCount"], pack)
            self.assertEqual("PENDING_AGENT_BEHAVIOR_EVAL", pack["behaviorEvaluation"]["status"])
            self.assertEqual(3, pack["behaviorEvaluation"]["scenarioCount"])

    def test_pinned_swe_catalog_is_an_external_trigger_set_for_primary_packs(self) -> None:
        catalog = ROOT / "benchmarks" / "swe-skills-bench" / "catalog.json"

        report = qualify_domain_packs(ROOT / "proofloop_domain_packs", external_catalog=catalog)
        by_name = {item["pack"]: item for item in report["packs"]}

        for name in ("backend-development", "frontend-development", "devops-delivery"):
            external = by_name[name]["externalTriggerEvaluation"]
            self.assertEqual("MEASURED", external["status"])
            self.assertEqual(1.0, external["f1"], external)
            self.assertEqual(0, external["falsePositiveCount"], external)
        self.assertEqual("NOT_COVERED", by_name["test-engineering"]["externalTriggerEvaluation"]["status"])
        self.assertEqual("NOT_COVERED", by_name["code-review"]["externalTriggerEvaluation"]["status"])
        self.assertEqual("95b3ce519fcb58d0b19e90a5b6e5165211dc6dd1", report["externalCatalog"]["commit"])

    def test_behavior_schedule_has_stable_fixture_and_scenario_hashes(self) -> None:
        first = qualify_domain_packs(ROOT / "proofloop_domain_packs")
        second = qualify_domain_packs(ROOT / "proofloop_domain_packs")

        self.assertEqual(first["qualificationHash"], second["qualificationHash"])
        first_scenarios = first["packs"][0]["behaviorEvaluation"]["scenarios"]
        self.assertRegex(first_scenarios[0]["scenarioHash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("requires", json.dumps(first_scenarios))
        self.assertNotIn("forbids", json.dumps(first_scenarios))

    def test_behavior_trial_schedule_is_paired_stable_and_hides_rubrics(self) -> None:
        qualification = qualify_domain_packs(ROOT / "proofloop_domain_packs")

        first = build_behavior_trial_schedule(qualification, repetitions=3, seed=19)
        second = build_behavior_trial_schedule(qualification, repetitions=3, seed=19)

        self.assertEqual(first, second)
        self.assertEqual("PLANNED", first["status"])
        self.assertEqual(90, first["plannedTrials"])
        self.assertEqual(
            {"single-no-skill", "single-proofloop-domain"},
            {trial["arm"] for trial in first["trials"]},
        )
        pairs: dict[tuple[str, str, int], set[str]] = {}
        for trial in first["trials"]:
            key = (trial["pack"], trial["scenarioHash"], trial["repetition"])
            pairs.setdefault(key, set()).add(trial["arm"])
        self.assertTrue(pairs)
        self.assertTrue(all(arms == {"single-no-skill", "single-proofloop-domain"} for arms in pairs.values()))
        serialized = json.dumps(first)
        self.assertNotIn("requires", serialized)
        self.assertNotIn("forbids", serialized)
        self.assertRegex(first["scheduleHash"], r"^[0-9a-f]{64}$")

    def test_behavior_trial_schedule_rejects_invalid_repetition_count(self) -> None:
        qualification = qualify_domain_packs(ROOT / "proofloop_domain_packs")

        with self.assertRaisesRegex(ValueError, "repetitions"):
            build_behavior_trial_schedule(qualification, repetitions=0)

    def test_duplicate_behavior_scenario_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "behavior.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "scenarios": [
                            {"id": "same", "request": "one", "requires": ["x"], "forbids": ["y"]},
                            {"id": "same", "request": "two", "requires": ["x"], "forbids": ["y"]},
                            {"id": "third", "request": "three", "requires": ["x"], "forbids": ["y"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate behavior scenario id"):
                validate_behavior_fixture(path)

    def test_cli_writes_machine_readable_qualification_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "qualification.json"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "qualify-skills",
                        "--root",
                        str(ROOT / "proofloop_domain_packs"),
                        "--pack",
                        "backend-development",
                        "--output",
                        str(output),
                        "--external-catalog",
                        str(ROOT / "benchmarks" / "swe-skills-bench" / "catalog.json"),
                        "--behavior-repetitions",
                        "3",
                        "--seed",
                        "19",
                    ]
                )

            self.assertEqual(0, exit_code)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("READY_FOR_BEHAVIOR_EVAL", report["status"])
            self.assertEqual(["backend-development"], [item["pack"] for item in report["packs"]])
            self.assertEqual("MEASURED", report["packs"][0]["externalTriggerEvaluation"]["status"])
            self.assertEqual(18, report["behaviorBenchmark"]["plannedTrials"])
            self.assertEqual(str(output.resolve()), json.loads(stdout.getvalue())["report"])


if __name__ == "__main__":
    unittest.main()
