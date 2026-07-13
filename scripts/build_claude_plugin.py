#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--root", default=str(ROOT))
parser.add_argument("--output", default="dist/claude")
args = parser.parse_args()
raise SystemExit(subprocess.call([sys.executable, str(ROOT / "scripts" / "build_host_adapter.py"), "--host", "claude-code", "--root", args.root, "--output", args.output]))
