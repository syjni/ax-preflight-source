import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { OnboardingPanel } from '../src/components/OnboardingPanel.tsx';

const assessment = {
  schema_version: 'ax-onboarding-assessment-v1',
  dataset: 'customer',
  dataset_name: 'customer-data',
  status: 'REVIEW_REQUIRED',
  can_run: true,
  blocker_count: 0,
  warning_count: 1,
  checks: [
    { code: 'DATASET_INTEGRITY', status: 'PASS', observed: 12, total: 12 },
    { code: 'BUSINESS_TASK_REVIEW', status: 'WARN', observed: 1, total: 3 },
  ],
};

test('onboarding preflight distinguishes runnable review items from blockers', () => {
  const html = renderToStaticMarkup(React.createElement(OnboardingPanel, {
    data: assessment, loading: false, error: '',
  }));

  assert.match(html, /검토 후 실행 가능/);
  assert.match(html, /실행 가능/);
  assert.match(html, /12개 파일 일치/);
  assert.match(html, /검증 1 \/ 전체 3개/);
  assert.match(html, /업무 담당자가 질문과 성공 기준을 확인/);
});

test('blocked onboarding states that execution is unavailable', () => {
  const html = renderToStaticMarkup(React.createElement(OnboardingPanel, {
    data: {
      ...assessment,
      status: 'BLOCKED',
      can_run: false,
      blocker_count: 1,
      checks: [{ code: 'DATASET_INTEGRITY', status: 'BLOCK', observed: null, total: null }],
    },
    loading: false,
    error: '',
  }));

  assert.match(html, /실행 차단/);
  assert.match(html, /실행 불가/);
  assert.match(html, /원본과 스캔 보고서/);
});
