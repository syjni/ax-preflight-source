import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { ExecutionControlPanel } from '../src/components/ExecutionControlPanel.tsx';

const project = {
  project_id: 'prj_control', name: '고객지원 PoC', description: '', member_role: 'OWNER',
  member_count: 1, created_at: '2026-09-29T01:00:00Z',
};

const dataset = {
  profile: 'local-control', dataset_name: 'company-files', display_label: '회사 자료',
  origin: 'LOCAL', project_id: 'prj_control', source_root_name: 'company-files',
  scanned_at: '2026-09-29T01:10:00Z',
};

const control = {
  schema_version: 'ax-project-execution-control-v1', project_id: 'prj_control',
  dataset_profile: 'local-control', can_execute: true, blockers: [],
  connection: {
    schema_version: 'ax-model-connection-status-v1', runner_enabled: true,
    provider: 'KIRO_CLI', executable_status: 'AVAILABLE',
    credential_status: 'ENVIRONMENT_MANAGED_NOT_PROBED', timeout_seconds: 120,
    default_model: 'claude-sonnet-5',
  },
  policy: {
    schema_version: 'ax-project-execution-policy-v1', project_id: 'prj_control',
    provider: 'KIRO_CLI', model: 'claude-sonnet-5', daily_run_limit: 20,
    max_batch_runs: 10, max_concurrent_runs: 1, estimated_cost_per_run_cents: 10,
    daily_budget_cents: 200, updated_by: 'usr_owner', updated_at: '2026-09-29T01:15:00Z',
  },
  transfer_approval: {
    schema_version: 'ax-data-transfer-approval-v1', approval_id: 'data_1',
    project_id: 'prj_control', dataset_profile: 'local-control', provider: 'KIRO_CLI',
    model: 'claude-sonnet-5', data_classification: 'INTERNAL',
    boundary_revision: 'AX_DATA_BOUNDARY_V1', pii_affected_file_count: 1,
    tool_output_to_model_acknowledged: true, provider_policy_reviewed: true,
    sensitive_data_reviewed: true, approved_by: 'usr_owner',
    approved_at: '2026-09-29T01:15:00Z', expires_at: '2026-10-29T01:15:00Z',
  },
  usage: {
    schema_version: 'ax-project-execution-usage-v1', window: 'ROLLING_24_HOURS',
    window_started_at: '2026-09-28T01:15:00Z', reserved_runs: 3, running_runs: 0,
    estimated_spend_cents: 30, remaining_run_capacity: 17, remaining_budget_cents: 170,
  },
};

let dom;
let root;
let container;
let originalFetch;

beforeEach(() => {
  dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>');
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  originalFetch = globalThis.fetch;
  container = document.getElementById('root');
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  globalThis.fetch = originalFetch;
  dom.window.close();
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.IS_REACT_ACT_ENVIRONMENT;
});

test('execution control explains credentials, approved data boundary, and bounded usage', async () => {
  await act(async () => root.render(React.createElement(ExecutionControlPanel, {
    project, dataset, control, loading: false, loadError: '', onRefresh: async () => {},
  })));

  assert.match(container.textContent, /실행 가능/);
  assert.match(container.textContent, /자격 증명은 실행 환경에서만 관리/);
  assert.match(container.textContent, /원본 폴더 자체는 업로드하지 않습니다/);
  assert.match(container.textContent, /3 \/ 20/);
  assert.match(container.textContent, /\$0\.30 \/ \$2\.00/);
  assert.match(container.textContent, /PII 가능 파일 1개/);
});

test('OWNER policy form sends the selected model and limits as server-enforced values', async () => {
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    return new Response(JSON.stringify(control.policy), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  };
  let refreshed = 0;
  await act(async () => root.render(React.createElement(ExecutionControlPanel, {
    project, dataset, control, loading: false, loadError: '',
    onRefresh: async () => { refreshed += 1; },
  })));

  const form = container.querySelector('.execution-control__form');
  await act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));

  assert.equal(requests[0].url, '/api/projects/prj_control/execution-policy');
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    model: 'claude-sonnet-5', daily_run_limit: 20, max_batch_runs: 10,
    max_concurrent_runs: 1, estimated_cost_per_run_cents: 10, daily_budget_cents: 200,
  });
  assert.equal(refreshed, 1);
  assert.match(container.textContent, /모델을 바꾸면 자료 전달 승인을 다시 받아야 합니다/);
});
