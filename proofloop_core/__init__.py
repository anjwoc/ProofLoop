"""ProofLoop automatic evidence-driven coding harness."""

__version__ = "0.4.0a0"

# ponytail: backward-compatibility import routing for role-segregated subpackages
import sys
import importlib
import importlib.util
from importlib.abc import MetaPathFinder, Loader

_LEGACY_MAP = {
    "orchestrator": "proofloop_core.engine.orchestrator",
    "external_loop": "proofloop_core.engine.external_loop",
    "strategy": "proofloop_core.engine.strategy",
    "intent": "proofloop_core.engine.intent",
    "intent_gate": "proofloop_core.engine.intent_gate",
    "attempts": "proofloop_core.engine.attempts",
    "reconciler": "proofloop_core.engine.reconciler",
    "domain_runtime": "proofloop_core.engine.domain_runtime",
    "skill_qualification": "proofloop_core.engine.skill_qualification",
    "skill_registry": "proofloop_core.engine.skill_registry",
    "repair": "proofloop_core.engine.repair",

    "runtime": "proofloop_core.runtimes.runtime",
    "hosts": "proofloop_core.runtimes.hosts",
    "host_adapter": "proofloop_core.runtimes.host_adapter",
    "host_runner": "proofloop_core.runtimes.host_runner",
    "acp_runner": "proofloop_core.runtimes.acp_runner",
    "process_runner": "proofloop_core.runtimes.process_runner",
    "adapters": "proofloop_core.runtimes.adapters",

    "blueprint": "proofloop_core.contracts.blueprint",
    "capability_contract": "proofloop_core.contracts.capability_contract",
    "execution_brief": "proofloop_core.contracts.execution_brief",
    "expected_output": "proofloop_core.contracts.expected_output",
    "goal": "proofloop_core.contracts.goal",
    "request_envelope": "proofloop_core.contracts.request_envelope",
    "role_view": "proofloop_core.contracts.role_view",
    "run_state": "proofloop_core.contracts.run_state",
    "task_brief": "proofloop_core.contracts.task_brief",
    "verification_plan": "proofloop_core.contracts.verification_plan",

    "usage": "proofloop_core.analysis.usage",
    "tokscale": "proofloop_core.analysis.tokscale",
    "usage_viewer": "proofloop_core.analysis.usage_viewer",
    "benchmark": "proofloop_core.analysis.benchmark",
    "benchmark_environment": "proofloop_core.analysis.benchmark_environment",
    "swe_skills_bench": "proofloop_core.analysis.swe_skills_bench",
    "workload": "proofloop_core.analysis.workload",

    "truth": "proofloop_core.assurance.truth",
    "assurance": "proofloop_core.assurance.assurance",
    "checks": "proofloop_core.assurance.checks",
    "diff_guard": "proofloop_core.assurance.diff_guard",
    "live_evidence": "proofloop_core.assurance.live_evidence",
    "preflight": "proofloop_core.assurance.preflight",

    "events": "proofloop_core.context.events",
    "memory": "proofloop_core.context.memory",
    "proof_graph": "proofloop_core.context.proof_graph",
    "trace": "proofloop_core.context.trace",
    "repository_context": "proofloop_core.context.repository_context",
    "fingerprint": "proofloop_core.context.fingerprint",
    "git_snapshot": "proofloop_core.context.git_snapshot",
    "grounding": "proofloop_core.context.grounding",
    "redact": "proofloop_core.context.redact",
    "io": "proofloop_core.context.io",

    "cli": "proofloop_core.ui.cli",
    "tui": "proofloop_core.ui.tui",
    "relay": "proofloop_core.ui.relay",
    "watch": "proofloop_core.ui.watch",
}

class _AliasLoader(Loader):
    def __init__(self, real_loader, target_name):
        self._real_loader = real_loader
        self._target_name = target_name

    def create_module(self, spec):
        mod = importlib.import_module(self._target_name)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass

    def get_filename(self, fullname):
        if hasattr(self._real_loader, "get_filename"):
            return self._real_loader.get_filename(self._target_name)
        return None

    def is_package(self, fullname):
        if hasattr(self._real_loader, "is_package"):
            return self._real_loader.is_package(self._target_name)
        return False

    def get_code(self, fullname):
        if hasattr(self._real_loader, "get_code"):
            return self._real_loader.get_code(self._target_name)
        return None

    def get_source(self, fullname):
        if hasattr(self._real_loader, "get_source"):
            return self._real_loader.get_source(self._target_name)
        return None

_finding = set()

class _LegacySubpackageFinder(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in _finding:
            return None
        if fullname.startswith("proofloop_core."):
            submod = fullname[len("proofloop_core."):]
            if submod in _LEGACY_MAP:
                _finding.add(fullname)
                try:
                    target_mod = _LEGACY_MAP[submod]
                    target_spec = importlib.util.find_spec(target_mod)
                    if target_spec is not None:
                        return importlib.util.spec_from_loader(
                            fullname, _AliasLoader(target_spec.loader, target_mod)
                        )
                finally:
                    _finding.discard(fullname)
        return None

sys.meta_path.insert(0, _LegacySubpackageFinder())
