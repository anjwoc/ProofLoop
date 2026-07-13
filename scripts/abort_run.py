#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proofloop_core.cli import main
raise SystemExit(main(["abort-run", *sys.argv[1:]]))
