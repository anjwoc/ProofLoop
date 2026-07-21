import unittest
from proofloop_core.prompting.prompt_ir import PromptIR, PromptMetadata

class PromptIRTest(unittest.TestCase):
    def test_prompt_ir_schema(self):
        metadata = PromptMetadata(compiler_version="1.0", generation_time="2026-07-21T00:00:00Z")
        ir = PromptIR(
            prompt_id="P-1",
            request_id="R-1",
            contract_id="C-1",
            blueprint_id="B-1",
            role="implementer_fast",
            goal="Fix the bug",
            stop_when="tests pass",
            deliverables=("src/main.py",),
            evidence_requirements=("pytest passed",),
            allowed_scope=("src/",),
            protected_scope=("tests/",),
            must_do=("Use standard library",),
            must_not=("Change API",),
            context_refs=("issue-123",),
            allowed_tools=("pytest",),
            output_contract="json",
            escalate_when=("timeout",),
            metadata=metadata
        )
        self.assertEqual("P-1", ir.prompt_id)
        d = ir.to_dict()
        self.assertEqual("P-1", d["prompt_id"])
        self.assertEqual(["src/main.py"], d["deliverables"])
        self.assertEqual("1.0", d["metadata"]["compiler_version"])

if __name__ == "__main__":
    unittest.main()
