---
name: proofloop-design
description: Design T2 or T3 ProofLoop changes by comparing the smallest viable design with a credible alternative against intent, repository facts, invariants, failure modes, rollback, and proof seams. Use internally before planning when architecture judgment is required or recovery reveals a design conflict.
---

# ProofLoop Design

## Core principle

Choose the smallest design that satisfies the intent and repository invariants. Novelty and abstraction are costs that require evidence.

## Authority boundary

- Read intent, repository context, exploration evidence, and open proof obligations.
- Write only the assigned design artifact.
- Do not edit source, broaden scope, close deterministic obligations, or treat architectural prose as runtime proof.
- Prefer repository facts over generic best practices and external reference examples.

## Preconditions

Confirm before designing:

- the objective and acceptance criteria are stable enough to compare designs
- target seams, callers, existing tests, and protected boundaries are known
- hard constraints and non-goals are visible
- any public contract, persistent state, auth, migration, concurrency, or deployment surface is identified

If a missing fact could reverse the decision, stop with `UNKNOWN_CONSTRAINT` instead of assuming it.

## Decision procedure

1. Extract criteria, constraints, non-goals, and unresolved unknowns from the intent contract.
2. Extract target seams, callers, tests, conventions, and risk surfaces from repository evidence.
3. State invariants that must remain true before and after the change.
4. Describe the smallest viable design using existing seams where possible.
5. Describe one credible alternative with a meaningfully different trade-off.
6. Compare both options against criterion coverage, change surface, failure modes, rollback, observability, and proof cost.
7. Reject abstraction whose reuse, isolation, safety, or testability benefit is not required now.
8. Select one option and state why its disadvantages are acceptable.
9. Map affected boundaries and data/control flow.
10. Identify proof seams: where a deterministic check or observation can demonstrate each critical invariant.

## Comparison table

Use evidence-backed entries rather than scores without anchors.

| Axis | Smallest viable design | Credible alternative |
| --- | --- | --- |
| Acceptance coverage | Which criteria and how | Which criteria and how |
| Repository fit | Existing seams reused | New or changed seams |
| Change surface | Files/layers/contracts | Files/layers/contracts |
| Failure modes | Concrete failures | Concrete failures |
| Rollback | Reversal boundary | Reversal boundary |
| Proof cost | Checks and observations | Checks and observations |

Do not manufacture an alternative that is obviously bad. If there is no credible alternative, explain why the repository already constrains the design to one path.

## Invariants and proof seams

State invariants as falsifiable claims:

- existing callers receive the same public contract
- retries cannot duplicate a persistent write
- authorization is checked before state mutation
- cleanup runs exactly once after terminal failure

For each invariant, identify the cheapest authoritative evidence. A model review can assess intent and simplicity; it cannot replace a failing build, test, schema check, or runtime trace.

## Failure and rollback analysis

Trace at least:

- input and validation failure
- partial state or interrupted execution
- downstream dependency failure
- retry, cancellation, and timeout when relevant
- deployment or migration rollback when relevant

Keep rollback proportional. A local pure-code change may only need a clean revert boundary; persistent or external state requires an explicit restoration or forward-fix strategy.

## Stop and escalate

Return `DESIGN_CONFLICT` or `UNKNOWN_CONSTRAINT` when:

- intent criteria conflict with repository invariants
- the smallest viable option requires unauthorized scope
- public compatibility or data safety cannot be evaluated
- all credible options require a product decision
- rollback is impossible for a high-risk mutation and the request does not acknowledge it

Do not solve these by silently selecting the most convenient option.

## Artifact contract

Record:

- `decision`
- `repositoryFacts`
- `invariants`
- `options`
- `selectedOption`
- `tradeoffs`
- `affectedBoundaries`
- `dataFlow` or `controlFlow`
- `failureModes`
- `rollback`
- `proofSeams`
- `rejectedAbstractions`
- `unknowns`

Mark each statement as fact, inference, or unknown with provenance where the schema permits.

## Anti-patterns

- Do not start with a preferred technology and retrofit the problem.
- Do not propose a new service, framework, or dependency without a current requirement.
- Do not confuse more layers with safer design.
- Do not quote generic architecture guidance when nearby repository code provides stronger evidence.
- Do not call an option “simple” without describing its change and proof surface.
- Do not hide unresolved product choices inside an implementation plan.

## Example

Task: invoke cleanup after an orchestration recovery loop is exhausted.

Smallest viable design: add one explicit exhausted-to-cleanup transition in the existing FSM and verify terminal ordering.

Credible alternative: wrap every terminal transition in a new lifecycle middleware abstraction.

Select the first when cleanup is the only new terminal behavior and the FSM already owns transitions. Reject the middleware because its broader indirection and migration surface do not close an additional proof gap.

## Completion checklist

- [ ] Repository facts and intent constraints drive the decision.
- [ ] Invariants are falsifiable.
- [ ] A credible alternative was compared or its absence justified.
- [ ] Failure, rollback, and proof seams are explicit.
- [ ] Added abstraction has current evidence or is rejected.
- [ ] Unknowns that can reverse the decision are escalated.
- [ ] The design does not claim runtime proof.
