import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { evidenceVerdictCopy, readinessRows, taskRows } from '../src/viewModel.ts';

const readiness = {
  dataset: 'demo', dataset_name: 'demo', unscored_observations: [],
  readiness: {
    readiness_score: 50, schema_version: 'ax-readiness-score-v1', as_of_date: '2026-01-01', stale_threshold_days: 365,
    dimensions: { accessibility: .5, completeness: .6, redundancy: .4, timeliness: .7, safety: .8 },
    dimension_weights: { accessibility: .2, completeness: .2, redundancy: .2, timeliness: .2, safety: .2 },
    counts: {
      accessibility: { total_files: 2, parsed_files: 2, ocr_required_files: 0, accessible_files: 2 },
      completeness: { eligible_tables: 1, total_cells: 5, estimated_missing_cells: 1 },
      redundancy: { total_files: 2, exact_duplicate_groups: 0, redundant_files: 0 },
      timeliness: { files_with_valid_modified_at: 2, non_stale_files: 2, stale_files: 0, future_timestamp_files: 0, missing_timestamp_files: 0, invalid_timestamp_files: 0 },
      safety: { total_files: 2, pii_affected_files: 0, files_without_detected_pii: 2 },
    },
    flags: { empty_file_set: false, completeness_not_applicable: false, no_valid_modified_at: false, missing_modified_at_count: 0, invalid_modified_at_count: 0, future_modified_at_count: 0, unknown_ocr_file_id_count: 0, unknown_pii_file_id_count: 0, scan_metadata_file_count_mismatch: false },
  },
};

test('readiness adapter uses only response dimensions, counts, and flags', () => {
  const rows = readinessRows(readiness);
  assert.deepEqual(rows.map((row) => row.key), ['redundancy', 'completeness', 'safety', 'accessibility', 'timeliness']);
  assert.equal(rows[0].score, 40);
  assert.equal(rows[0].name, '완전 중복 파일');
  assert.equal(rows[0].description, 'Exact duplicate files');
  assert.equal(rows[2].name, '개인정보 패턴 탐지');
  assert.equal(rows[2].description, 'PII pattern detection');
  assert.deepEqual(rows[0].counts.map((item) => item.value), ['2', '0', '0']);
  assert.ok(rows[0].flags.some((item) => item.label === '빈 파일 집합' && item.value === '아니요'));
});

test('dataset control is API-backed and cannot fall back to free text', () => {
  const controlSource = readFileSync(new URL('../src/components/RunControls.tsx', import.meta.url), 'utf8');
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(controlSource, /<select id="dataset"/);
  assert.doesNotMatch(controlSource, /<input id="dataset"/);
  assert.match(controlSource, /option\.display_label/);
  assert.match(appSource, /api\.datasets\(\)/);
  assert.match(appSource, /setDatasets\(\[\]\)/);
  assert.match(appSource, /setDataset\(''\)/);
});

test('task adapter preserves candidate and approval fields without manufacturing rows', () => {
  assert.deepEqual(taskRows({ dataset: 'demo', catalog_status: 'CANDIDATES_AVAILABLE', tasks: [] }), []);
  const rows = taskRows({ dataset: 'demo', catalog_status: 'CANDIDATES_AVAILABLE', tasks: [{ task_id: 'T-1', question: 'Q', category: '정책', status: 'CANDIDATE', description: '선택형 후보' }] });
  assert.deepEqual(rows, [{ id: 'T-1', label: 'Q', status: 'CANDIDATE', approvalScope: null, fields: [
    { label: 'category', value: '정책' },
    { label: 'status', value: 'CANDIDATE' },
    { label: 'description', value: '선택형 후보' },
  ] }]);

  const verified = taskRows({ dataset: 'demo', catalog_status: 'VERIFIED_TASKS_AVAILABLE', tasks: [{
    task_id: 'T-2', question: 'Approved?', category: '정책', status: 'VERIFIED', description: '검증 업무',
    approval: { approval_id: 'A-1', owner_role: '정책 담당자', success_criteria: ['근거 포함'], approval_scope: 'CUSTOMER', approved_by_role: '업무 책임자', approved_at: '2026-09-28' },
  }] });
  assert.equal(verified[0].status, 'VERIFIED');
  assert.equal(verified[0].approvalScope, 'CUSTOMER');
  assert.deepEqual(verified[0].fields.slice(2, 6), [
    { label: 'owner', value: '정책 담당자' },
    { label: 'criteria', value: '근거 포함' },
    { label: 'approver', value: '업무 책임자' },
    { label: 'approved', value: '2026-09-28' },
  ]);
});

test('all evidence checker verdicts have explicit Korean display copy', () => {
  assert.deepEqual(Object.keys(evidenceVerdictCopy), ['DIRECT_MATCH', 'DERIVABLE', 'PARTIAL_SUPPORT', 'UNCONFIRMED']);
  assert.equal(evidenceVerdictCopy.UNCONFIRMED.label, '확인 불가');
});

test('expandable report controls expose keyboard-native buttons and aria state', () => {
  const readinessSource = readFileSync(new URL('../src/components/ReadinessTable.tsx', import.meta.url), 'utf8');
  const findingSource = readFileSync(new URL('../src/components/FindingCard.tsx', import.meta.url), 'utf8');
  for (const source of [readinessSource, findingSource]) {
    assert.match(source, /<button/);
    assert.match(source, /aria-expanded=/);
  }
});

test('report DOM order keeps diagnostic results ahead of controls', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const order = [
    '<SummarySection', 'id="findings"', '<ReadinessTable', '<TaskTable',
    '<EvidenceCheckPanel', '<RunControls', 'className="dev-banner"',
  ].map((needle) => appSource.indexOf(needle));
  assert.ok(order.every((index) => index >= 0));
  assert.deepEqual(order, [...order].sort((left, right) => left - right));
});

test('task-centric summary and finding cards keep task and run counts separate', () => {
  const summarySource = readFileSync(new URL('../src/components/SummarySection.tsx', import.meta.url), 'utf8');
  const findingSource = readFileSync(new URL('../src/components/FindingCard.tsx', import.meta.url), 'utf8');
  assert.match(summarySource, /AI 업무 진단/);
  assert.match(summarySource, /processable_task_count/);
  assert.match(summarySource, /blocked_task_count/);
  assert.match(findingSource, /affected_task_count/);
  assert.match(findingSource, /observed_run_count/);
  assert.match(findingSource, /After에서 재현되지 않음/);
  assert.match(findingSource, /실행에서 반환된 근거/);
  assert.match(findingSource, /권고 조치/);
});

test('unscored observations render once outside readiness dimension rows', () => {
  const source = readFileSync(new URL('../src/components/ReadinessTable.tsx', import.meta.url), 'utf8');
  assert.equal(source.match(/data\.unscored_observations\.map/g)?.length, 1);
  assert.match(source, /점수에 포함되지 않으며/);
});

test('visual tokens use the approved report palette', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const expected = {
    '--color-ink': '#0A1E3D', '--color-accent': '#0F62FE', '--color-sub': '#35506E',
    '--color-muted': '#58748F', '--color-faint': '#8FA3BC', '--color-line': '#C3D6E8',
    '--color-line-light': '#DFEAF4', '--color-surface': '#EEF4FA', '--color-bg': '#FFFFFF',
    '--color-warn': '#C43F5B', '--color-evidence-bg': '#0A1E3D',
    '--color-evidence-label': '#93AAC8', '--color-evidence-link': '#7CC0F5',
  };
  for (const [name, value] of Object.entries(expected)) assert.match(css, new RegExp(`${name}: ${value}`));
  assert.doesNotMatch(css, /box-shadow/);
  assert.match(css, /border-radius: 0/);
});

test('report uses color as an accent instead of filling information panels', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  for (const selector of ['.status', '.notice', '.readiness-detail', '.evidence-result', '.not-incorrect']) {
    const rule = css.match(new RegExp(`${selector.replace('.', '\\.')}(?:\\s|\\{|[^\\{])*\\{[^}]*\\}`))?.[0] ?? '';
    assert.match(rule, /background: transparent/);
  }
  assert.doesNotMatch(css, /\.report-tabs button\.is-active\s*\{[^}]*background:/);
  assert.doesNotMatch(css, /\.control-grid button, \.primary-action\s*\{[^}]*background:\s*var\(--color-(?:ink|accent)\)/);
});

test('rendered styles use the muted palette for secondary typography only', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const rule = (selector) => css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{[^}]*\\}`))?.[0] ?? '';
  assert.match(rule('.brand-name'), /color: var\(--color-sub\)/);
  assert.match(rule('.sidebar-label'), /color: var\(--color-muted\)/);
  assert.match(rule('.summary-verdict > p'), /color: var\(--color-sub\)/);
  assert.match(rule('.summary-verdict__line span'), /color: var\(--color-ink\)/);
  assert.match(rule('.status--positive'), /color: var\(--color-accent\)/);
});

test('divider hierarchy keeps strong rules at section and sheet starts', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const rule = (selector) => css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{[^}]*\\}`))?.[0] ?? '';
  assert.match(css, /--color-rule-strong: #0A1E3D/);
  assert.match(rule('.section-heading'), /border-bottom: 1px solid var\(--color-rule-strong\)/);
  assert.doesNotMatch(rule('.summary-status'), /border/);
  assert.match(rule('.readiness-table'), /border-top: 1px solid var\(--color-rule-strong\)/);
  assert.match(rule('.readiness-row'), /border: 0/);
  assert.match(rule('.readiness-row + .readiness-row'), /border-top: 1px solid var\(--color-rule-soft\)/);
  assert.doesNotMatch(rule('.detail-group dl div, .derivation dl div'), /border/);
  assert.doesNotMatch(rule('.source-link'), /border/);
  assert.doesNotMatch(rule('.finding-meta > div'), /border/);
  assert.doesNotMatch(rule('.finding-card, .blocked-card'), /border/);
  assert.match(rule('.evidence-result'), /border-top: 2px solid var\(--color-rule-strong\)/);
  assert.doesNotMatch(rule('.evidence-result'), /border-bottom/);
  assert.doesNotMatch(rule('.source-groups'), /border/);
  assert.doesNotMatch(rule('.evidence-references > div'), /border/);
  assert.doesNotMatch(rule('.fixture-control'), /border/);
  assert.doesNotMatch(rule('.dev-banner'), /border/);
});
