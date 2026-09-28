# AX Experiment v3 Freeze Result

Experiment: `ax-exp-v3`

Status: **FROZEN**

Official backend: `SEMI_AUTOMATED_FRESH_PROCESS`

Run design: `16 tasks × 2 conditions × 2 repetitions = 64 runs`

Held-out valid executions: `0`

Held-out task prompts submitted: `0`

Regression tests: `113/113 PASS`

## v3 change boundary

The only substantive v3 changes are exact submitted-prompt validation and fresh-process execution orchestration. The v2 dataset, defect variants, bindings, prompt, model, tools, retrieval, Scanner, benchmark, ground truth, Readiness/scoring, and failure taxonomy remain frozen and unchanged.

The official backend is semi-automated because the investigated Kiro CLI 2.22.1 non-interactive paths did not jointly produce a successful response, persistent one-turn session, and runtime-identity receipt with harmless Dev-only inputs. The operator performs one paste, one submit, waits, and exits; all preparation, discovery, capture, validation, and finalization are automated.

## Exact-prompt gate

The prepared UTF-8 `prompt.txt` bytes must equal the UTF-8 bytes reconstructed from the sole Kiro JSONL Prompt event. Exactly one linked user turn, the correct run-specific agent, a completed response, fresh-process termination evidence, and the exact runtime identity are additionally required. A mismatch is always invalid.

The known wrong session `35613a28-a498-4707-b72a-c58e67697a58` is preserved as `INVALID_OPERATOR_WRONG_PROMPT`, is excluded from the denominator, and did not submit a held-out prompt.

## Frozen invariants

- Model: `claude-sonnet-5`
- Prompt v2 SHA-256: `dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8`
- Tool count: 4
- Ceiling runtime identity SHA-256: `baa5078e30d31dcf681a141452fc7f6cc8a9b673c90413e26bcb355c6df9ab99`
- Task-runtime bindings SHA-256: `93755845b12c0552f6a256cb648b301342d307a4f4ee818d7e2299b476703abb`
- Defect injection spec SHA-256: `c4961d327dd70e2052ec3979d8dc70546e2ec134c389709c545ac9ded1c6568a`

The machine-verifiable receipt is `experiment/frozen/ax-exp-v3-manifest.json`. No held-out Agent task was executed while preparing or freezing v3.
