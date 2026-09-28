# AX Experiment v2 Freeze Result

Experiment: `ax-exp-v2`

Status: **FROZEN**

Official backend: `INTERACTIVE_FRESH_PROCESS`

Run design: `16 tasks × 2 conditions × 2 repetitions = 64 runs`

Held-out executed: `0`

Regression tests: `100/100 PASS`

Static routes: `32/32 PASS`

Runtime identity mismatches: `0`

Runtime leakage violations: `0`

## Registered design

- Treated tasks: 12
- Control tasks: 4
- Unique treated Before variants: 8
- Treated `Before`: task-relevant deterministic accessibility-defect profile
- Treated `Ceiling`: frozen `ceiling` profile
- Control `Before` and `Ceiling`: the same frozen `ceiling` profile and runtime identity
- Repetitions: stochastic-stability measurements, not independent dataset samples

The v2 defect operator preserves each affected path in the file inventory and preserves its deterministic modified timestamp, while replacing its bytes with a path-keyed payload rejected by the declared-format parser. Every variant receipt verifies that Accessibility decreases while Completeness, Redundancy, Timeliness, and Safety remain unchanged.

## Frozen invariants

- Model: `claude-sonnet-5`
- Prompt v2 SHA-256: `dc783a41a5b06eb871ada33be7dd21aec2e4106757a40921ddf59fcf81176fc8`
- Tool count: 4
- Ceiling runtime identity SHA-256: `baa5078e30d31dcf681a141452fc7f6cc8a9b673c90413e26bcb355c6df9ab99`
- Ceiling dataset manifest SHA-256: `bcf60e523ee55951b8bb58fdc9049c667c8902154baab02d745ea7262a44a804`
- Ceiling Readiness: `100.0`
- v1 manifest SHA-256: `8077fb08f829133443fd496b1e0cebd760a048e45c7f64bba32222c7959841e3`

The v1 manifest remains byte-identical to the external frozen snapshot. Retrieval, Scanner, benchmark, ground truth, failure taxonomy, deterministic scorer, output contract, runtime prompt constructor, and Readiness implementation/specification match their v1 frozen component hashes.

## v2 hashes

- Runtime dataset config: `9b231de90f0429a7eda2cec7d80030f25654dd2934d554be79c68d2aaea35a76`
- Task runtime bindings: `93755845b12c0552f6a256cb648b301342d307a4f4ee818d7e2299b476703abb`
- Defect injection spec: `c4961d327dd70e2052ec3979d8dc70546e2ec134c389709c545ac9ded1c6568a`
- Interactive recorder: `32632d12aecd7b3e4fd329403ad835a2f86d2f799e45f3072611d6c180b3fd3d`

The machine-verifiable manifest is `experiment/frozen/ax-exp-v2-manifest.json`. No held-out Agent task was executed while preparing or freezing v2.
