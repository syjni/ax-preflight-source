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

  const buttons = [...container.querySelectorAll('button')];
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

  const buttons = [...container.querySelectorAll('button')];
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
