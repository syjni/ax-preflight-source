import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';


test('live console requests the same verified featured journey as static mode', () => {
  const api = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8');

  assert.match(api, /request<FeaturedCasesResponse>\('\/api\/featured-cases'\)/);
  assert.doesNotMatch(api, /Promise\.resolve\(\[\] as FeaturedCase\[\]\)/);
});
