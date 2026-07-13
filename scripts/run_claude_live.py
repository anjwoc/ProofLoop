#!/usr/bin/env python3
# Retained for compatibility. Claude remains a separate, higher-cost acceptance runner.
from __future__ import annotations
import runpy
runpy.run_path(str(__import__('pathlib').Path(__file__).resolve().with_name('_run_claude_live_legacy.py')), run_name='__main__')
