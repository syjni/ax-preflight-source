import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { PocEvaluationPanel } from '../src/components/PocEvaluationPanel.tsx';

const project = {
  project_id: 'prj_eval', name: '반품 PoC', description: '', member_role: 'OWNER',
  member_count: 1, created_at: '2026-09-29T01:00:00Z',
};

const dataset = {
  profile: 'local-eval', dataset_name: 'return-files', display_label: '반품팀 자료',
  origin: 'LOCAL', project_id: 'prj_eval', source_root_name: 'return-files',
  scanned_at: '2026-09-29T01:10:00Z',
};

const report = {
  schema_version: 'ax-poc-evaluation-v1', project_id: 'prj_eval', project_name: '반품 PoC',
  dataset_profile: 'local-eval', dataset_name: '반품팀 자료',
  generated_at: '2026-09-29T02:00:00Z', assessment_fingerprint: 'a'.repeat(64),
  recommendation: 'GO', decision_current: false, decision_expired: false,
  criteria_version: 'AX_POC_GATES_V2', diagnostics_version: 'v2',
  scope_note: '현재 저장된 관측 결과를 요약하며 인증이나 정답률을 대신하지 않습니다.',
  metrics: {
    readiness_score: 92, onboarding_status: 'READY', registered_tasks: 3,
    approved_tasks: 3, observed_runs: 9, answered_runs: 8, abstained_runs: 1,
    rejected_runs: 0, direct_evidence_runs: 8, stable_tasks: 3, open_findings: 0,
    direct_evidence_ratio: 0.8889, repeated_tasks: 3,
  },
  run_population: {
    total_final_runs: 12, included_runs: 9, included_answered_runs: 8,
    included_abstained_runs: 1, excluded_rejected_runs: 1,
    excluded_runtime_failure_runs: 1, excluded_non_verified_request_runs: 1,
    excluded_unapproved_task_runs: 0, excluded_missing_context_runs: 0,
  },
  task_samples: [
    { task_id: 'task-a', task_label: '반품 기간', included_runs: 3, minimum_runs: 3, sample_complete: true },
    { task_id: 'task-b', task_label: '반품 예외', included_runs: 3, minimum_runs: 3, sample_complete: true },
    { task_id: 'task-c', task_label: '반품 책임자', included_runs: 3, minimum_runs: 3, sample_complete: true },
  ],
  gates: [
    { code: 'DATA_READINESS', label: '정적 데이터 준비도', status: 'PASS', detail: '관측 점수 92/100' },
    { code: 'DIRECT_EVIDENCE', label: '직접 근거 연결', status: 'PASS', detail: 'DIRECT_MATCH 8/9회', decision_relevant: true, numerator: 8, denominator: 9, excluded: 3, minimum_sample: 3, minimum_ratio: 0.8 },
    { code: 'EXECUTION_CAPACITY', label: '현재 실행 용량', status: 'WARN', detail: '현재 신규 실행 차단', decision_relevant: false },
  ],
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

async function renderPanel() {
  await act(async () => {
    root.render(React.createElement(PocEvaluationPanel, { project, dataset, revision: '1' }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test('PoC dashboard combines readiness, approved scope, observed runs, evidence, and gates', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify(report), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
  await renderPanel();

  assert.match(container.textContent, /GO · 승인 가능/);
  assert.match(container.textContent, /데이터 준비도92/);
  assert.match(container.textContent, /승인 업무3\/ 3/);
  assert.match(container.textContent, /직접 근거8DIRECT_MATCH/);
  assert.match(container.textContent, /포함 9회/);
  assert.match(container.textContent, /제외 3회/);
  assert.match(container.textContent, /분자 8 \/ 분모 9/);
  assert.match(container.textContent, /판단 비반영 운영 상태/);
  assert.match(container.textContent, /AX_POC_GATES_V2/);
  assert.match(container.textContent, /승인 게이트/);
  assert.match(container.textContent, /현재 저장된 관측 결과/);
});

test('OWNER decision records explicit scope and risk acknowledgements', async () => {
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    const response = init.method === 'PUT'
      ? { ...report, decision_current: true, decision: {
          schema_version: 'ax-poc-decision-v1', decision_id: 'poc_1',
          project_id: 'prj_eval', dataset_profile: 'local-eval', decision: 'APPROVED',
          note: '현재 범위에서 운영 승인을 진행합니다.', assessment_fingerprint: 'a'.repeat(64),
          decided_by: 'usr_owner', decided_at: '2026-09-29T02:10:00Z', expires_at: '2026-10-29T02:10:00Z',
        } }
      : report;
    return new Response(JSON.stringify(response), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  };
  await renderPanel();

  const textarea = container.querySelector('textarea');
  await act(async () => {
    textarea.value = '현재 범위에서 운영 승인을 진행합니다.';
    textarea.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    for (const checkbox of container.querySelectorAll('input[type="checkbox"]')) checkbox.click();
  });
  const form = container.querySelector('.poc-evaluation__decision-form');
  await act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })));

  const write = requests.find((item) => item.init.method === 'PUT');
  assert.equal(write.url, '/api/projects/prj_eval/poc-evaluation/decision?dataset_profile=local-eval');
  assert.deepEqual(JSON.parse(write.init.body), {
    decision: 'APPROVED', note: '현재 범위에서 운영 승인을 진행합니다.',
    scope_acknowledged: true, risk_acknowledged: true, valid_days: 30,
  });
  assert.match(container.textContent, /책임자 판단승인/);
});
