# AX Experiment v3 Protocol

Experiment ID: `ax-exp-v3`

Status: frozen execution design; held-out executions have not started.

## Scope of the v3 change

v3 closes one outcome-affecting execution-validation gap in v2: v2 verified the prepared run-specific agent, one user turn, and successful turn completion, but did not compare the actual Kiro user-turn text with the prepared `prompt.txt`. v3 also defines the official operator wrapper used to launch and close each fresh Kiro process.

No evidence, task, model, prompt, retrieval, Scanner, scoring, or condition-binding semantics change from v2. In particular, the frozen v2 Agent prompt bytes and SHA-256 remain unchanged.

## Registered design

- 16 held-out tasks × 2 conditions × 2 repetitions = 64 runs.
- The task order is the order in `task_runtime_bindings.json`.
- For repetition 1, each task runs `Before` and then `Ceiling`; repetition 2 follows only after all repetition-1 pairs.
- The 12 treated tasks retain their v2 single-defect Before profiles.
- The 4 control tasks retain byte-identical/equivalent `ceiling` profiles for Before and Ceiling.
- Repetitions measure stochastic stability and are not independent evidence samples.
- A Kiro process or session may not be reused across runs.

## Official backend

The official backend is `SEMI_AUTOMATED_FRESH_PROCESS`.

Kiro CLI 2.22.1 was tested with harmless Dev-only prompts. The default v1 engine rejected `stream-json`; the v2 engine non-interactive paths ended in internal errors without a complete persistent session/runtime receipt; and the remaining sandboxed path did not produce reliable execution evidence. A network-enabled retry was not run because external-runtime data-egress authorization was unavailable. Therefore automated prompt submission is not pre-registered as reliable.

The wrapper automates preparation, exact clipboard population, command construction, fresh-process launch, pre/post session discovery, capture, prompt validation, runtime validation, finalization, and advancement. The only human actions are: paste once, submit once, wait for the response, and exit that Kiro process.

## Exact submitted-prompt validity rule

The authoritative submitted text is reconstructed from the single `Prompt` event in the Kiro session JSONL and encoded as UTF-8. Its bytes must equal `prompt.txt` exactly. The linked session JSON must contain exactly one user-turn metadata record and it must link to that Prompt event.

A run can be `VALID` only when all of the following hold:

1. `prepared_prompt_sha256 == submitted_prompt_sha256` and the byte comparison passes.
2. Exactly one user turn and exactly one Prompt event exist.
3. The prompt is non-empty and contains only text content.
4. There is no prefix, suffix, command text, alternate task prompt, or extra turn.
5. The session agent is the prepared run-specific agent and the turn completed successfully.
6. Exactly one new matching session is discovered after the fresh process exits.
7. Process ID, exit code, termination, `fresh_process=true`, and `resume_used=false` are recorded. A nonzero code caused only by the operator's post-response console exit is retained as evidence; response completion and session validation remain mandatory.
8. The MCP runtime identity receipt matches the pre-registered task/condition binding.
9. All frozen v2 model, prompt, tool-surface, dataset, and routing consistency checks pass.

Any mismatch is invalid and cannot be promoted by a valid response or runtime receipt. Prompt-related metadata includes `prepared_prompt_sha256`, `submitted_prompt_sha256`, `submitted_prompt_matches_prepared`, `user_turn_count`, `prompt_event_count`, and `prompt_validation_errors`.

## Known pre-v3 operator error

Session `35613a28-a498-4707-b72a-c58e67697a58` submitted a PowerShell clipboard command instead of the prepared K01 prompt. It is classified `INVALID_OPERATOR_WRONG_PROMPT`, excluded from the official denominator, and does not count as a held-out task execution because the held-out prompt was never submitted. The original v2 prepared artifact and Kiro session are not modified; byte-preserved copies and hashes are stored under `experiment/v3/operator-errors/`.

## Stop conditions

The wrapper stops immediately on invalid session discovery, prompt mismatch, wrong agent, incomplete turn, process failure, runtime mismatch, or any frozen-invariant failure. It does not prepare the next run after an invalid result.
