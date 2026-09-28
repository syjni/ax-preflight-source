import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const component = readFileSync(new URL('../src/components/ExecutiveReport.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

test('manager report exposes Before/After, actionable fixes, and browser PDF export', () => {
  assert.match(component, /Before/);
  assert.match(component, /After/);
  assert.match(component, /recommended_action/);
  assert.match(component, /affected_task_count/);
  assert.match(component, /window\.print\(\)/);
  assert.match(component, /PDF로 저장 \/ 인쇄/);
});

test('print stylesheet isolates the one-page executive report', () => {
  assert.match(styles, /@media print/);
  assert.match(styles, /@page \{ size: A4/);
  assert.match(styles, /report-main > \*:not\(\.executive-report\)/);
});
