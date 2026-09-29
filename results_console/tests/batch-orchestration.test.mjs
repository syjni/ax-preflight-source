import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { BatchPanel } from '../src/components/BatchPanel.tsx';

const tasks = {
  dataset: 'mini',
  catalog_status: 'VERIFIED_TASKS_AVAILABLE',
  tasks: [
    {
      task_id: 'TASK_VERIFIED', category: '정책', question: '승인된 질문',
      description: '승인 업무', status: 'VERIFIED', approval: null,
    },
    {
      task_id: 'TASK_CANDIDATE', category: '운영', question: '후보 질문',
      description: '후보 업무', status: 'CANDIDATE', approval: null,
    },
  ],
};

function batch(state, retried = false) {
  const failed = state === 'COMPLETED_WITH_ERRORS';
  return {
    schema_version: 'ax-batch-status-v1', batch_id: 'batch-ui', dataset: 'mini',
    model: 'claude-sonnet-5', state, requested_control: 'RUN', repetitions: 1,
    max_attempts: 2, created_at: '2026-09-28T00:00:00Z',
    updated_at: '2026-09-28T00:00:01Z', total_items: 2, completed_items: 2,
    succeeded_items: failed ? 1 : 2, failed_items: failed ? 1 : 0,
    cancelled_items: 0, running_items: 0, queued_items: 0, progress_percent: 100,
    items: [
      {
        item_id: 't01-r01', task_id: 'TASK_VERIFIED', task_label: '승인된 질문',
        request_type: 'VERIFIED_BUSINESS_TASK', repetition: 1, attempt: 1,
        status: 'SUCCEEDED', run_id: 'batch-ui-t01-r01-a1', delivery_status: 'DELIVERED',
      },
      {
        item_id: 't02-r01', task_id: 'TASK_CANDIDATE', task_label: '후보 질문',
        request_type: 'TASK_CANDIDATE', repetition: 1, attempt: retried ? 2 : 1,
        status: failed ? 'FAILED' : 'SUCCEEDED',
        run_id: retried ? 'batch-ui-t02-r01-a2' : 'batch-ui-t02-r01-a1',
        delivery_status: failed ? 'REJECTED' : 'DELIVERED',
        error_code: failed ? 'RUNTIME_ERROR' : null,
      },
    ],
  };
}

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

test('batch panel sends approved identity, candidate question, and retries only through the batch endpoint', async () => {
  const requests = [];
  const opened = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const body = requests.length === 1
      ? batch('COMPLETED_WITH_ERRORS')
      : batch('COMPLETED', true);
    return new Response(JSON.stringify(body), {
      status: requests.length === 1 ? 202 : 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  await act(async () => root.render(React.createElement(BatchPanel, {
    dataset: 'mini', tasks, canRun: true, fixture: false,
    onOpenRun: (runId) => opened.push(runId),
  })));

  const checkboxes = [...container.querySelectorAll('input[type="checkbox"]')];
  assert.equal(checkboxes[0].checked, true, 'the verified task should be preferred');
  assert.equal(checkboxes[1].checked, false);
  await act(async () => checkboxes[1].click());

  const repetition = container.querySelectorAll('select')[0];
  await act(async () => {
    repetition.value = '1';
    repetition.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  });
  assert.match(container.textContent, /2 \/ 50/);

  await act(async () => {
    container.querySelector('form').dispatchEvent(
      new dom.window.Event('submit', { bubbles: true, cancelable: true }),
    );
  });

  assert.equal(requests[0].url, '/api/batches');
  const submitted = JSON.parse(requests[0].init.body);
  assert.deepEqual(submitted, {
    dataset: 'mini',
    tasks: [
      { task_id: 'TASK_VERIFIED', request_type: 'VERIFIED_BUSINESS_TASK' },
      { task_id: 'TASK_CANDIDATE', request_type: 'TASK_CANDIDATE', question: '후보 질문' },
    ],
    repetitions: 1,
    max_attempts: 2,
  });
  assert.match(container.textContent, /일부 실패/);
  assert.match(container.textContent, /RUNTIME_ERROR/);

  const runButton = [...container.querySelectorAll('.batch-item button')][0];
  await act(async () => runButton.click());
  assert.deepEqual(opened, ['batch-ui-t01-r01-a1']);

  const retry = [...container.querySelectorAll('.batch-actions button')]
    .find((button) => button.textContent === '실패만 재시도');
  assert.equal(retry.disabled, false);
  await act(async () => retry.click());
  assert.equal(requests[1].url, '/api/batches/batch-ui/retry');
  assert.match(container.textContent, /완료/);
  assert.match(container.textContent, /batch-ui-t02-r01-a2/);
  assert.equal(retry.disabled, true);
});

test('batch panel exposes the safe-point rule and disables mutation in fixture mode', async () => {
  await act(async () => root.render(React.createElement(BatchPanel, {
    dataset: 'mini', tasks, canRun: true, fixture: true,
    fixtureBatch: batch('COMPLETED_WITH_ERRORS'), onOpenRun: () => {},
  })));

  assert.match(container.textContent, /현재 실행을 안전하게 마친 뒤 적용/);
  assert.match(container.textContent, /읽기 전용/);
  assert.equal(container.querySelector('fieldset').disabled, true);
  assert.equal(container.querySelector('button.primary-action').disabled, true);
  const actions = [...container.querySelectorAll('.batch-actions button')];
  assert.equal(actions.length, 4);
  assert.ok(actions.every((button) => button.disabled));
});

test('batch panel previews project capacity and blocks an oversized estimated budget', async () => {
  const executionControl = {
    project_id: 'prj_1', dataset_profile: 'local-1', can_execute: true, blockers: [],
    connection: { runner_enabled: true, provider: 'KIRO_CLI', executable_status: 'AVAILABLE' },
    policy: {
      project_id: 'prj_1', model: 'claude-sonnet-5', daily_run_limit: 5,
      max_batch_runs: 2, max_concurrent_runs: 1, estimated_cost_per_run_cents: 25,
      daily_budget_cents: 100, updated_by: 'owner', updated_at: '2026-09-29T00:00:00Z',
    },
    usage: {
      window_started_at: '2026-09-28T00:00:00Z', reserved_runs: 3, running_runs: 0,
      estimated_spend_cents: 50, remaining_run_capacity: 2, remaining_budget_cents: 50,
    },
  };
  await act(async () => root.render(React.createElement(BatchPanel, {
    dataset: 'local-1', tasks, canRun: true, fixture: false,
    model: 'claude-sonnet-5', executionControl, onOpenRun: () => {},
  })));

  assert.match(container.textContent, /3 \/ 2/);
  assert.match(container.textContent, /\$0\.75 \/ \$0\.50/);
  const start = container.querySelector('button.primary-action');
  assert.equal(start.disabled, true);
  assert.match(start.textContent, /실행·비용 한도 조정 필요/);
});
