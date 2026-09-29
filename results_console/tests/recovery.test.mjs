import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RecoveryNotice } from '../src/components/RecoveryNotice.tsx';
import { runFailureFor } from '../src/recovery.ts';

function apiError(status, detail) {
  return Object.assign(new Error(detail), { status, detail });
}

test('read-only runner failures direct users to verified evidence instead of a dead retry', () => {
  const failure = runFailureFor(apiError(503, 'RUNNER_UNAVAILABLE'), 'submit');
  assert.equal(failure.kind, 'runner-unavailable');
  assert.equal(failure.actionLabel, '검증된 대표 흐름 보기');
  assert.match(failure.message, /읽기 전용/);
});

test('missing runs preserve the lookup context and ask for ID correction', () => {
  const failure = runFailureFor(apiError(404, 'run not found'), 'lookup');
  assert.equal(failure.kind, 'run-not-found');
  assert.equal(failure.source, 'lookup');
  assert.equal(failure.code, 'RUN_NOT_FOUND');
});

test('recovery notice exposes the error code, explanation, and next action', () => {
  const failure = runFailureFor(apiError(0, 'API_CONNECTION_FAILED'), 'poll');
  const html = renderToStaticMarkup(React.createElement(RecoveryNotice, { failure, onAction: () => {} }));
  assert.match(html, /role="alert"/);
  assert.match(html, /API_CONNECTION_FAILED/);
  assert.match(html, /다시 시도/);
});

test('onboarding blockers direct the user to the preflight checks', () => {
  const failure = runFailureFor(apiError(409, 'ONBOARDING_BLOCKED'), 'submit');
  assert.equal(failure.kind, 'onboarding-blocked');
  assert.equal(failure.actionLabel, '온보딩 검사 보기');
  assert.match(failure.message, /원본 무결성/);
});

test('model boundary and budget blockers route users to project execution control', () => {
  for (const code of ['DATA_TRANSFER_APPROVAL_REQUIRED', 'MODEL_NOT_APPROVED', 'DAILY_BUDGET_REACHED']) {
    const failure = runFailureFor(apiError(409, code), 'submit');
    assert.equal(failure.kind, 'execution-control');
    assert.equal(failure.actionLabel, '실행 통제 설정 보기');
    assert.equal(failure.code, code);
  }
});
