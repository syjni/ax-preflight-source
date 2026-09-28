import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const finding = readFileSync(new URL('../src/components/FindingCard.tsx', import.meta.url), 'utf8');
const executive = readFileSync(new URL('../src/components/ExecutiveReport.tsx', import.meta.url), 'utf8');

test('inconsistent answers are shown as cause-unconfirmed rather than document defects', () => {
  assert.match(finding, /불안정 업무 · 원인 미확인/);
  assert.match(finding, /CAUSE_UNCONFIRMED/);
  assert.match(finding, /데이터 원인 미확인/);
  assert.match(finding, /비교한 답변 실행/);
});

test('manager report separates review signals from document fixes', () => {
  assert.match(executive, /우선 검토할 불안정·데이터 신호/);
  assert.match(executive, /데이터 원인 미확인/);
  assert.doesNotMatch(executive, /우선 수정할 데이터/);
});
