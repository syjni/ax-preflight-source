import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { FeaturedCaseJourney } from '../src/components/FeaturedCaseJourney.tsx';

const featuredCase = {
  case_id: 'return-policy-remediation',
  title: '반품 기간 충돌 해결',
  question: '현재 반품 가능 기간은 며칠인가요?',
  summary: '검증된 대표 사례',
  before: {
    phase: 'BEFORE', label: '정리 전', dataset: 'before', run_id: 'before-r1',
    result: '0 / 3 답변', detail: '근거 충돌로 3회 모두 보류', action_label: '보류 근거 보기', target: 'summary',
  },
  after: {
    phase: 'AFTER', label: '정리 후', dataset: 'after', run_id: 'after-r1',
    result: '3 / 3 답변', detail: '30일 · 근거 직접 일치', action_label: '30일 근거 확인', target: 'evidence',
  },
  walkthrough: {
    label: '검증된 동결 예시', read_only: true, snapshot_id: 'phase6-v4',
    recommendation: 'CONDITIONAL_GO', recommendation_note: '실행 근거는 통과했지만 조직별 운영 승인은 별도입니다.',
    approved_task_id: 'TASK_POLICY_RETURN_WINDOW', approved_task_question: '현재 반품 가능 기간은 며칠인가요?',
    approval_scope: 'CONTROLLED_DEMO', successful_runs: 3, direct_evidence_runs: 3,
    direct_evidence_ratio: 1, cited_source_ids: ['DOC_POLICY'], model: 'frozen-model',
    failure_recovery: '정리 전 근거 충돌 3회 보류에서 정리 후 3회 답변으로 바뀌었습니다.',
    model_boundary: '과거 동결 실행의 모델 식별자만 표시하며 현재 자격 증명이나 전송 승인을 뜻하지 않습니다.',
    cost_control: '동결 산출물에는 프로젝트 비용 승인 기록이 없어 실제 도입 전에 설정해야 합니다.',
    audit_retention: 'v4 manifest는 검증됐지만 조직별 감사·보존 승인은 별도입니다.',
    final_report_note: '검증된 실행 사례는 조건부 진행 근거이며 실제 조직 승인을 대신하지 않습니다.',
    gates: [
      { code: 'EXECUTION_SAMPLE', label: '성공 실행 표본', status: 'PASS', detail: '3/3' },
      { code: 'DIRECT_EVIDENCE', label: '직접 근거', status: 'PASS', detail: '3/3' },
      { code: 'MODEL_BOUNDARY', label: '모델·전달 승인', status: 'WARN', detail: '조직별 승인 필요' },
      { code: 'COST_CONTROL', label: '비용 통제', status: 'WARN', detail: '조직별 설정 필요' },
      { code: 'AUDIT_RETENTION', label: '감사·보존', status: 'WARN', detail: '조직별 정책 필요' },
    ],
  },
};

let dom;
let root;
let container;

beforeEach(() => {
  dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>');
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.getElementById('root');
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  dom.window.close();
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.IS_REACT_ACT_ENVIRONMENT;
});

test('verified Before and After stages open their exact frozen references', async () => {
  const opened = [];
  await act(async () => root.render(React.createElement(FeaturedCaseJourney, {
    cases: [featuredCase], currentDataset: 'before', currentRunId: null,
    loadingRunId: null, error: '', onOpen: (reference) => opened.push(reference),
  })));

  const buttons = [...container.querySelectorAll('.featured-case__stage')];
  assert.equal(buttons.length, 2);
  assert.match(buttons[0].textContent, /0 \/ 3 답변/);
  assert.match(buttons[1].textContent, /30일 근거 확인/);

  await act(async () => buttons[0].click());
  await act(async () => buttons[1].click());
  assert.deepEqual(opened, [featuredCase.before, featuredCase.after]);
});

test('selected and loading states are explicit and prevent duplicate requests', async () => {
  await act(async () => root.render(React.createElement(FeaturedCaseJourney, {
    cases: [featuredCase], currentDataset: 'after', currentRunId: 'after-r1',
    loadingRunId: 'after-r1', error: '', onOpen: () => {},
  })));

  const buttons = [...container.querySelectorAll('.featured-case__stage')];
  assert.equal(buttons[1].getAttribute('aria-pressed'), 'true');
  assert.equal(buttons[0].disabled, true);
  assert.equal(buttons[1].disabled, true);
  assert.match(buttons[1].textContent, /불러오는 중/);
});

test('the journey stays absent when a deployment has no verified featured case', async () => {
  await act(async () => root.render(React.createElement(FeaturedCaseJourney, {
    cases: [], currentDataset: '', currentRunId: null,
    loadingRunId: null, error: '', onOpen: () => {},
  })));

  assert.equal(container.textContent, '');
});

test('verified frozen PoC is a connected read-only journey with an honest approval report', async () => {
  let printCalls = 0;
  window.print = () => { printCalls += 1; };
  await act(async () => root.render(React.createElement(FeaturedCaseJourney, {
    cases: [featuredCase], currentDataset: 'before', currentRunId: null,
    loadingRunId: null, error: '', onOpen: () => {},
  })));

  assert.match(container.textContent, /검증된 동결 예시/);
  assert.match(container.textContent, /읽기 전용/);
  assert.match(container.textContent, /승인 업무/);
  assert.match(container.textContent, /실행 결과/);
  assert.match(container.textContent, /근거 경로와 인용/);
  assert.match(container.textContent, /실패 복구/);
  assert.match(container.textContent, /모델·데이터 전달 경계/);
  assert.match(container.textContent, /비용·실행 통제/);
  assert.match(container.textContent, /감사·보존 상태/);
  assert.match(container.textContent, /PoC 평가 게이트/);
  assert.match(container.textContent, /최종 승인 보고서/);
  assert.match(container.textContent, /CONDITIONAL/);

  const printButton = [...container.querySelectorAll('button')].find((button) => button.textContent === '읽기 전용 보고서 인쇄');
  await act(async () => printButton.click());
  assert.equal(printCalls, 1);
  assert.equal(document.body.classList.contains('print-frozen-poc'), true);
  window.dispatchEvent(new window.Event('afterprint'));
  assert.equal(document.body.classList.contains('print-frozen-poc'), false);
});
