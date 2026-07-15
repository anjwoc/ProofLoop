#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("RUN", " ".join(command))
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if check and completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")
    return completed


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def copy_tree(source: Path, target: Path) -> None:
    remove_path(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "dist"))


def install_runtime(home: Path, dry_run: bool) -> dict[str, str]:
    runtime = home / "runtime"
    bin_dir = home / "bin"
    wrapper = bin_dir / "proofloop-core"
    if dry_run:
        print(f"DRY remove runtime -> {runtime}")
        print(f"DRY install runtime -> {runtime}")
        print(f"DRY install wrapper -> {wrapper}")
        return {"runtime": str(runtime), "wrapper": str(wrapper)}
    remove_path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("proofloop_core", "references"):
        copy_tree(ROOT / name, runtime / name)
    bin_dir.mkdir(parents=True, exist_ok=True)
    remove_path(wrapper)
    wrapper.write_text(
        "#!/bin/sh\n"
        f'PYTHONPATH="{runtime}:$PYTHONPATH" exec "{sys.executable}" -m proofloop_core.cli "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return {"runtime": str(runtime), "wrapper": str(wrapper)}


def merge_marketplace(path: Path, plugin_path: Path) -> None:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("name", "personal-plugins")
    data.setdefault("interface", {"displayName": "Personal Plugins"})
    plugins = data.setdefault("plugins", [])
    plugins[:] = [item for item in plugins if item.get("name") != "proofloop"]
    # marketplace file is at ~/.agents/plugins; source paths resolve from ~/.agents.
    relative = os.path.relpath(plugin_path, path.parents[2])
    plugins.append(
        {
            "name": "proofloop",
            "source": {"source": "local", "path": "./" + relative.replace(os.sep, "/")},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_codex(output: Path, scope: str, target: Path, dry_run: bool) -> dict[str, object]:
    home = Path.home()
    if scope == "user":
        plugin_target = home / ".codex" / "plugins" / "proofloop"
        agents_target = home / ".codex" / "agents"
        marketplace_target = home / ".agents" / "plugins" / "marketplace.json"
    else:
        plugin_target = target / "plugins" / "proofloop"
        agents_target = target / ".codex" / "agents"
        marketplace_target = target / ".agents" / "plugins" / "marketplace.json"
    codex = shutil.which("codex")
    commands = [
        [codex, "plugin", "remove", "proofloop@proofloop-local"],
        [codex, "plugin", "marketplace", "remove", "proofloop-local"],
        [codex, "plugin", "marketplace", "add", str(output)],
        [codex, "plugin", "add", "proofloop@proofloop-local"],
    ] if scope == "user" and codex else []
    if dry_run:
        print(f"DRY remove Codex ProofLoop plugin -> {plugin_target}")
        print(f"DRY remove Codex ProofLoop agents -> {agents_target / 'proofloop_*.toml'}")
        print(f"DRY copy Codex plugin -> {plugin_target}")
        print(f"DRY copy Codex agents -> {agents_target}")
        for command in commands:
            print("DRY", " ".join(command))
    else:
        if commands:
            run(commands[0], check=False)
            run(commands[1], check=False)
        copy_tree(output / "plugins" / "proofloop", plugin_target)
        agents_target.mkdir(parents=True, exist_ok=True)
        for stale in agents_target.glob("proofloop_*.toml"):
            remove_path(stale)
        for source in (output / "agents").glob("*.toml"):
            shutil.copy2(source, agents_target / source.name)
        merge_marketplace(marketplace_target, plugin_target)

    cli_status = "NOT_ATTEMPTED"
    if commands:
        if dry_run:
            cli_status = "DRY_RUN"
        else:
            add_market = run(commands[2], check=False)
            add_plugin = run(commands[3], check=False) if add_market.returncode == 0 else add_market
            cli_status = "PASS" if add_market.returncode == 0 and add_plugin.returncode == 0 else "FALLBACK_DIRECT_COPY"
    elif not codex:
        cli_status = "CLI_MISSING_DIRECT_COPY_USED"
    return {
        "host": "codex",
        "mode": "EXTERNAL_MODEL_ROUTING",
        "plugin": str(plugin_target),
        "agents": str(agents_target),
        "marketplace": str(marketplace_target),
        "cliInstall": cli_status,
        "nativeAgentConfigs": "INSTALLED_OPTIONAL",
        "next": "Restart Codex, then invoke $proofloop <request> or select proofloop from /skills.",
    }


def install_antigravity(output: Path, scope: str, target: Path, dry_run: bool) -> dict[str, object]:
    home = Path.home()
    destinations: list[tuple[Path, Path]] = []
    if scope == "user":
        destinations.extend(
            [
                (output / "skills", home / ".gemini" / "config" / "skills"),
                (output / "skills", home / ".gemini" / "antigravity-cli" / "skills"),
            ]
        )
        workflow_target = home / ".gemini" / "config" / "global_workflows" / "proofloop.md"
    else:
        destinations.append((output / "skills", target / ".agents" / "skills"))
        workflow_target = target / ".agent" / "workflows" / "proofloop.md"
    installed_skills: list[str] = []
    for source_root, destination_root in destinations:
        if dry_run:
            print(
                "DRY remove Antigravity ProofLoop skills -> "
                f"{destination_root}/proofloop* and {destination_root / 'using-proofloop'}"
            )
        if not dry_run and destination_root.exists():
            for stale in destination_root.glob("proofloop*"):
                remove_path(stale)
            remove_path(destination_root / "using-proofloop")
        for source in source_root.iterdir():
            destination = destination_root / source.name
            installed_skills.append(str(destination))
            if dry_run:
                print(f"DRY copy Antigravity skill -> {destination}")
            else:
                destination_root.mkdir(parents=True, exist_ok=True)
                copy_tree(source, destination)
    if dry_run:
        print(f"DRY remove Antigravity workflow -> {workflow_target}")
        print(f"DRY copy Antigravity workflow -> {workflow_target}")
    else:
        workflow_target.parent.mkdir(parents=True, exist_ok=True)
        remove_path(workflow_target)
        shutil.copy2(output / "workflows" / "proofloop.md", workflow_target)
    return {
        "host": "antigravity",
        "mode": "ROLE_ROUTING_ONLY",
        "skills": installed_skills,
        "workflow": str(workflow_target),
        "nativeInteractiveMode": "ROLE_ROUTING_ONLY",
        "crossModelRouting": False,
        "permissionBypass": "OPT_IN_WITH_PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1",
        "next": "Restart Antigravity and invoke /proofloop <request>.",
    }


def install_claude(output: Path, scope: str, dry_run: bool) -> dict[str, object]:
    claude = shutil.which("claude")
    if not claude:
        return {"host": "claude-code", "mode": "EXTERNAL_MODEL_ROUTING", "status": "CLI_MISSING", "built": str(output)}
    commands = [
        [claude, "plugin", "validate", str(output), "--strict"],
        [claude, "plugin", "uninstall", "proofloop@proofloop-local", "--scope", scope, "--yes"],
        [claude, "plugin", "marketplace", "remove", "proofloop-local", "--scope", scope],
        [claude, "plugin", "marketplace", "add", str(output), "--scope", scope],
        [claude, "plugin", "install", "proofloop@proofloop-local", "--scope", scope],
    ]
    if dry_run:
        for command in commands:
            print("DRY", " ".join(command))
    else:
        run(commands[0])
        run(commands[1], check=False)
        run(commands[2], check=False)
        run(commands[3])
        run(commands[4])
    return {
        "host": "claude-code",
        "mode": "EXTERNAL_MODEL_ROUTING",
        "nativeAgentConfigs": "INSTALLED_OPTIONAL",
        "status": "DRY_RUN" if dry_run else "PASS",
        "next": "Restart Claude Code and invoke /proofloop <request>.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and install ProofLoop Core adapters")
    parser.add_argument("--host", choices=["claude-code", "codex", "antigravity", "all"], default="all")
    parser.add_argument("--scope", choices=["user", "project", "local"], default="user")
    parser.add_argument("--target", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    target = Path(args.target).resolve()
    home = Path(os.environ.get("PROOFLOOP_HOME", Path.home() / ".proofloop"))
    runtime = install_runtime(home, args.dry_run)
    hosts: Iterable[str] = ("claude-code", "codex", "antigravity") if args.host == "all" else (args.host,)
    results: list[dict[str, object]] = []
    for host in hosts:
        name = "claude" if host == "claude-code" else host
        output = ROOT / "dist" / name
        run([sys.executable, str(ROOT / "scripts" / "build_host_adapter.py"), "--host", host, "--output", str(output)])
        if args.build_only:
            results.append({"host": host, "built": str(output)})
        elif host == "codex":
            results.append(install_codex(output, args.scope, target, args.dry_run))
        elif host == "antigravity":
            results.append(install_antigravity(output, args.scope, target, args.dry_run))
        else:
            results.append(install_claude(output, args.scope, args.dry_run))
    print(json.dumps({"runtime": runtime, "adapters": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
