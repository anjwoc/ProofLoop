# Ignore-Safe Worktree Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `snapshot_worktree()` succeed when `.proofloop/` is ignored while continuing to exclude all ProofLoop evidence from the ephemeral baseline.

**Architecture:** Populate the temporary Git index using normal ignore semantics, then remove `.proofloop` from that temporary index with an ignore-tolerant cached removal. The user's index and worktree remain untouched because every Git index operation uses `GIT_INDEX_FILE`.

**Tech Stack:** Python standard library, Git CLI, `unittest`

## Global Constraints

- Preserve the user's real Git index and branch.
- Exclude `.proofloop` whether it is ignored, untracked, or already tracked.
- Add no runtime dependency.
- Use a real temporary repository in the regression test.

---

### Task 1: Ignore-safe ephemeral snapshot

**Files:**
- Create: `tests/deterministic/test_git_snapshot.py`
- Modify: `proofloop_core/git_snapshot.py:44-48`

**Interfaces:**
- Consumes: `snapshot_worktree(repository: str | Path) -> str`
- Produces: an unreachable commit whose tree represents the worktree without `.proofloop`

- [ ] **Step 1: Write the failing regression test**

Create a temporary Git repository with `.gitignore` containing `.proofloop/`, commit a tracked source file, then create ignored `.proofloop` evidence and an uncommitted source change. Call `snapshot_worktree()`, assert it returns a commit, assert the source change is present in that commit, assert `.proofloop` is absent, and assert the real index is unchanged.

- [ ] **Step 2: Run the regression test and verify RED**

Run: `python3 -m unittest tests.deterministic.test_git_snapshot -v`

Expected: the snapshot call raises the current ignored-path `RuntimeError`.

- [ ] **Step 3: Implement the minimal fix**

Replace the explicit negative pathspecs with:

```python
_git(repo, "add", "-A", "--", ".", env=env)
_git(repo, "rm", "-r", "--cached", "--ignore-unmatch", "--", ".proofloop", env=env)
```

Both commands operate only on the temporary index.

- [ ] **Step 4: Verify GREEN and regression safety**

Run:

```bash
python3 -m unittest tests.deterministic.test_git_snapshot -v
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

Expected: all commands pass.

- [ ] **Step 5: Sync, reinstall, and verify installed runtime**

Run:

```bash
codegraph sync .
python3 scripts/install.py --host all --scope user
cmp proofloop_core/git_snapshot.py "$HOME/.proofloop/runtime/proofloop_core/git_snapshot.py"
```

Expected: all three host adapters install successfully and the installed runtime matches the fixed source.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/plans/2026-07-14-ignore-safe-worktree-snapshot.md \
  proofloop_core/git_snapshot.py tests/deterministic/test_git_snapshot.py
git commit -m "fix: snapshot repositories with ignored ProofLoop evidence"
```
