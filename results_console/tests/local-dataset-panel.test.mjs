import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { LocalDatasetPanel } from '../src/components/LocalDatasetPanel.tsx';

const capabilities = {
  mode: 'LOCAL_REVIEW', local_dataset_scan: true, ai_task_execution: false,
  local_file_upload: true, local_path_scan: true, bundled_demo: true, source_files_stay_local: true,
  supported_extensions: ['.txt', '.pdf', '.docx', '.csv', '.xlsx'],
  max_upload_files: 5000, max_upload_bytes: 1073741824,
  max_upload_file_bytes: 104857600,
  pdf_table_extraction: true, ocr_available: false, ocr_languages: [],
  ocr_install_hint: 'Docker 실행에는 OCR이 포함됩니다.',
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
    source_mode: 'PATH', source_files_copied: false, managed_copy_deleted_with_record: false,
    file_count: 3, parsed_file_count: 2, unsupported_file_count: 1,
    error_file_count: 0, table_count: 1, pdf_table_count: 0, ocr_completed_file_count: 0, duplicate_group_count: 0,
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
let originalFormData;
let originalFile;

beforeEach(() => {
  dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url: 'http://127.0.0.1:5173/' });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  originalFetch = globalThis.fetch;
  originalFormData = globalThis.FormData;
  originalFile = globalThis.File;
  globalThis.FormData = dom.window.FormData;
  globalThis.File = dom.window.File;
  container = document.getElementById('root');
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  globalThis.fetch = originalFetch;
  globalThis.FormData = originalFormData;
  globalThis.File = originalFile;
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

  await act(async () => {
    [...container.querySelectorAll('[role="tab"]')].find((button) => /허용된 서버 폴더/.test(button.textContent)).click();
  });

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
  assert.match(container.textContent, /원본 파일을 복사하거나 수정하지 않습니다/);
});

test('reviewer can choose browser files and send them only to the local upload endpoint', async () => {
  const requests = [];
  const uploadedResult = {
    ...scanResult,
    audit: { ...scanResult.audit, source_mode: 'UPLOAD', source_files_copied: true, managed_copy_deleted_with_record: true },
  };
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    return new Response(JSON.stringify(uploadedResult), {
      status: 201, headers: { 'Content-Type': 'application/json' },
    });
  };
  await act(async () => root.render(React.createElement(LocalDatasetPanel, {
    capabilities, capabilitiesError: '', selectedDataset: null,
    onScanned: () => {}, onDeleted: () => {},
  })));

  const picker = container.querySelectorAll('input[type="file"]')[1];
  const chosen = new dom.window.File(['order_id,amount\nA-1,12000'], 'orders.csv', { type: 'text/csv' });
  Object.defineProperty(picker, 'files', { configurable: true, value: [chosen] });
  await act(async () => picker.dispatchEvent(new dom.window.Event('change', { bubbles: true })));
  assert.match(container.textContent, /1개 파일 선택/);

  await act(async () => container.querySelector('form').dispatchEvent(
    new dom.window.Event('submit', { bubbles: true, cancelable: true }),
  ));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/local-datasets/upload');
  assert.ok(requests[0].init.body instanceof dom.window.FormData);
  assert.deepEqual(JSON.parse(requests[0].init.body.get('relative_paths')), ['orders.csv']);
  assert.match(container.textContent, /로컬 관리 복사본/);
});

test('Docker-safe reviewer mode defaults to browser folder upload and hides server paths', async () => {
  await act(async () => root.render(React.createElement(LocalDatasetPanel, {
    capabilities: { ...capabilities, local_path_scan: false },
    capabilitiesError: '', selectedDataset: null,
    onScanned: () => {}, onDeleted: () => {},
  })));

  assert.match(container.textContent, /호스트 폴더의 파일을 브라우저가 로컬 Docker API로 전송/);
  assert.match(container.textContent, /파일·폴더 선택/);
  assert.doesNotMatch(container.textContent, /폴더 경로 입력/);
  assert.equal(container.querySelector('#local-source-path'), null);
});

test('public demo preserves the example while clearly routing local review to source', async () => {
  await act(async () => root.render(React.createElement(LocalDatasetPanel, {
    capabilities: { ...capabilities, mode: 'STATIC_DEMO', local_dataset_scan: false },
    capabilitiesError: '', selectedDataset: null, onScanned: () => {}, onDeleted: () => {},
  })));
  assert.equal(container.querySelector('form'), null);
  assert.match(container.textContent, /검증된 예시로 둘러보기/);
  assert.match(container.textContent, /동결된 60회 결과/);
  assert.match(container.textContent, /자료와 모델 자격 증명을 공개 호스팅으로 받지 않기 위해/);
  assert.match(container.textContent, /Kiro CLI와 모델 자격 증명을 명시적으로 연결한 live mode/);
  assert.equal(
    container.querySelector('a').getAttribute('href'),
    'https://github.com/syjni/ax-preflight-source#내-자료로-점검하기',
  );
});
