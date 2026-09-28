import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8');
}

test('public UI consistently uses the AX Preflight display name and subtitles', () => {
  const index = read('../index.html');
  const portal = read('../src/components/Portal.tsx');
  const sidebar = read('../src/components/Sidebar.tsx');
  const report = read('../src/components/ExecutiveReport.tsx');
  const styles = read('../src/style.css');

  assert.match(index, /<title>AX Preflight · Results Console<\/title>/);
  assert.match(portal, /<span>AX Preflight<\/span><span>AI Data Readiness Audit<\/span>/);
  assert.match(portal, /AX Preflight · AI Data Readiness Audit · AI 업무 도입 전 점검/);
  assert.match(sidebar, /className="brand-symbol">AX Preflight<\/span>/);
  assert.match(report, /AX Preflight · AI 업무 도입 전 점검/);
  assert.match(styles, /\.executive-report__header small \{[^}]*text-transform: none;/);
});

test('intro calls to action use right arrows and separate local review from the example', () => {
  const portal = read('../src/components/Portal.tsx');

  assert.match(portal, /내 자료 점검하기 <span>→<\/span>/);
  assert.match(portal, /검증된 예시 보기 <span>→<\/span>/);
  assert.doesNotMatch(portal, /<span>↗<\/span>/);
});

test('guide states the actual local-storage and model-processing boundary', () => {
  const portal = read('../src/components/Portal.tsx');

  assert.match(portal, /원본 파일과 실행 산출물은 로컬 경로에서 관리합니다/);
  assert.match(portal, /문서 일부 또는 구조화 값이 설정된 모델 처리 경계로 전달될 수 있습니다/);
  assert.doesNotMatch(portal, /데이터가 외부로 나가지 않/);
});
