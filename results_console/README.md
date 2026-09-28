# AX Preflight · Results Console (Phase 5 UI)

Start with the [repository README](../README.md). See also the
[architecture](../docs/ARCHITECTURE.md), [data and privacy boundaries](../docs/DATA_AND_PRIVACY.md),
and [three-minute demo script](../docs/DEMO_SCRIPT.md).

React, Vite, and TypeScript UI for the existing FastAPI product contract. It
reads `GET /api/findings/{dataset}`, `GET /api/readiness/{dataset}`, `GET /api/onboarding/{dataset}`, `GET /api/tasks/{dataset}`,
`GET /api/runs/{run_id}`, and the final-run-only
`GET /api/runs/{run_id}/evidence-check`, and `GET /api/batches/{batch_id}`. Ad hoc test requests use `POST /api/run`; bounded repeated runs use `POST /api/batches` and the pause, resume, cancel, and retry actions. The UI uses
only the accepted delivery envelope and never reads assistant final prose or
research benchmark answers.

## Run

From the repository root, install Python dependencies with `pip install -r
requirements.txt`, then start the API:

```powershell
python -m uvicorn ax_product.api:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd results_console
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/`. Vite proxies `/api` to port 8000. For another
API origin set `VITE_API_BASE_URL` before starting Vite; a cross-origin API also
needs an appropriate CORS policy. Enter a dataset profile
from `runtime_datasets.json`; `mini` is the initial profile.

Before enabling a run, the console shows the onboarding preflight returned by
`GET /api/onboarding/{dataset}`. It checks source/scan integrity, parse coverage,
retrieval surface, and runtime-resource leakage. `WARN` items remain reviewable;
`BLOCK` items disable execution and the API returns `ONBOARDING_BLOCKED` before
reserving a run or invoking a runner.

The default API has no model runner. An ad hoc or selected candidate request
reports HTTP 503 `RUNNER_UNAVAILABLE` and creates no run. The catalog contains
ten product-owned `TASK_CANDIDATE` questions; an item becomes `VERIFIED` only when a separate dataset-scoped approval record matches its exact question hash. The checked-in approval is a controlled demo, not customer approval, and there is no research benchmark task fallback. Once a runner
is connected, use the run ID lookup to display `RUNNING`, `DELIVERED`, or
`REJECTED` from the API. A delivered answer's source IDs are shown with its
`source_link_status`; `NOT_CHECKED` explicitly means linkage and support were
not verified. The run detail displays its persisted dataset profile. When it
differs from the selected readiness profile, or an older run has `UNKNOWN`
provenance, a warning appears above readiness and beside the run detail. This
applies to the submit response, Run ID lookup, and RUNNING polling path.

The **08 / 반복 실행** panel selects up to ten approved or candidate tasks and requests one to five repetitions each, capped at 50 runs. It polls durable progress, distinguishes success, failure, running, queued, and cancelled items, and links each item back to its run. Pause and cancel take effect after the active run reaches a safe final result; failed items can be retried with a new run ID up to the configured attempt limit. Static and development-fixture modes disable every batch mutation.

### Public read-only static demo

The competition deployment uses the same verified v4 responses in a static
snapshot, so the public site does not need a Python server and cannot create or
modify runs. Regenerate and verify the checked-in snapshot from the repository
root, then build the static site:

```powershell
python -m scripts.export_static_demo
python -m pytest -q tests/test_static_demo_export.py
cd results_console
npm run build:static
```

Serve `dist/` with any static host. `.env.static` selects the Before portfolio
as the first console dataset, uses relative asset paths, and exposes a verified
Before/After representative case whose buttons open the frozen run and evidence
without requiring a run ID. The evidence section also shows a run-bound trace
of stored search candidates, failed attempts, opened sources, and final citation
linkage without copying raw source content, query text, or filter values.
`POST`-style execution requests still return
`RUNNER_UNAVAILABLE` in the browser and the recovery UI directs reviewers to
the verified flow. The exporter fails if the featured run,
dataset, 0/3→3/3 comparison, or `DIRECT_MATCH` evidence drifts. The GitHub Pages
workflow in `.github/workflows/deploy-pages.yml` runs this build from `main`.

### Local reviewer mode

On Windows, `start-local.cmd` at the repository root installs dependencies and
starts both processes. The console then accepts an absolute folder path and
shows that folder's readiness and file-level action list alongside the bundled
verified example. Source files are read in place and are never copied or
modified.

The default panel also accepts browser file selection, folder selection, and
drag-and-drop. Those bytes go only to the local `/api/local-datasets/upload`
endpoint and are kept in a managed local copy until the reviewer removes the
record. The result shows PDF table counts, OCR state, processed pages, and OCR
confidence when available. The path tab remains available for an in-place scan.

For the smallest reviewer setup, `start-docker.cmd` at the repository root
builds and opens a single <http://127.0.0.1:8000/> app with Korean/English OCR
included.

To start the same mode manually, run this command from the repository root:

```powershell
$env:AX_PRODUCT_FROZEN_RESULTS_ROOT = "artifacts/phase6_product_demo_v4/runs"
python -m uvicorn ax_product.api:create_local_review_app_from_env --factory --host 127.0.0.1 --port 8000
```

Then start this console in another terminal with `npm ci` and
`npm run dev -- --port 5173`. The API verifies and reads official snapshot runs
and permits local static scans; AI task and batch mutations remain unavailable.

## Generate types

The Python exporter writes the Pydantic JSON Schemas into `schemas/`, including
`FeaturedCasesResponse`, `FindingsResponse`, and
the separate Phase 5 `EvidenceCheckResult` returned by
`GET /api/runs/{run_id}/evidence-check`.
`BatchCreateRequest` and `BatchStatus` describe the bounded orchestration contract.
`RunRequest` and `RunningRun` come from `ax_product.api`; delivery models come
from `ax_product.models`; the evidence-check response comes from
`ax_product.evidence`; readiness and task response models live in
`ax_product.console_contracts` and are attached to the FastAPI endpoints.

```powershell
python -m ax_product.console_schema_export results_console/schemas
cd results_console
npm run generate:types
npm run build
```

The generated TypeScript file is `src/generated/api.ts`. Cross-field Pydantic
validators remain the server's validation authority; JSON Schema and generated
TypeScript describe response shapes.

## UI verification

Development builds offer `?fixture=running`, `?fixture=answered`,
`?fixture=abstained`, `?fixture=rejected`, `?fixture=mismatch`, and
`?fixture=legacy`. `?fixture=benchmark` is the only mode that reveals the
controlled experiment tab. These are synthetic API response
fixtures for screen verification only. A conspicuous fixture banner and detail
badge identify them; fixture mode disables API submission and lookup. This
switch is absent from production builds. The fixtures live in
`src/mock/report.ts` and are reached only by a DEV-guarded dynamic import; the
production build is checked for fixture-only sentinel text.

The report is task-centric: AI 업무 진단 and data findings appear first, followed
by static Readiness, task candidates, Evidence Checker, and controls. Finding
cards keep affected-task counts separate from repeated-run counts and reveal
only source titles and excerpts preserved from same-run tool output.

The report layout keeps a 280px sidebar on desktop and centers the report at a
maximum width of 1180px. At 1024px and below the sidebar moves above the report.
Readiness rows reveal only the counts and flags supplied by the API. Since the
current readiness contract does not connect observations to a scored dimension
or expose per-dimension file lists, the UI says so rather than inferring either.

Evidence Checker verdicts are displayed separately from
`DeliveryEnvelope.source_link_status`. A 404 is shown as “근거 검사 결과 없음”
and does not alter run success. `UNCONFIRMED` is accompanied by the contract's
`unconfirmed_is_not_incorrect` meaning, and derivation, source-ID sets, and
limitations are shown when supplied.

An explicitly opt-in real Kiro runner is available through
`create_app_from_env`; the default `ax_product.api:app` and the read-only factory
remain runner-free and return HTTP 503 for `POST /api/run`. Production deployment
still needs a customer-verified task catalog, authentication, retention and
operational controls, and broader semantic validation beyond Evidence Checker v1
before it can make verified evidence claims.
