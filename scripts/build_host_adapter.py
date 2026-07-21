#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proofloop_core.hosts import agy_workflow, capability, write_codex_agents
from proofloop_core.skill_registry import SkillRegistry


def remove_tree(path: Path, *, attempts: int = 5) -> None:
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.05 * (attempt + 1))


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        remove_tree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "dist"))



def specialize_entry_skill(skill_root: Path, host: str) -> None:
    path = skill_root / "proofloop" / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("--host <current-host>", f"--host {host}")
    text = text.replace("Determine the current host as exactly one of `claude-code`, `codex`, or `agy`.", f"Use the fixed installed host `{host}`.")
    if host == "agy":
        # Goalng invokes AGY with this permission mode.  The entry host has
        # already received the user's mutation request, and the detached
        # child roles must inherit the same non-interactive permission mode.
        text = text.replace(
            "nohup $HOME/.proofloop/bin/proofloop-core run \\",
            "PROOFLOOP_AGY_BYPASS_PERMISSIONS=1 nohup $HOME/.proofloop/bin/proofloop-core run \\",
        )
    path.write_text(text, encoding="utf-8")


def write_skill_manifest(protocol_root: Path, domain_root: Path, target: Path) -> None:
    registry = SkillRegistry(
        [
            *SkillRegistry.discover(protocol_root).skills,
            *SkillRegistry.discover(domain_root).skills,
        ]
    )
    target.write_text(
        json.dumps(registry.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_claude(root: Path, output: Path) -> None:
    plugin_root = output / "plugins" / "proofloop"
    (output / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    marketplace = json.loads((root / "plugin" / "marketplace.json").read_text(encoding="utf-8"))
    plugin = json.loads((root / "plugin" / "plugin.json").read_text(encoding="utf-8"))
    (output / ".claude-plugin" / "marketplace.json").write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(json.dumps(plugin, indent=2) + "\n", encoding="utf-8")
    for name in ("skills", "proofloop_protocols", "proofloop_domain_packs", "agents", "scripts", "proofloop_core", "references", "hooks"):
        copy_tree(root / name, plugin_root / name)
    specialize_entry_skill(plugin_root / "skills", "claude-code")
    write_skill_manifest(plugin_root / "proofloop_protocols", plugin_root / "proofloop_domain_packs", plugin_root / "installed-skills.json")


def build_codex(root: Path, output: Path) -> None:
    plugin_root = output / "plugins" / "proofloop"
    (output / ".agents" / "plugins").mkdir(parents=True, exist_ok=True)
    (plugin_root / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    marketplace = {
        "name": "proofloop-local",
        "interface": {"displayName": "ProofLoop Local"},
        "plugins": [
            {
                "name": "proofloop",
                "source": {"source": "local", "path": "./plugins/proofloop"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Developer Tools",
                "interface": {"displayName": "ProofLoop Core"},
            }
        ],
    }
    manifest = {
        "name": "proofloop",
        "version": "0.4.0-alpha",
        "description": "One-command evidence-based coding harness with automatic model roles, deterministic checks, bounded repair, and truth-gated completion.",
        "skills": "./skills/",
        "hooks": "./hooks/hooks.json",
        "license": "MIT",
        "keywords": ["verification", "repair-loop", "truth-gate", "subagents"],
        "interface": {
            "displayName": "ProofLoop Core",
            "shortDescription": "Plan deeply, implement cheaply, verify deterministically.",
            "longDescription": "Uses Codex custom agents for Sol planning/recovery/review and Terra bounded implementation, while refusing completion without deterministic evidence.",
            "developerName": "ProofLoop",
            "category": "Developer Tools",
            "capabilities": ["Read", "Write"],
            "defaultPrompt": ["Use ProofLoop to implement this change with real checks and evidence."],
        },
    }
    (output / ".agents" / "plugins" / "marketplace.json").write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")
    (plugin_root / ".codex-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for name in ("skills", "proofloop_protocols", "proofloop_domain_packs", "proofloop_core", "references"):
        copy_tree(root / name, plugin_root / name)
    specialize_entry_skill(plugin_root / "skills", "codex")
    write_skill_manifest(plugin_root / "proofloop_protocols", plugin_root / "proofloop_domain_packs", plugin_root / "installed-skills.json")
    hooks_dir = plugin_root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "scripts" / "host_trace_hook.py", hooks_dir / "host_trace_hook.py")
    shutil.copy2(root / "scripts" / "truth_stop_hook.py", hooks_dir / "truth_stop_hook.py")
    hooks = {
        "hooks": {
            "SubagentStop": [
                {
                    "matcher": "proofloop_.*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 ${PLUGIN_ROOT}/hooks/host_trace_hook.py --host codex",
                            "timeout": 10,
                            "statusMessage": "Recording ProofLoop subagent evidence",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 ${PLUGIN_ROOT}/hooks/truth_stop_hook.py --host codex",
                            "timeout": 10,
                            "statusMessage": "Checking ProofLoop truth gate",
                        }
                    ]
                }
            ],
        }
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
    write_codex_agents(output / "agents")


def build_agy(root: Path, output: Path) -> None:
    copy_tree(root / "skills", output / "skills")
    copy_tree(root / "proofloop_protocols", output / "proofloop_protocols")
    copy_tree(root / "proofloop_domain_packs", output / "proofloop_domain_packs")
    specialize_entry_skill(output / "skills", "agy")
    write_skill_manifest(output / "proofloop_protocols", output / "proofloop_domain_packs", output / "installed-skills.json")
    (output / "workflows").mkdir(parents=True, exist_ok=True)
    (output / "workflows" / "proofloop.md").write_text(agy_workflow(), encoding="utf-8")
    (output / "capability.json").write_text(
        json.dumps(
            {
                "host": "agy",
                "mode": "EXTERNAL_MODEL_ROUTING",
                "crossModelRouting": True,
                "deterministicSidecar": "$HOME/.proofloop/bin/proofloop-core",
                "roles": capability("agy")["roles"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a ProofLoop host adapter")
    parser.add_argument("--host", choices=["claude-code", "codex", "agy"], required=True)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    name = "claude" if args.host == "claude-code" else args.host
    output = Path(args.output).resolve() if args.output else root / "dist" / name
    if output.exists():
        remove_tree(output)
    output.mkdir(parents=True, exist_ok=True)
    if args.host == "claude-code":
        build_claude(root, output)
    elif args.host == "codex":
        build_codex(root, output)
    else:
        build_agy(root, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
