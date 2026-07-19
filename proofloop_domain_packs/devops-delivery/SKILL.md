---
name: devops-delivery
description: Change CI, deployment, infrastructure, and GitOps artifacts with bounded blast radius, reproducibility, and rollback evidence.
---

# DevOps and Delivery

## Core principle

A delivery change is correct only when its rendered artifact, execution ordering, secret boundary, and rollback path are understood—not merely when the YAML parses.

## Authority boundary

Edit only authorized workflow, manifest, policy, or infrastructure paths. Never execute deployment, credential, destructive cloud, or remote mutation commands unless separately authorized. Local render, lint, schema, and dry-run evidence may close deterministic gaps; model review cannot prove production safety.

## Inputs

Read the intent, repository fingerprint, environment layout, target workflow/overlay, protected paths, current checks, and selected adapter references. Identify whether the change affects build, test, package, deploy, promotion, rollback, or policy.

## Procedure

1. Map trigger/input → job/stage → artifact → target environment → observable result.
2. Identify environment inheritance, overlays, reusable workflows, and generated artifacts.
3. Record secret sources, permissions, identity boundaries, and untrusted input interpolation.
4. Determine ordering, concurrency, retry, timeout, cancellation, and rollback behavior.
5. Reuse existing actions, images, modules, bases, and version-pinning policy.
6. Make the smallest source change; do not edit rendered/generated output unless it is the canonical source.
7. Run syntax/schema validation and the repository's local render or dry-run command.
8. Compare rendered output or job graph before and after for unintended drift.
9. Test a failure path such as missing input, failed gate, or rollback selection when feasible.
10. Report what remains unverified without remote execution.

## Safety checklist

- Tokens and secrets are never printed or passed through untrusted shell interpolation.
- Permissions are least-privilege and explicit where supported.
- Third-party actions/images/modules follow repository pinning rules.
- Promotion cannot bypass required checks.
- Concurrency does not race destructive or stateful operations.
- Rollback points to a known prior artifact/configuration.
- Environment-specific values remain in their existing ownership layer.
- Rendered output contains only intended resource/job changes.

## Stop and escalate

Return `BLOCKED` for missing deployment authority, unknown secret ownership, destructive state migration, unreviewable generated drift, or a requested permission broadening. Return `NEEDS_CONTEXT` when the canonical source, environment inheritance, or local verifier cannot be determined. Never "test" by deploying.

## Anti-patterns

- YAML parse success is not deployment proof.
- Do not duplicate a reusable workflow or base to avoid understanding inputs.
- Do not change `latest`/floating pins silently.
- Do not add broad write permissions to fix one failed step.
- Do not suppress a policy or health gate to make promotion pass.
- Do not assume Kustomize, Flux, or GitHub Actions without fingerprint evidence.

## Artifact contract

Report changed source artifacts, selected environment/overlay, before/after render summary, validation commands, security boundary, rollback path, adapter IDs, and remote-only unknowns. Keep command output as parent-owned evidence.

## Worked example

For “add a smoke test before production deploy,” insert it at the existing promotion seam, consume the existing artifact, use the current credential boundary, make deploy depend on the smoke result, and verify the local workflow graph/schema. Do not create a second deploy path.

For “apply this manifest to production,” stop unless explicit external mutation authority and environment safeguards are present.

## Resource routing

Use common delivery guidance always. Load GitHub Actions, Kustomize, or Flux details only when selected by fingerprint. Prefer local render and validation helpers; record unavailable tools as evidence gaps rather than installing or simulating them silently.

## Completion checklist

- Canonical source and affected environment are identified.
- Syntax plus semantic/render checks are fresh.
- Secrets, permissions, ordering, concurrency, and rollback were considered.
- No remote mutation occurred without authority.
- Unverified production behavior is clearly labeled.
