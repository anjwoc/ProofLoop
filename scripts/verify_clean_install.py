#!/usr/bin/env python3
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> int:
    """Verify clean install isolation.
    ponytail: the simplest possible check - can it pip install and run --help in a fresh venv without missing deps?
    """
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_dir = Path(tmpdir) / "venv"
        venv.create(venv_dir, with_pip=True)
        pip = venv_dir / "bin" / "pip"
        executable = venv_dir / "bin" / "proofloop-core"

        print("Installing ProofLoop in clean venv...")
        subprocess.run([str(pip), "install", str(root)], check=True)

        print("Verifying executable works...")
        subprocess.run([str(executable), "--help"], check=True)

    print("Clean install isolation verification PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
