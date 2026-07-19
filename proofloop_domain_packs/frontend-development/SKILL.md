---
name: frontend-development
description: Implement frontend behavior through existing component, state, accessibility, and visual contracts with verifiable user outcomes.
---

# Frontend Development

## Core principle

Prove the user-visible behavior through the repository's existing UI system; do not trade accessibility, state correctness, or regression safety for a screenshot-shaped patch.

## Authority boundary

Edit only authorized UI, style, state, and test paths. Reuse the installed design system and tokens. You may not redefine product language, navigation, analytics semantics, or accessibility policy without explicit intent. Browser screenshots and model judgment support review but do not close deterministic obligations by themselves.

## Inputs

Read the intent contract, target routes/components, repository fingerprint, current visual and test conventions, and selected references. Determine whether the task is behavior, layout, visual polish, data flow, accessibility, or a combination. Unknown product decisions remain unknown.

## Procedure

1. Identify the user action and observable outcome for every acceptance criterion.
2. Locate the route, owning component, data/state boundary, design tokens, and closest tests or stories.
3. Trace loading, empty, success, error, disabled, and permission-dependent states that already exist.
4. Preserve semantic HTML, focus order, keyboard operation, accessible names, and contrast behavior.
5. Reuse components and tokens before adding variants or CSS primitives.
6. Make the smallest vertical UI change, including state wiring and error behavior.
7. Add a failing component or browser-level assertion at the stable user boundary when feasible.
8. Verify responsive behavior at repository-supported breakpoints, not arbitrary device lists.
9. Run static checks and focused tests, then inspect the rendered result when a browser harness exists.
10. Review the diff for hardcoded colors, duplicate components, unstable selectors, hydration hazards, and leaked internal errors.

## State and interaction checklist

- A user can discover and operate the control with keyboard and assistive semantics.
- Pending operations prevent accidental duplicate submission when necessary.
- Loading and error states do not erase recoverable user input.
- Server and client state ownership follows repository conventions.
- Analytics events preserve names and payload contracts or are explicitly authorized.
- Visual change uses the current token/variant system.
- Tests assert user outcomes rather than component internals.

## Stop and escalate

Return `NEEDS_CONTEXT` when the owning route, design token, data contract, or runnable UI verifier is unavailable. Return `BLOCKED` when the request depends on an unspecified product choice, destructive navigation change, new tracking policy, or inaccessible design requirement. Do not guess copy, permissions, or responsive behavior that materially changes the product.

## Anti-patterns

- Do not add a parallel component when an existing variant is sufficient.
- Do not encode state in CSS when it belongs in the application state model.
- Do not use placeholder click handlers or fabricated API data.
- Do not remove focus outlines or semantic labels for visual cleanliness.
- Do not snapshot large markup trees as the sole behavior test.
- Do not load a React adapter unless React was actually detected.

## Artifact contract

Report routes/components changed, user states covered, accessibility checks, visual evidence locations, commands run, adapter/reference IDs, and unresolved risks. Separate facts observed in code/browser from inferences. Never report “pixel perfect” without a defined reference and comparable capture.

## Worked example

For “add retry to a failed data panel,” locate the existing error boundary and query ownership, reuse the standard button, preserve focus and pending state, invoke the existing refetch path, and test error → retry → success. Do not add a second fetch state machine inside the panel.

For “make the dashboard more modern” without a target, acceptance criteria, or permitted surface, stop and request a product/design constraint rather than restyling the application broadly.

## Resource routing

Always use the common reference. Load framework guidance only when selected from the fingerprint. Browser verification is required only when the repository has a supported runnable surface and the criterion is visual or interactive; otherwise document the unavailable evidence seam.

## Completion checklist

- Acceptance criteria map to user-observable states.
- Component, state, and data ownership follow existing patterns.
- Keyboard and accessibility consequences were checked.
- Focused automated checks are fresh.
- Visual evidence is captured when material and feasible.
- No unrelated design-system or route changes are present.
