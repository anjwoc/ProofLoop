.PHONY: check test build build-claude build-codex build-antigravity install install-codex install-antigravity doctor live live-codex live-codex-recovery live-antigravity live-antigravity-recovery release-check development-check clean

check:
	python3 scripts/validate_package.py
	python3 scripts/run_tests.py
	python3 -m compileall -q proofloop_core scripts

test:
	python3 scripts/run_tests.py

build: build-claude build-codex build-antigravity

build-claude:
	python3 scripts/build_host_adapter.py --host claude-code

build-codex:
	python3 scripts/build_host_adapter.py --host codex

build-antigravity:
	python3 scripts/build_host_adapter.py --host antigravity

install:
	python3 scripts/install.py --host all --scope user

install-codex:
	python3 scripts/install.py --host codex --scope user

install-antigravity:
	python3 scripts/install.py --host antigravity --scope user

doctor:
	python3 scripts/doctor.py

live: live-codex live-antigravity

live-codex:
	python3 scripts/run_host_live.py --host codex --scenario normal --keep-workspace

live-codex-recovery:
	python3 scripts/run_host_live.py --host codex --scenario recovery --keep-workspace

live-antigravity:
	python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace

live-antigravity-recovery:
	python3 scripts/run_host_live.py --host antigravity --scenario recovery --keep-workspace

release-check:
	python3 scripts/release_check.py

development-check:
	python3 scripts/release_check.py --development

clean:
	rm -rf dist build *.egg-info __pycache__ proofloop_core/__pycache__ scripts/__pycache__ tests/**/__pycache__
