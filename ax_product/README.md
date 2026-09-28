# AX Preflight product delivery contract (Phase 1)

처음 실행하거나 제출용 개요가 필요하면 [저장소 대표 README](../README.md)를 먼저 보고,
[시스템 구조](../docs/ARCHITECTURE.md), [데이터와 개인정보](../docs/DATA_AND_PRIVACY.md),
[3분 시연 절차](../docs/DEMO_SCRIPT.md)를 참고하십시오.

`SubmitAnswerInput` is the only authoritative product answer. Raw assistant prose is
outside this contract. Create one `SubmitAnswerSession` per run. Invalid payloads
return `VALIDATION_ERROR` and leave the state `UNSUBMITTED`; the first valid payload
changes it to `ACCEPTED`. Every later call returns `ALREADY_SUBMITTED`, including
malformed calls. The session keeps its own copy of the accepted payload.

## Source policy

- `ANSWERED`: at least one distinct, nonblank `source_id`.
- `ABSTAINED / NOT_FOUND`: zero or more source IDs.
- `ABSTAINED / INSUFFICIENT_EVIDENCE`: at least one source ID.
- `ABSTAINED / CONFLICTING_EVIDENCE`: at least one source ID. Two are useful when
  the conflict spans two sources, but one source can contain conflicting evidence.

These rules check ID count and syntax only. They do not prove that an ID appeared
in a tool response or supports the answer. A delivered session envelope therefore
sets `source_link_status=NOT_CHECKED`. Linkage assessment belongs to a later
product stage. `UnscoredObservation` has no score field and does not alter the
frozen readiness score.

Generate the three JSON Schemas with:

```text
python -m ax_product.schema_export ax_product/schemas
```

Pydantic remains the validation authority: the exported JSON Schemas describe
field shapes, while the Python model validators enforce cross-field relationships.
## Phase 2 MCP integration

`.kiro/agents/ax-product.json` uses `python -m ax_product.server`. This separate
server exposes the four existing evidence tools and `submit_answer`; the research
server and `ax-evaluation` remain separate. The bundled configuration points to
the `mini` sample dataset. Select a customer runtime profile for a real product
run.

One product MCP process represents one run. Its adapter retains one
`SubmitAnswerSession` and one CROSS_FILE `ToolSession` across tool calls. The four
data tools share the existing 12-call CROSS_FILE budget for the entire process;
successful and tool-level failed data calls consume that budget, while
`submit_answer` does not. The server generates a unique run ID at startup unless
the caller supplies `--run-id`; a task orchestrator should launch a fresh process
for every run and may pass `--task-id`. Restarting the process starts new
submission and data-tool sessions, even if an old run ID is reused, so the batch
orchestrator assigns a new run ID to every item attempt and manages process lifetime.

The successful local MCP `submit_answer` response contains a `DeliveryEnvelope` as
`structuredContent`. Kiro `stream-json` has also been observed wrapping it as JSON
text at `rawOutput.items[0].Json.content[0].text`, without `structuredContent`.
Invalid submissions return `VALIDATION_ERROR` with field
messages so the agent can retry. Later submissions return `ALREADY_SUBMITTED`.
An in-process consumer can also call `ProductMcpAdapter.delivery_envelope()`.
Product consumers must read the accepted envelope from the tool response or this
accessor, never the assistant's final prose or transcript. Neither path performs
evidence-link checking: accepted results report `source_link_status=NOT_CHECKED`.

## Phase 3 API and result storage

Install `requirements.txt` and serve `ax_product.api:app` with an ASGI server such
as Uvicorn. The endpoints are `GET /api/findings/{dataset}`,
`GET /api/readiness/{dataset}`, `GET /api/tasks/{dataset}`,
`GET /api/runs/{run_id}`, `POST /api/run`, `POST /api/batches`,
`GET /api/batches/{batch_id}`, and the batch pause, resume, cancel, retry actions. `dataset` is a profile in
`runtime_datasets.json`. The product-owned catalog returns ten generic
`TASK_CANDIDATE` questions and never reads the research benchmark catalog.
These candidates are not customer-verified business tasks. Readiness uses the
existing, unchanged score function and returns `unscored_observations`
separately for probable version groups.

`POST /api/run` requires `request_type`. An `AD_HOC_QUESTION` requires a
`question` and forbids `task_id`; it receives no automatic answer score. A
`TASK_CANDIDATE` requires the exact catalog `task_id` and `question`; a mismatch
returns HTTP 409. A `VERIFIED_BUSINESS_TASK` requires `task_id` and forbids
`question`; the API resolves the exact catalog question only when a separate
approval record matches the dataset, task ID, question hash, owner, and success
criteria. Unapproved verified requests return HTTP 409. All forms accept
`dataset`, optional `run_id`, and optional `model`. The default app has no
model runner configured and returns HTTP 503 `RUNNER_UNAVAILABLE` without
creating a run. Supply a `Runner` to `create_app` to
execute a run. The runner must wait for its MCP process to exit. Pass the reserved
`run_id`, `model`, optional `task_id`, and `--results-root` to
`python -m ax_product.server`. The MCP server writes its final
`DeliveryEnvelope` when stdin closes. The API reads that envelope by `run_id`;
it never interprets assistant prose or Kiro `finalText`. The current opt-in Kiro
runner passes the dataset profile as routing metadata and uses the actual task
question as the prompt; see [Phase 6A](#phase-6a-opt-in-kiro-runner). Do not phrase
`mini` or another profile label as if it were a company name in the question.

Results live at `artifacts/product_runs/<run_id>/delivery.json` by default.
Reservation atomically publishes `state.json` with `run_status: RUNNING` and the
requested dataset profile, and separately persists `run-context.json` with the
selected task identity and label, without
a final envelope. `GET /api/runs/{run_id}` returns this running state until the
MCP process exits or runner failure is confirmed. It then returns the final
`DeliveryEnvelope`: `DELIVERED`, `REJECTED / NO_SUBMISSION`,
`REJECTED / INVALID_SUBMISSION`, or `REJECTED / RUNTIME_ERROR`. Final writes use
a temporary file and atomic write-once publication. A later runner cleanup
exception cannot replace a final envelope. A missing final result after runner
failure becomes `RUNTIME_ERROR`; `INVALID_RUN` requires an explicit `RunGate`
verdict supplied to `create_app`. A duplicate `run_id` returns HTTP 409,
including while the first run is in progress. The server must use the directory
reserved by the API; it does not allocate its own run directory.

The reservation's dataset profile is copied into the final stored envelope,
including rejected results. The API returns `dataset: UNKNOWN` for older final
results or running states that have no dataset field; it does not infer a profile
from the current console selection or research records.

Phase 3 당시에는 Kiro 또는 Claude runner 구현이 없었습니다. 현재는
[Phase 6A](#phase-6a-opt-in-kiro-runner)의 명시적 opt-in factory가 실제 Kiro
runner를 제공하며, 기본 `ax_product.api:app`은 계속 runner 없이
`POST /api/run`에 HTTP 503 `RUNNER_UNAVAILABLE`을 반환합니다. 프로덕션
배포에는 인증, customer-verified task catalog, retention 정책과 운영 통제가 여전히
필요합니다.

## Failure→Finding aggregation

`GET /api/findings/{dataset}` derives task-level diagnostics from stored
`DeliveryEnvelope` records, persisted run context, and same-run structured tool
responses only. It performs no additional model reasoning and never reads raw
assistant prose. Abstentions become `CONFLICTING_SOURCES`,
`INSUFFICIENT_EVIDENCE`, or task-level `MISSING_INFORMATION` findings. Repeated
conflicts and insufficient-evidence failures are grouped only when both finding
type and sorted source-ID set match. Affected task count and observed run count
remain separate.

Evidence excerpts must come from recorded tool output. A configured comparison
may mark a prior finding `NOT_REPRODUCED_AFTER` only when every observed After
run for the task answered and the same finding type is absent; otherwise the
comparison is `UNKNOWN`. The aggregator does not change `delivery.json`, the
Evidence Checker verdict, or Readiness.

## Phase 5 Evidence Checker v1

The product MCP server records each successful structured data-tool response as a
write-once file under
`artifacts/product_runs/<run_id>/tool-responses/`. It never records or consumes
assistant prose for evidence checking. After `delivery.json` is published, the
checker reads only that approved envelope and records bearing the same `run_id`.
It filters those records again to the `payload.source_ids` cited by the delivery.

The separate, write-once `evidence-check.json` uses four conservative verdicts:

- `DIRECT_MATCH`: the delivered value occurs in an explicitly allowed data field
  of a cited response. Allowed fields are `search_documents` snippets,
  `read_document` content, `lookup_value.value`, and `query_table` row cells.
  Citation IDs and response metadata are never answer content. Numeric answers
  with units require the value and a compatible unit in the same row, field, or
  text segment. If `unit` is set for a list, boolean, or other non-quantity answer
  shape, v1 does not promote it to a direct match. An abstention requires the same
  negative sentence or quoted negative passage in the cited response.
- `DERIVABLE`: an exact numeric answer is reproducible by only a same-field sum,
  same-field difference, or returned-row count. Row-count derivation requires an
  untruncated response whose reported and actual row counts agree. If multiple
  fields or operations produce the same answer, v1 does not select one.
- `PARTIAL_SUPPORT`: a cited response matches only part of a list, contains the
  answer's exact numeric value without a verifiable compatible unit, or has
  multiple allowed derivations that reproduce the answer. Merely containing
  different numeric values is not partial support.
- `UNCONFIRMED`: the response record or citation is missing, or the claim is
  outside v1's deterministic scope. This means *not verified*, not *incorrect*.

Division, rate computation, unit conversion, semantic inference, source-file
inspection, research ground truth, and raw assistant output are deliberately out
of scope. Identifiers, scores, matched/returned counts, section numbers, and
truncation flags are used only for citation linkage or completeness checks and
cannot create direct or partial content support. `delivery.json` remains unchanged with
`source_link_status=NOT_CHECKED`; checker results are available separately at
`GET /api/runs/<run_id>/evidence-check`. The existing `ax-evaluation` agent and
Readiness Score v1 are not inputs to or modified by this stage.

Current writable product runs use additive Evidence Checker v3. It applies the
frozen v2 deterministic rules first, then downgrades a quantity that appears in
cited narrative text only as an explicitly retired value. For example, `14일`
is not presented as current direct support when the cited sentence says that
the 14-day rule was retired and the current rule is 30 days. Frozen v1/v2
implementations and Phase 6 evidence artifacts remain byte-stable.

## Phase 6A opt-in Kiro runner

The exported `ax_product.api:app` remains runner-free and returns HTTP 503
`RUNNER_UNAVAILABLE`. To start the separate, explicitly enabled Kiro-backed app
from the repository root in PowerShell:

```powershell
$env:AX_PRODUCT_RUNNER = "kiro"
$env:AX_PRODUCT_RUN_TIMEOUT_SECONDS = "300"
python -m uvicorn --factory ax_product.api:create_app_from_env --host 127.0.0.1 --port 8000
```

`AX_KIRO_CLI` is optional when `kiro-cli` is on `PATH`; the runner resolves it
with `shutil.which`. `AX_RUNTIME_DATASET_CONFIG` may optionally select another
runtime dataset registry. The factory uses the same registry for API validation
and MCP routing.

Each accepted ad-hoc or catalog-matched candidate request creates a unique
temporary agent file based on `.kiro/agents/ax-product.json`. The generated agent
keeps that template's prompt and exactly the four data tools plus
`submit_answer`, while setting both the Kiro model and product MCP `--model` to
the requested model. It passes the reserved run ID, selected dataset profile,
runtime dataset registry, results root, and any candidate `task_id` to the MCP
process. For both request types, the actual request question is the final literal
Kiro argv element; the process is launched with `shell=False` and closed stdin.
Kiro CLI 2.23 also requires `--agent-engine v2` for `--output-format
stream-json`, so the runner passes that compatibility flag explicitly.

The HTTP request remains synchronous. While it is executing, a concurrent
`GET /api/runs/<run_id>` returns `RUNNING`. Kiro stdout and `finalText` are never
used as a product answer. After Kiro and its MCP child exit, the API reads only
the MCP-written `delivery.json` and same-run structured tool-response records.
On timeout, the runner terminates the complete Windows process tree with
`taskkill /T /F` (or the process group on POSIX), then removes the temporary
agent file. Missing final output is published through the existing
`RUNTIME_ERROR` path.

## Bounded batch orchestration

`POST /api/batches` accepts one to ten distinct approved or candidate tasks, one
to five repetitions per task, and one to three maximum attempts. The expanded
batch is capped at 50 items. Every task is validated against the same onboarding
and task-identity gates as `POST /api/run` before the batch record is created.

`BatchManager` runs the items sequentially in a background thread and persists
`ax-batch-status-v1` at `artifacts/product_batches/<batch_id>/batch.json` through
atomic file replacement. Each attempt delegates to the normal run executor, so
reservation, `DeliveryEnvelope`, evidence-checking, and Finding inputs keep one
implementation. Item run IDs include batch, item, and attempt identity. Retrying
a failed item creates a new run and never overwrites an earlier result.

Pause and cancel are safe-point controls: an already-running model process is
allowed to publish its final result, after which the worker pauses or marks only
queued items cancelled. On API process restart, a previously running item is not
assumed successful; it becomes `FAILED / INTERRUPTED_BY_RESTART` and the batch is
restored as `PAUSED`. The operator can inspect it, retry failed items, or resume
remaining queued work.

This scheduler is deliberately single-process. It does not provide distributed
worker leases, automatic retry backoff, concurrency or cost quotas, schedules,
webhooks, or tenant-isolated queues. Those controls are required before scaling
the API horizontally or using the batch endpoint for customer production data.

## Phase 6B frozen read-only demo

From the repository root in PowerShell, serve only the verified Phase 6 snapshot:

```powershell
$env:AX_PRODUCT_FROZEN_RESULTS_ROOT = "artifacts/phase6_product_demo/runs"
python -m uvicorn ax_product.api:create_read_only_app_from_env --factory --host 127.0.0.1 --port 8000
```

The factory verifies the frozen manifest at startup. It has no runner, returns
HTTP 503 for `POST /api/run`, and does not modify official results. Use the exact
dataset and run-ID pairs in the [representative README](../README.md).
