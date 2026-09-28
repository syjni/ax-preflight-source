# AX Results Console UI redesign handoff

## Files in this folder

- `current-answered-static.html`: script-free snapshot of the current rendered `answered` DEV fixture. It is a visual reference and has no working interactions.
- `current-answered-1280.png`: current desktop viewport.
- `current-answered-768.png`: current tablet viewport.

## Authoritative implementation files

The snapshot data is synthetic and must not be treated as an API contract. Preserve behavior and data semantics from:

- `../../src/generated/api.ts`
- `../../src/App.tsx`
- `../../src/components/`
- `../../src/viewModel.ts`
- `../../src/provenance.ts`

## Redesign scope

Redesign the information hierarchy, typography, spacing, color, and responsive presentation. Keep the current API types, run lifecycle, dataset provenance warnings, evidence verdict meanings, DEV-only fixture boundary, and accessibility behavior.

The current page gives developer controls more prominence than the diagnostic outcome, uses many 10–11 px labels, and repeats nearly identical line-based section treatments. Make the readiness result, delivery verdict, and evidence status understandable within the first viewport while retaining access to the run controls and technical details.
