import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { LocalDatasetPanel } from '../src/components/LocalDatasetPanel.tsx';

const capabilities = {
  mode: 'LOCAL_REVIEW', local_dataset_scan: true, ai_task_execution: false,
  bundled_demo: true, source_files_stay_local: true,
  supported_extensions: ['.txt', '.pdf', '.docx', '.csv', '.xlsx'],
};

const scanResult = {
  dataset: {
    profile: 'local-review-data-abcd123456', dataset_name: 'review-data-local-abcd123456',
    display_label: '내 자료 · 심사 자료', origin: 'LOCAL',
    scanned_at: '2026-09-29T01:00:00+09:00', source_root_name: 'review-data',
  },
  audit: {
    profile: 'local-review-data-abcd123456', dataset_name: 'review-data-local-abcd123456',
    display_label: '내 자료 · 심사 자료', source_root_name: 'review-data',
    scanned_at: '2026-09-29T01:00:00+09:00', as_of_date: '2026-09-29',
    local_only: true, supported_extensions: capabilities.supported_extensions,
    file_count: 3, parsed_file_count: 2, unsupported_file_count: 1,
    error_file_count: 0, table_count: 1, duplicate_group_count: 0,
    probable_version_group_count: 0, pii_finding_count: 1, ocr_required_count: 0,
    issues: [{
      code: 'PII_PATTERN', severity: 'warning', count: 1,
      title: '개인정보 가능 패턴', action: '마스킹 범위를 검토하세요.',
      relative_paths: ['contacts.txt'],
    }],
    files: [
      { relative_path: 'contacts.txt', extension: '.txt', size_bytes: 40, modified_at: '2026-09-29T00:00:00Z', parse_status: 'PARSED', parser: 'text', text_char_count: 20, pii_finding_count: 1, requires_ocr: false },
      { relative_path: 'orders.csv', extension: '.csv', size_bytes: 2048, modified_at: '2026-09-29T00:00:00Z', parse_status: 'PARSED', parser: 'csv', text_char_count: 100, pii_finding_count: 0, requires_ocr: false },
      { relative_path: 'logo.png', extension: '.png', size_bytes: 4096, modified_at: '2026-09-29T00:00:00Z', parse_status: 'UNSUPPORTED', text_char_count: 0, pii_finding_count: 0, requires_ocr: false, issue: 'Unsupported extension' },
    ],
  },
  readiness: {
    dataset: 'local-review-data-abcd123456', dataset_name: 'review-data-local-abcd123456',
    readiness: { readiness_score: 83.3 }, unscored_observations: [],
  },
};

let dom;
let root;
let container;
let originalFetch;

beforeEach(() => {
  dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://127.0.0.1:5173/' });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  originalFetch = globalThis.fetch;
  container = document.getElementById('root');
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  globalThis.fetch = originalFetch;
  dom.window.close();
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.location;
  delete globalThis.IS_REACT_ACT_ENVIRONMENT;
});

test('reviewer can scan a local folder and inspect actionable file results', async () => {
  const requests = [];
  const scanned = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    return new Response(JSON.stringify(scanResult), {
      status: 201, headers: { 'Content-Type': 'application/json' },
    });
  };
  await act(async () => root.render(React.createElement(LocalDatasetPanel, {
    capabilities, capabilitiesError: '', selectedDataset: null,
    onScanned: (result) => scanned.push(result), onDeleted: () => {},
  })));

  const pathInput = container.querySelector('#local-source-path');
  const nameInput = container.querySelector('#local-display-name');
  const setValue = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setValue.call(pathInput, 'C:\\review-data');
    pathInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    pathInput.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    setValue.call(nameInput, '심사 자료');
    nameInput.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    nameInput.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  });
  await act(async () => container.querySelector('form').dispatchEvent(
    new dom.window.Event('submit', { bubbles: true, cancelable: true }),
  ));

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/local-datasets');
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    source_path: 'C:\\review-data', display_name: '심사 자료',
  });
  assert.equal(scanned.length, 1);
  assert.match(container.textContent, /LOCAL AUDIT COMPLETE/);
  assert.match(container.textContent, /READINESS83/);
  assert.match(container.textContent, /개인정보 가능 패턴/);
  assert.match(container.textContent, /원본을 복사·수정하지 않습니다/);
});

test('public demo preserves the example while clearly routing local review to source', async () => {
  await act(async () => root.render(React.createElement(LocalDatasetPanel, {
    capabilities: { ...capabilities, mode: 'STATIC_DEMO', local_dataset_scan: false },
    capabilitiesError: '', selectedDataset: null, onScanned: () => {}, onDeleted: () => {},
  })));
  assert.equal(container.querySelector('form'), null);
  assert.match(container.textContent, /검증된 예시/);
  assert.match(container.textContent, /외부 서버로 파일을 전송하지 않습니다/);
  assert.equal(
    container.querySelector('a').getAttribute('href'),
    'https://github.com/syjni/ax-preflight-source#내-자료로-점검하기',
  );
});
