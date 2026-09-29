import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { afterEach, test } from 'node:test';
import { api } from '../src/api.ts';

const originalFetch = globalThis.fetch;

afterEach(() => { globalThis.fetch = originalFetch; });

test('authenticated API writes carry the rotated CSRF token and same-origin credentials', async () => {
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    if (String(url).endsWith('/api/auth/session')) {
      return new Response(JSON.stringify({
        authentication_required: true,
        authenticated: true,
        bootstrap_required: false,
        user: { user_id: 'usr_1', username: 'owner', display_name: 'Owner', global_role: 'ADMIN' },
        csrf_token: 'rotated-csrf-token',
        expires_at: '2026-09-29T12:00:00Z',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return new Response(JSON.stringify({
      project_id: 'prj_123', name: 'PoC', description: '', member_role: 'OWNER',
      member_count: 1, created_at: '2026-09-29T01:00:00Z',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } });
  };

  await api.authSession();
  await api.createProject({ name: 'PoC', description: '' });

  assert.equal(requests[0].init.credentials, 'same-origin');
  assert.equal(requests[1].init.credentials, 'same-origin');
  assert.equal(requests[1].init.headers['X-CSRF-Token'], 'rotated-csrf-token');
  assert.equal(requests[1].init.method, 'POST');
});

test('workspace UI exposes project selection, account membership, and task approval controls', () => {
  const source = readFileSync(new URL('../src/components/WorkspacePanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /PROJECT ACCESS/);
  assert.match(source, /새 로그인 계정 만들기/);
  assert.match(source, /기존 계정에 프로젝트 권한 주기/);
  assert.match(source, /BUSINESS TASK CONTROL/);
  assert.match(source, /api\.approveProjectTask/);
  assert.match(source, /member_role === 'OWNER'/);
  assert.match(source, /api\.removeProjectMember/);
  assert.match(source, /api\.revokeUserSessions/);
});

test('project governance shows retained records and requires exact-name deletion', () => {
  const source = readFileSync(new URL('../src/components/ProjectGovernancePanel.tsx', import.meta.url), 'utf8');
  const styles = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  assert.match(source, /DATA GOVERNANCE/);
  assert.match(source, /설정된 날짜에 자동 삭제하지 않습니다/);
  assert.match(source, /confirmation !== project\.name/);
  assert.match(source, /원본 경로의 파일은 항상 유지됩니다/);
  assert.match(source, /api\.projectDataInventory/);
  assert.match(source, /api\.projectAuditLog/);
  assert.match(source, /api\.updateRetentionPolicy/);
  assert.match(source, /api\.purgeProject/);
  assert.match(source, /법적 보존/);
  assert.match(source, /법적 보존 · 삭제 차단/);
  assert.match(source, /감사 확인 필요/);
  assert.match(source, /삭제 증명서/);
  assert.match(styles, /\.governance-panel__metrics/);
  assert.match(styles, /\.governance-panel__audit-list/);
  assert.match(styles, /var\(--color-warn\)/);
});

test('local dataset selection follows its project access boundary', () => {
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(source, /option\.origin === 'LOCAL' && option\.project_id/);
  assert.match(source, /selectedDatasetProject\?\.member_role === 'OWNER'/);
});
