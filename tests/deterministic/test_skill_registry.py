from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.skill_registry import ResolutionContext, SkillRegistry


def write_skill(
    root: Path,
    name: str,
    *,
    tier: list[str],
    obligations: list[str],
    max_tokens: int = 1000,
    status: str = "EXPERIMENTAL",
    dependencies: list[str] | None = None,
    conflicts: list[str] | None = None,
    frameworks: list[dict[str, str]] | None = None,
    valid_until: str | None = None,
    kind: str = "PROCESS_PROTOCOL",
    task_types: list[str] | None = None,
    positive_signals: list[str] | None = None,
) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8")
    (skill / "proofloop.skill.json").write_text(
        json.dumps(
            {
                "schemaVersion": "2.0",
                "id": name,
                "version": "1.0.0",
                "status": status,
                "kind": kind,
                "source": {"license": "MIT", "provenance": ["test-fixture"]},
                "activation": {
                    "modes": ["adaptive", "goal"],
                    "taskTypes": task_types or [],
                    "positiveSignals": positive_signals or [],
                    "negativeSignals": [],
                },
                "compatibility": {
                    "hosts": ["codex"],
                    "tiers": tier,
                    "languages": [],
                    "frameworks": frameworks or [],
                    "requiredTools": [],
                },
                "dependencies": dependencies or [],
                "conflicts": conflicts or [],
                "proof": {"closes": obligations, "adds": [], "minimumAuthority": "MODEL_REVIEW", "selfClosureAllowed": False},
                "context": {"required": ["intent-contract.json"], "maxInjectedTokens": 2000},
                "budget": {"maxTokens": max_tokens, "maxSeconds": 60, "maxInvocations": 1},
                "completion": {"artifact": "result.json", "schema": None},
                "escalation": {"on": ["UNKNOWN"]},
                "evaluation": {"evidenceLevel": "E0", "validUntil": valid_until, "scorecard": None},
            }
        )
        + "\n",
        encoding="utf-8",
    )


class SkillRegistryTest(unittest.TestCase):
    def test_resolver_intersects_tier_gap_compatibility_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "proofloop-review", tier=["T2", "T3"], obligations=["intent-alignment"])
            write_skill(root, "proofloop-verify", tier=["T0", "T1", "T2", "T3"], obligations=["deterministic-checks"])
            registry = SkillRegistry.discover(root)

            selected = registry.resolve(
                ResolutionContext(
                    mode="adaptive",
                    host="codex",
                    tier="T1",
                    open_obligations=("deterministic-checks", "intent-alignment"),
                    remaining_tokens=1500,
                )
            )

            self.assertEqual(["proofloop-verify"], [item.name for item in selected])

    def test_quarantined_and_over_budget_skills_are_never_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "proofloop-verify", tier=["T1"], obligations=["checks"], max_tokens=2000)
            manifest = root / "proofloop-verify" / "proofloop.skill.json"
            raw = json.loads(manifest.read_text())
            raw["status"] = "QUARANTINED"
            manifest.write_text(json.dumps(raw))
            registry = SkillRegistry.discover(root)

            selected = registry.resolve(
                ResolutionContext("adaptive", "codex", "T1", ("checks",), remaining_tokens=1000)
            )

            self.assertEqual([], selected)

    def test_registry_manifest_contains_content_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "proofloop-verify", tier=["T1"], obligations=["checks"])

            manifest = SkillRegistry.discover(root).to_dict()

            self.assertEqual("2.0", manifest["schemaVersion"])
            self.assertRegex(manifest["skills"][0]["contentHash"], r"^[0-9a-f]{64}$")
            self.assertEqual(manifest["skills"][0]["contentHash"], manifest["skills"][0]["bundleSha256"])

    def test_resolver_does_not_overcommit_cumulative_token_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "proofloop-intent", tier=["T0"], obligations=["intent"], max_tokens=700)
            write_skill(root, "proofloop-verify", tier=["T0"], obligations=["checks"], max_tokens=700)

            selected = SkillRegistry.discover(root).resolve(
                ResolutionContext("adaptive", "codex", "T0", ("intent", "checks"), remaining_tokens=1000)
            )

            self.assertEqual(1, len(selected))
            self.assertLessEqual(sum(item.max_tokens for item in selected), 1000)

    def test_bundle_hash_covers_references_not_only_manifest_and_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "proofloop-design", tier=["T2"], obligations=["design"])
            reference = root / "proofloop-design" / "references" / "example.md"
            reference.parent.mkdir()
            reference.write_text("first\n", encoding="utf-8")
            first = SkillRegistry.discover(root).skills[0].content_hash

            reference.write_text("second\n", encoding="utf-8")
            second = SkillRegistry.discover(root).skills[0].content_hash

            self.assertNotEqual(first, second)

    def test_dependency_cycle_and_missing_dependency_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "a", tier=["T1"], obligations=["a"], dependencies=["b"])
            with self.assertRaisesRegex(ValueError, "missing dependency"):
                SkillRegistry.discover(root)
            write_skill(root, "b", tier=["T1"], obligations=["b"], dependencies=["a"])
            with self.assertRaisesRegex(ValueError, "dependency cycle"):
                SkillRegistry.discover(root)

    def test_symlink_escape_is_rejected_from_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            write_skill(root, "proofloop-design", tier=["T2"], obligations=["design"])
            (root / "proofloop-design" / "references").mkdir()
            (root / "proofloop-design" / "references" / "escape.md").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "symlink"):
                SkillRegistry.discover(root)

    def test_framework_range_and_evidence_expiry_filter_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(
                root,
                "proofloop-backend",
                tier=["T1"],
                obligations=["api"],
                frameworks=[{"name": "django", "range": ">=5 <6"}],
            )
            write_skill(
                root,
                "proofloop-stale",
                tier=["T1"],
                obligations=["api"],
                valid_until="2000-01-01T00:00:00Z",
            )
            registry = SkillRegistry.discover(root)

            selected = registry.resolve(
                ResolutionContext(
                    "adaptive",
                    "codex",
                    "T1",
                    ("api",),
                    remaining_tokens=10_000,
                    frameworks=(("django", "5.1.2"),),
                )
            )
            incompatible = registry.resolve(
                ResolutionContext(
                    "adaptive",
                    "codex",
                    "T1",
                    ("api",),
                    remaining_tokens=10_000,
                    frameworks=(("django", "4.2.0"),),
                )
            )

            self.assertEqual(["proofloop-backend"], [item.name for item in selected])
            self.assertEqual([], incompatible)

    def test_conflicting_protocols_are_not_selected_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "a", tier=["T1"], obligations=["x"], conflicts=["b"])
            write_skill(root, "b", tier=["T1"], obligations=["x"], conflicts=["a"])

            selected = SkillRegistry.discover(root).resolve(
                ResolutionContext("adaptive", "codex", "T1", ("x",), remaining_tokens=10_000)
            )

            self.assertEqual(1, len(selected))

    def test_verified_contract_requires_live_existing_scorecard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "verified", tier=["T1"], obligations=["x"], status="VERIFIED")
            manifest = root / "verified" / "proofloop.skill.json"
            raw = json.loads(manifest.read_text())
            raw["evaluation"] = {
                "evidenceLevel": "E2",
                "validUntil": "2099-01-01T00:00:00Z",
                "scorecard": "evals/scorecard.json",
            }
            manifest.write_text(json.dumps(raw))

            with self.assertRaisesRegex(ValueError, "scorecard file does not exist"):
                SkillRegistry.discover(root)

            scorecard = root / "verified" / "evals" / "scorecard.json"
            scorecard.parent.mkdir()
            scorecard.write_text('{"schemaVersion":"1.0"}\n')
            self.assertEqual("VERIFIED", SkillRegistry.discover(root).skills[0].status)

    def test_invalid_authority_and_non_boolean_self_closure_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "invalid", tier=["T1"], obligations=["x"])
            manifest = root / "invalid" / "proofloop.skill.json"
            raw = json.loads(manifest.read_text())
            raw["proof"]["minimumAuthority"] = "MODEL_MAGIC"
            manifest.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "unsupported proof authority"):
                SkillRegistry.discover(root)

            raw["proof"]["minimumAuthority"] = "MODEL_REVIEW"
            raw["proof"]["selfClosureAllowed"] = "false"
            manifest.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "selfClosureAllowed must be boolean"):
                SkillRegistry.discover(root)

    def test_domain_pack_activates_from_task_type_and_adds_obligations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(
                root,
                "backend-development",
                tier=["T1"],
                obligations=[],
                kind="DOMAIN_PACK",
                task_types=["backend-development"],
            )
            manifest = root / "backend-development" / "proofloop.skill.json"
            raw = json.loads(manifest.read_text())
            raw["proof"]["adds"] = ["backend-contract-preserved"]
            manifest.write_text(json.dumps(raw))

            selected = SkillRegistry.discover(root).resolve(
                ResolutionContext(
                    "adaptive",
                    "codex",
                    "T1",
                    ("intent-alignment",),
                    remaining_tokens=10_000,
                    task_type="backend-development",
                    allow_experimental_domains=True,
                )
            )

            self.assertEqual(["backend-development"], [item.name for item in selected])

    def test_dependency_can_be_selected_for_domain_pack_without_own_gap_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_skill(root, "shared-probe", tier=["T1"], obligations=["different-gap"])
            write_skill(
                root,
                "backend-development",
                tier=["T1"],
                obligations=[],
                kind="DOMAIN_PACK",
                task_types=["backend-development"],
                dependencies=["shared-probe"],
            )
            manifest = root / "backend-development" / "proofloop.skill.json"
            raw = json.loads(manifest.read_text())
            raw["proof"]["adds"] = ["backend-contract-preserved"]
            manifest.write_text(json.dumps(raw))

            selected = SkillRegistry.discover(root).resolve(
                ResolutionContext(
                    "adaptive",
                    "codex",
                    "T1",
                    ("intent-alignment",),
                    remaining_tokens=10_000,
                    task_type="backend-development",
                    allow_experimental_domains=True,
                )
            )

            self.assertEqual(["shared-probe", "backend-development"], [item.name for item in selected])


if __name__ == "__main__":
    unittest.main()
