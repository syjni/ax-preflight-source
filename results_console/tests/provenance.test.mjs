import test from 'node:test';
import assert from 'node:assert/strict';
import { assessRunContext } from '../src/provenance.ts';

test('matching run and readiness profiles have no context warning', () => {
  assert.deepEqual(assessRunContext('mini', 'mini'), {
    kind: 'MATCH', selected: 'mini', origin: 'mini', warning: null,
  });
});

test('different run profile is a visible context mismatch', () => {
  const assessment = assessRunContext('mini', 'ceiling');
  assert.equal(assessment.kind, 'MISMATCH');
  assert.match(assessment.warning, /mini/);
  assert.match(assessment.warning, /ceiling/);
});

test('legacy missing provenance stays UNKNOWN and warns', () => {
  for (const recorded of [undefined, 'UNKNOWN']) {
    const assessment = assessRunContext('mini', recorded);
    assert.equal(assessment.kind, 'UNKNOWN');
    assert.equal(assessment.origin, 'UNKNOWN');
    assert.match(assessment.warning, /UNKNOWN/);
  }
});
