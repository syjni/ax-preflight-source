# ax-exp-v2 interactive execution protocol

The official backend remains `INTERACTIVE_FRESH_PROCESS`. This protocol records a reproducible human-driven run; it never automates model interaction. Preparation resolves `task_id + condition` through `task_runtime_bindings.json` and creates a deterministic run-specific Kiro agent configuration. The operator must not edit dataset JSON or agent JSON between preparation and finalization.

One run is exactly:

```text
prepare task/condition/repetition/prompt
→ resolve pre-registered runtime profile
→ generate run-specific ax-evaluation agent config
→ fresh Kiro interactive process
→ paste the exact prompt once
→ process exit
→ capture-session
→ finalize
→ inspect validity_status
```

## Registered condition semantics

- Treated tasks (12): `Before` resolves to the task-relevant single-defect profile and `Ceiling` resolves to frozen `ceiling`.
- Control tasks (4): both `Before` and `Ceiling` resolve to frozen `ceiling`. Their byte- and identity-equivalent evidence is an intentional negative control for condition-label routing and stochastic stability, not a defect.
- Two repetitions measure stochastic stability. They are not represented as independent dataset samples.

The complete pre-registration is in `EXPERIMENT_PROTOCOL_V2.md`, `DEFECT_INJECTION_SPEC_V2.json`, and `task_runtime_bindings.json`. The run design remains `16 × 2 × 2 = 64`.

## One run

1. Create an exact blind prompt file using the existing two-field runtime projection.
2. Prepare an empty run directory:

   ```powershell
   python -m scripts.interactive_run prepare --run-dir <directory> --task-id <id> --condition <Before|Ceiling> --repetition <1|2> --prompt-file <file>
   ```

3. Execute only the exact command saved in `command.txt`. It names the generated run-specific agent and never includes a resume option.
4. Paste `prompt.txt` exactly once. Do not submit another task.
5. Exit immediately after the response.
6. Capture the explicit one-turn session:

   ```powershell
   python -m scripts.interactive_run capture-session --run-dir <directory> --session-id <id>
   ```

7. Finalize:

   ```powershell
   python -m scripts.interactive_run finalize --run-dir <directory>
   ```

8. Accept the run only when `validity_status` is `VALID` and `validation_errors` is empty.

Preparation fails before `PREPARED` for an unknown task, unknown condition, binding/profile mismatch, changed model, changed prompt, or changed tool surface. Finalization independently resolves the binding again, re-hashes the run-specific config, recomputes runtime identity, and compares the MCP startup identity receipt. Any mismatch produces `validity_status = INVALID`; evidence is retained.

The model remains `claude-sonnet-5`. The prompt remains frozen v2. The only model-callable tools remain `search_documents`, `read_document`, `lookup_value`, and `query_table`. Resume, cross-task context, manual answer correction, model fallback, and tool expansion are forbidden.

`capture-session` proves that exactly one user turn used the prepared run-specific agent. A manually supplied response is retained but can only become `REQUIRES_MANUAL_PROTOCOL_REVIEW`, never `VALID`.
