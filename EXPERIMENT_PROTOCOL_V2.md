# AX experiment v2 pre-registered protocol

Experiment version: `ax-exp-v2`

Status: pre-registered before any held-out Agent execution.

## Purpose

v2 completes the missing task/condition/runtime binding and the previously unspecified defect-injection operator. It does not tune prompts, retrieval, tools, scoring, benchmark questions, ground truth, or Ceiling evidence.

## Design

The run matrix is `16 held-out tasks × 2 condition labels × 2 repetitions = 64 runs`.

### Treated tasks

The 12 held-out tasks that have an entry in the frozen `task_to_defect_manifest.json` compare:

- `Before`: the task-relevant single accessibility-defect variant registered in `DEFECT_INJECTION_SPEC_V2.json`;
- `Ceiling`: the frozen `ceiling` runtime profile.

Tasks with the same frozen affected-source set share one runtime variant. This avoids task-specific corpus duplication.

### Control tasks

The four held-out control tasks remain controls:

- `K03_DELAY_COMPENSATION_THRESHOLD`
- `K06_FIRST_RESPONSE_TARGET`
- `O04_PRODUCT_MASTER_COUNT`
- `C03_TEA_STOCK`

Both condition labels resolve to the unchanged frozen `ceiling` runtime profile. Evidence bytes and runtime identity are therefore identical. These comparisons measure condition-label routing false effects and stochastic stability under evidence-equivalent conditions. No control defect is invented.

### Repetitions

The two repetitions measure runtime/model stochastic stability. They are repeated measurements under the same registered evidence, not independent dataset samples.

## v2 defect operator

The v1 label `source_readiness` identifies task-relevant sources but does not define a transformation. v2 operationalizes it as an Accessibility defect because the Scanner and Readiness Score define accessibility by successful parsing.

The deterministic operator preserves the source path, inventory membership, and modified timestamp, but replaces the selected file bytes with a path-keyed invalid payload that its declared-format parser rejects. It does not delete sources. Each generated variant must satisfy:

- only registered affected-source bytes change;
- every affected source remains inventoried and has `parse_status = ERROR`;
- Accessibility decreases;
- Completeness, Redundancy, Timeliness, and Safety remain unchanged;
- protected control sources remain byte-identical;
- runtime leakage violations remain zero;
- repeated generation is byte-identical.

Machine-readable parameters, source and generated hashes, provenance, scan reports, runtime identities, and diff receipts are registered in `DEFECT_INJECTION_SPEC_V2.json` and `experiment/v2/runtime/`.

## Blindness and frozen invariants

Runtime prompts continue to expose only `category` and `question`. Expected answers, primary blockers, required sources, tool plans, and defect ground truth are not runtime resources.

The following remain frozen from v1: prompt v2 bytes, `claude-sonnet-5`, the four-tool surface, retrieval implementation, Scanner implementation, benchmark, ground truth, failure taxonomy, Readiness Score implementation/specification, and Ceiling runtime identity.

No held-out task may be submitted while preparing or freezing v2.
