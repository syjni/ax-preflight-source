import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const summary = read('../src/components/SummarySection.tsx');
const finding = read('../src/components/FindingCard.tsx');
const evidence = read('../src/components/EvidenceCheckPanel.tsx');
const executive = read('../src/components/ExecutiveReport.tsx');
const styles = read('../src/style.css');
const reviewGenerator = read('../scripts/build-claude-review.mjs');
const viewModel = read('../src/viewModel.ts');
const readinessTable = read('../src/components/ReadinessTable.tsx');

test('first screen leads with the readiness-versus-return outcome and exhaustive task classes', () => {
  assert.match(summary, /impact-story/);
  assert.match(summary, /정적 Data Readiness/);
  assert.match(summary, /반품 기간 업무/);
  assert.match(summary, /staticDemo/);
  assert.match(summary, /0 \/ 3/);
  assert.match(summary, /3 \/ 3/);
  assert.match(summary, /비교 결과 조회 전/);
  assert.match(summary, /processable_task_count/);
  assert.match(summary, /blocked_task_count/);
  assert.match(summary, /inconclusive_task_count/);
  assert.match(summary, /legacy_diagnostics/);
});

test('findings separate mixed outcomes, expose conflict excerpts, and hide audit identifiers', () => {
  assert.match(finding, /MIXED_OUTCOMES/);
  assert.match(finding, /실행 결과 혼재/);
  assert.match(finding, /RETRIEVAL_LIMITATION/);
  assert.match(finding, /검색 경로 한계 확인/);
  assert.match(finding, /서로 충돌한 원문/);
  assert.match(finding, /검색했지만 답을 확정하지 못한 자료/);
  assert.match(finding, /finding-audit/);
  assert.match(finding, /technical-detail/);
  assert.match(finding, /답변된 실행의 값/);
  assert.match(finding, /보류된 실행의 사유/);
  assert.match(finding, /structured-table/);
  assert.match(finding, /정리 후 원문 · 현재 FAQ/);
  assert.match(finding, /finding\.finding_type === 'CONFLICTING_SOURCES' \? highlightedExcerpt/);
});

test('manager-facing content uses Korean labels and keeps technical evidence details collapsed', () => {
  assert.doesNotMatch(summary, /CURRENT RUN OUTCOME|Dataset aggregate|Observed runs/);
  assert.doesNotMatch(executive, />Dataset</);
  assert.match(executive, /반복 안정 처리/);
  assert.match(evidence, /evidence-audit/);
  assert.match(evidence, /근거 연결 감사 정보/);
  assert.match(viewModel, /개인정보 패턴 탐지/);
  assert.match(viewModel, /완전 중복 파일/);
  assert.match(readinessTable, /등록된 개인정보 탐지 패턴 기반 점검/);
  assert.doesNotMatch(readinessTable, /PII pattern detection/);
});

test('answer formatting avoids appending an already-present unit', () => {
  assert.match(summary, /endsWith\(compactUnit\)/);
  assert.match(finding, /endsWith\(compactUnit\)/);
  assert.match(finding, /compactUnit === 'krw'/);
  assert.match(finding, /compactUnit === 'date'/);
  assert.match(finding, /근거가 부족해 보류/);
  assert.match(finding, /정리 전·후 반복 결과/);
  assert.match(finding, /회 보류 → .*회 답변/);
});

test('static review scopes nested finding layout and conflict highlighting', () => {
  assert.match(reviewGenerator, /\.finding>summary/);
  assert.doesNotMatch(reviewGenerator, /\.finding summary\{/);
  assert.match(reviewGenerator, /finding\.finding_type === 'CONFLICTING_SOURCES'/);
  assert.match(reviewGenerator, /structuredTable/);
  assert.match(reviewGenerator, /정리 전 FAQ · Before 실행에서 인용/);
  assert.match(reviewGenerator, /정리 후 FAQ · 현재 원문/);
  assert.match(reviewGenerator, /에이전트 설명 · 검증 대상 아님/);
  assert.match(reviewGenerator, /검색 경로 한계 확인/);
  assert.match(reviewGenerator, /finding-counts__transition/);
});

test('unstable summary metric is neutral and current evidence is visually distinct', () => {
  assert.match(styles, /diagnostic-metric--accent > strong \{ color: var\(--color-ink\); \}/);
  assert.match(styles, /executive-report__quote--current/);
  assert.match(styles, /finding-current-source/);
});
