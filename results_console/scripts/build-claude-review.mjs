import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const outputDir = resolve(here, '../artifacts/claude-final-review');
const apiBase = (process.env.AX_REVIEW_API_BASE ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const afterDataset = 'portfolio-ceiling-after';
const beforeDataset = 'portfolio-hidden-conflict-before';
const exampleRunId = 'phase6v4-portfolio-ceiling-after-task_policy_return_window-r1';

async function getJson(path) {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${path}`);
  return response.json();
}

const [readiness, afterFindings, beforeFindings, tasks, exampleRun, exampleEvidence] = await Promise.all([
  getJson(`/api/readiness/${afterDataset}`),
  getJson(`/api/findings/${afterDataset}`),
  getJson(`/api/findings/${beforeDataset}`),
  getJson(`/api/tasks/${afterDataset}`),
  getJson(`/api/runs/${exampleRunId}`),
  getJson(`/api/runs/${exampleRunId}/evidence-check`),
]);
const afterFaqText = await readFile(resolve(here, '../../sample_data/ceiling_company/06_고객지원/FAQ_2026.txt'), 'utf8');
const currentReturnFaqExcerpt = afterFaqText.split(/\r?\n/).find((line) => line.includes('반품 가능 여부는 구매일'))?.trim();
if (!currentReturnFaqExcerpt) throw new Error('Could not locate the current return FAQ sentence.');

const sourceFacts = {
  artifact_purpose: 'Static review artifact for a five-minute judging-path critique. Not the production UI and not an API contract.',
  generated_at: new Date().toISOString(),
  datasets: { before: beforeDataset, after: afterDataset },
  interpretation_boundaries: [
    'Semantic comparison v2 reclassifies the same frozen runs as Before 5/10 stable, 3/10 consistently blocked, 2/10 mixed; After 6/10 stable, 2/10 consistently blocked, 2/10 mixed.',
    'Legacy comparison v1 remains auditable: Before 4/10 processable and After 2/10 processable. It over-counted wording and unit-format differences and treated any abstention as blocked.',
    'The descriptive 5/10 to 6/10 change is not a broad causal claim because only one source file changed.',
    'The defensible causal claim is limited to the return-window task: 0/3 conflict abstentions Before to 3/3 answered DIRECT_MATCH After.',
    'A mixed ANSWERED/ABSTAINED outcome is a human-review signal. The two order-task mixtures were traced to a retrieval top-k limitation, not a missing ledger or a filename mismatch.',
    'DIRECT_MATCH means the approved answer value matched cited same-run structured evidence under a narrow rule. It is not a general correctness guarantee.',
    'UNCONFIRMED does not mean incorrect.',
  ],
  audited_claims: {
    evidence_checker: {
      direct_match_runs: 35,
      observed_runs: 60,
      wording: '60회 중 35건에서 인용된 구조화 응답과 승인 답 값이 직접 일치했다.',
      limitation: 'This is a narrow evidence-link result, not a general accuracy rate.',
      source_document: 'docs/PHASE6_V4_DIRECT_MATCH_AUDIT.md',
    },
    manual_direct_match_audit: {
      passed_samples: 6,
      audited_samples: 6,
      limitation: 'The 6/6 sample does not guarantee the remaining runs or general correctness.',
      source_document: 'docs/PHASE6_V4_DIRECT_MATCH_AUDIT.md',
    },
    comparison_v1_audit: {
      changed_files: ['06_고객지원/FAQ_2026.txt'],
      legacy_v1_stable: { before: 4, after: 2 },
      semantic_v2_stable: { before: 5, after: 6 },
      conclusion: 'v1 over-counted representational differences and abstention mixtures. v2 is the current product interpretation; neither aggregate difference is presented as a causal effect.',
      source_document: 'docs/PHASE6_V4_STABILITY_REVIEW.md',
    },
    order_retrieval_audit: {
      source_file: '04_주문/주문_원장_2026.xlsx',
      file_id: 'FILE_950a2b2ed909ef4c',
      table_id: 'TABLE_FILE_950a2b2ed909ef4c_Orders',
      exact_policy_alias_search_rank: 4,
      conclusion: 'The ledger is parsed and indexed, but query wording and top-k ranking can prevent the agent from discovering it.',
      source_document: 'docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md',
    },
  },
  readiness,
  findings: { before: beforeFindings, after: afterFindings },
  tasks,
  representative_run: exampleRun,
  representative_evidence_check: exampleEvidence,
  current_return_faq_excerpt: currentReturnFaqExcerpt,
};

const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const typeLabel = {
  CONFLICTING_SOURCES: '문서 충돌',
  INCONSISTENT_ANSWERS: '의미값 불일치 · 원인 미확인',
  MIXED_OUTCOMES: '실행 결과 혼재',
  INSUFFICIENT_EVIDENCE: '근거 부족',
  MISSING_INFORMATION: '자료 공백',
};

const activeFindings = afterFindings.findings.filter((item) => item.comparison_status !== 'NOT_REPRODUCED_AFTER');
const previousFindings = afterFindings.findings.filter((item) => item.comparison_status === 'NOT_REPRODUCED_AFTER');
const after = afterFindings.diagnostics;
const before = beforeFindings.diagnostics;
const score = Math.round(readiness.readiness.readiness_score);
const payload = exampleRun.payload;
const limitationCopy = {
  'Checks only the approved Delivery JSON and cited structured tool responses from this run.': '승인된 결과 JSON과 같은 실행에서 인용한 구조화 도구 응답만 검사합니다.',
  'DERIVABLE is limited to exact sum, difference, and row count; division, rates, unit conversion, and semantic inference are out of scope.': '계산 확인은 정확한 합계·차이·행 수로 제한하며, 나눗셈·비율·단위 변환·의미 추론은 범위 밖입니다.',
  'A lexical direct match does not independently establish broader contextual entailment.': '문자열의 직접 일치만으로 더 넓은 문맥의 정합성까지 보증하지 않습니다.',
};

function findingTitle(finding) {
  return finding.affected_tasks.map((item) => item.label).join(', ');
}

function formatAnswer(answer, unit) {
  const value = Array.isArray(answer) ? answer.join(', ') : String(answer ?? '—');
  if (!unit) return value;
  const compactValue = value.replace(/\s/g, '').toLocaleLowerCase();
  const compactUnit = String(unit).replace(/\s/g, '').toLocaleLowerCase();
  if (compactUnit === 'date') return value;
  if (compactUnit === 'krw' && (compactValue.endsWith('원') || compactValue.startsWith('₩'))) return value;
  return compactValue.endsWith(compactUnit)
    ? value : `${value} ${unit}`;
}

function abstentionReason(reason) {
  return {
    NOT_FOUND: '필요한 자료를 찾지 못해 보류',
    INSUFFICIENT_EVIDENCE: '근거가 부족해 보류',
    CONFLICTING_EVIDENCE: '근거가 충돌해 보류',
  }[reason] ?? '판단을 보류';
}

function attributionCopy(status) {
  if (status === 'RETRIEVAL_LIMITATION') return '검색 경로 한계 확인';
  return status === 'CAUSE_UNCONFIRMED' ? '원인 미확인' : '데이터 신호';
}

function evidenceHeading(finding) {
  if (finding.finding_type === 'CONFLICTING_SOURCES') return '정리 전 실행에서 인용한 서로 충돌한 원문';
  if (finding.finding_type === 'MIXED_OUTCOMES') return '보류 실행에서 조회한 자료';
  return '검색했지만 답을 확정하지 못한 자료';
}

function evidenceContext(finding, sourceTitle) {
  if (finding.finding_type !== 'CONFLICTING_SOURCES') return '';
  return sourceTitle?.includes('FAQ_2026')
    ? '정리 전 원문 · Before 실행에서 인용'
    : '변경되지 않은 현행 정책 · Before 실행에서 인용';
}

function structuredTable(excerpt, toolName) {
  if (toolName !== 'query_table' || !excerpt) return '';
  try {
    const rows = JSON.parse(excerpt);
    if (!Array.isArray(rows) || !rows.length || !rows.every((row) => row && typeof row === 'object' && !Array.isArray(row))) return '';
    const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    const head = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('');
    const body = rows.map((row) => `<tr>${columns.map((column) => {
      const value = row[column];
      const display = typeof value === 'number' ? value.toLocaleString('ko-KR') : value ?? '—';
      return `<td>${escapeHtml(display)}</td>`;
    }).join('')}</tr>`).join('');
    return `<div class="structured-table-wrap"><table class="structured-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  } catch {
    return '';
  }
}

function evidenceExcerpt(finding, item) {
  const table = structuredTable(item.excerpt, item.tool_name);
  if (table) return table;
  if (!item.excerpt) return '';
  const escaped = escapeHtml(item.excerpt);
  return finding.finding_type === 'CONFLICTING_SOURCES'
    ? `<p>${escaped.replaceAll('14일', '<mark>14일</mark>').replaceAll('30일', '<mark>30일</mark>')}</p>`
    : `<p>${escaped}</p>`;
}

function findingCard(finding, index) {
  const variants = (finding.answer_variants ?? []).map((variant) => `
    <li><strong>${escapeHtml(formatAnswer(variant.answer, variant.unit))}</strong><details><summary>비교 상세</summary><small>${escapeHtml(variant.run_count)}회 · ${escapeHtml(variant.normalized_value)}${variant.normalized_unit ? ` · ${escapeHtml(variant.normalized_unit)}` : ''}</small></details></li>`).join('');
  const abstentions = (finding.abstention_variants ?? []).map((variant) => `
    <li><strong>${escapeHtml(abstentionReason(variant.reason))}</strong><small>${escapeHtml(variant.run_count)}회</small><p>${escapeHtml(variant.explanation)}</p><details><summary>실행 상세</summary><small>${escapeHtml(variant.run_ids.join(', '))}</small></details></li>`).join('');
  const sources = finding.evidence.map((item) => `
    <li><strong>${escapeHtml(item.source_title ?? (item.tool_name === 'query_table' ? '구조화 조회 결과' : '자료 발췌'))}</strong>${evidenceContext(finding, item.source_title) ? `<span class="evidence-context">${escapeHtml(evidenceContext(finding, item.source_title))}</span>` : ''}${evidenceExcerpt(finding, item)}<details><summary>감사 정보</summary><small>${escapeHtml(item.tool_name)} · ${escapeHtml(item.source_id)}</small></details></li>`).join('');
  const isPrior = finding.comparison_status === 'NOT_REPRODUCED_AFTER';
  return `
  <details class="finding ${isPrior ? 'finding--prior' : ''}" ${finding.finding_type === 'CONFLICTING_SOURCES' ? 'open' : ''}>
    <summary>
      <span class="num">${String(index + 1).padStart(2, '0')}</span>
      <span class="finding-title"><small>${escapeHtml(typeLabel[finding.finding_type] ?? finding.finding_type)}</small><strong>${escapeHtml(findingTitle(finding))}</strong></span>
      <span class="pill ${isPrior ? 'pill--positive' : 'pill--warn'}">${isPrior ? '수정 후 미재현' : escapeHtml(attributionCopy(finding.attribution_status))}</span>
    </summary>
    <div class="finding-body">
      <div class="finding-copy"><p>${escapeHtml(finding.summary)}</p><span>권고 조치</span><strong>${escapeHtml(finding.recommended_action)}</strong></div>
      <div class="finding-counts"><div><span>영향받은 업무</span><strong>${finding.affected_task_count}</strong><small>고유 업무</small></div><div><span>${finding.finding_type === 'MIXED_OUTCOMES' ? '반복 실행 결과' : isPrior && finding.comparison ? '정리 전·후 반복 결과' : '관측된 실패 실행'}</span><strong class="${isPrior && finding.comparison ? 'finding-counts__transition' : ''}">${finding.finding_type === 'MIXED_OUTCOMES' ? `${finding.answered_run_count} 답변 · ${finding.abstained_run_count} 보류` : isPrior && finding.comparison ? `${finding.comparison.before_abstained_run_count}회 보류 → ${finding.comparison.after_answered_run_count}회 답변` : finding.observed_run_count}</strong><small>${isPrior && finding.comparison ? 'Before → After' : `총 ${finding.observed_run_count}회`}</small></div></div>
      ${finding.finding_type === 'CONFLICTING_SOURCES' && finding.comparison ? `<div class="current-source"><span>정리 후 원문 · 현재 FAQ</span><strong>FAQ_2026.txt</strong><p>${escapeHtml(currentReturnFaqExcerpt)}</p><small>정리 전의 ‘14일’ 문장을 제거했으며, 현재 반품 기간은 정책 문서의 30일을 따릅니다.</small></div>` : ''}
      ${variants ? `<div class="detail-list"><h4>${finding.finding_type === 'MIXED_OUTCOMES' ? '답변된 실행의 값' : '반복 실행에서 관측된 의미값'}</h4><ul>${variants}</ul></div>` : ''}
      ${abstentions ? `<div class="detail-list detail-list--abstention"><h4>보류된 실행의 사유</h4><ul>${abstentions}</ul></div>` : ''}
      ${sources ? `<div class="detail-list"><h4>${evidenceHeading(finding)}</h4><ul>${sources}</ul></div>` : ''}
      <details class="finding-id"><summary>기술 감사 정보</summary>${escapeHtml(finding.finding_type)} · ${escapeHtml(finding.finding_id)} · ${escapeHtml(finding.attribution_status)}</details>
    </div>
  </details>`;
}

const taskRows = tasks.tasks.map((task, index) => {
  const related = activeFindings.filter((finding) => finding.affected_task_ids.includes(task.task_id));
  const status = related.length
    ? related.some((finding) => finding.attribution_status === 'DATA_SIGNAL') ? '진단 신호'
      : related.some((finding) => finding.attribution_status === 'RETRIEVAL_LIMITATION') ? '검색 한계'
        : '불안정 검토'
    : '반복 안정';
  const tone = status === '반복 안정' ? 'positive' : status === '불안정 검토' ? 'neutral' : 'warn';
  const approval = task.status === 'VERIFIED'
    ? task.approval?.approval_scope === 'CUSTOMER' ? '고객 승인' : '통제 데모 승인'
    : '업무 후보';
  return `<tr><td class="mono">${String(index + 1).padStart(2, '0')}</td><td><strong>${escapeHtml(task.question)}</strong><small>${escapeHtml(task.category)} · ${approval}</small></td><td><span class="pill pill--${tone}">${status}</span></td></tr>`;
}).join('');
const verifiedTaskCount = tasks.tasks.filter((task) => task.status === 'VERIFIED').length;

const dimensionLabels = { redundancy: '완전 중복 파일', completeness: '표 데이터 완결성', safety: '개인정보 패턴 탐지', accessibility: '파일 접근성', timeliness: '수정일 최신성' };
const dimensions = Object.entries(readiness.readiness.dimensions).map(([name, value]) => `
  <div class="dimension"><span>${escapeHtml(dimensionLabels[name] ?? name)}</span><strong>${Math.round(Number(value) * 100)}</strong><i><b style="width:${Math.round(Number(value) * 100)}%"></b></i></div>`).join('');

const findingsHtml = [
  ...previousFindings.filter((item) => item.finding_type === 'CONFLICTING_SOURCES'),
  ...activeFindings,
  ...previousFindings.filter((item) => item.finding_type !== 'CONFLICTING_SOURCES'),
].map(findingCard).join('');
const returnFinding = afterFindings.findings.find((item) => item.finding_type === 'CONFLICTING_SOURCES');
const beforeFaqEvidence = returnFinding?.evidence.find((item) => item.source_title?.includes('FAQ_2026'));
const policyEvidence = returnFinding?.evidence.find((item) => !item.source_title?.includes('FAQ_2026'));
const quoteExcerpt = (item) => escapeHtml(item?.excerpt ?? '원문 발췌 없음').replaceAll('14일', '<mark>14일</mark>').replaceAll('30일', '<mark>30일</mark>');
const returnEvidence = `
  ${beforeFaqEvidence ? `<blockquote><span>정리 전 FAQ · Before 실행에서 인용</span><strong>${escapeHtml(beforeFaqEvidence.source_title)}</strong><p>${quoteExcerpt(beforeFaqEvidence)}</p></blockquote>` : ''}
  <blockquote class="claim-quote--current"><span>정리 후 FAQ · 현재 원문</span><strong>FAQ_2026.txt</strong><p>${escapeHtml(currentReturnFaqExcerpt)}</p></blockquote>
  ${policyEvidence ? `<blockquote><span>현행 정책 · 변경 없음</span><strong>${escapeHtml(policyEvidence.source_title ?? '기준 자료')}</strong><p>${quoteExcerpt(policyEvidence)}</p></blockquote>` : ''}`;
const jsonForHtml = JSON.stringify(sourceFacts).replaceAll('<', '\\u003c');

const html = `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="AX Preflight Results Console frozen v4 static review artifact">
  <title>AX Preflight · Results Console · Claude review artifact</title>
  <style>
    :root{font-family:Inter,Pretendard,"Noto Sans KR","Malgun Gothic",system-ui,sans-serif;color:#0a1e3d;background:#fff;font-synthesis:none;--ink:#0a1e3d;--sub:#35506e;--muted:#58748f;--faint:#8fa3bc;--line:#c3d6e8;--soft:#dfeaf4;--surface:#eef4fa;--blue:#0f62fe;--warn:#9a6700;--warn-bg:#fff8e6;--positive:#147d64;--positive-bg:#eaf6f2;--danger:#c43f5b}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;min-width:320px;background:#fff}.mono,code{font-family:"SFMono-Regular",Consolas,monospace;font-variant-numeric:tabular-nums}.shell{display:grid;grid-template-columns:252px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;padding:34px 28px;border-right:1px solid var(--soft);background:#fff}.brand{display:flex;align-items:baseline;gap:9px;color:var(--ink);text-decoration:none}.brand b{font-size:20px}.brand span{font-size:12px;color:var(--sub)}.eyebrow{margin:40px 0 16px;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.16em}.sidebar nav{display:grid;gap:12px}.sidebar nav a{display:grid;grid-template-columns:28px 1fr;color:var(--sub);font-size:12px;text-decoration:none}.sidebar nav a span{color:var(--faint);font-family:Consolas,monospace}.meta{display:grid;gap:12px;margin-top:42px}.meta div{display:grid;grid-template-columns:58px minmax(0,1fr);gap:8px}.meta dt{font-size:10px;color:var(--muted)}.meta dd{margin:0;font-size:11px;overflow-wrap:anywhere}.main{min-width:0;padding:52px clamp(28px,5vw,82px) 80px}.main>*{width:100%;max-width:1120px;margin-inline:auto}.section{padding:64px 0 0;scroll-margin-top:54px}.section:first-child{padding-top:0}.section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;padding-bottom:13px;border-bottom:1px solid var(--line)}.section-index{font:10px Consolas,monospace;color:var(--muted)}h1,h2,h3,p{margin-top:0}.section-head h1,.section-head h2{margin:7px 0 0;font-size:26px;letter-spacing:-.03em}.diagnostic-grid{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid var(--soft)}.metric{padding:24px 20px;border-right:1px solid var(--soft)}.metric:first-child{padding-left:0}.metric:last-child{border:0}.metric span,.metric small{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;margin:6px 0;font-size:35px;font-weight:500;letter-spacing:-.04em}.metric--accent strong{color:var(--ink)}.verdict{margin:28px 0;padding:22px 24px;background:var(--ink);color:#fff}.verdict>span{font:10px Consolas,monospace;color:#93aac8}.verdict div{display:flex;gap:16px;align-items:baseline;margin-top:10px}.verdict strong{font-size:18px}.verdict p{margin:8px 0 0;color:#c8d7ea;font-size:13px}.summary-meta{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;padding:17px 0;border-block:1px solid var(--soft)}.summary-meta span,.summary-meta strong{display:block}.summary-meta span{font-size:10px;color:var(--muted)}.summary-meta strong{margin-top:6px;font-size:12px;overflow-wrap:anywhere}.boundary{margin:28px 0 0;padding:18px 20px;border-left:4px solid var(--warn);background:var(--warn-bg)}.boundary strong{display:block;margin-bottom:7px}.boundary p{margin:0;color:#704d00;font-size:13px;line-height:1.65}.executive{margin-top:36px;padding:28px;border:1px solid var(--ink)}.executive header{display:flex;justify-content:space-between;gap:28px;padding-bottom:17px;border-bottom:2px solid var(--ink)}.executive header small{color:var(--muted);letter-spacing:.08em}.executive h2{margin:6px 0 0;font-size:30px;letter-spacing:-.04em}.executive header div:last-child{text-align:right}.executive header span,.executive header strong{display:block}.executive header span{font-size:10px;color:var(--muted)}.executive-metrics{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid var(--soft)}.executive-metrics article{padding:20px 18px;border-right:1px solid var(--soft)}.executive-metrics article:last-child{border:0}.executive-metrics span,.executive-metrics small,.executive-metrics strong{display:block}.executive-metrics span,.executive-metrics small{font-size:11px;color:var(--muted)}.executive-metrics strong{margin:5px 0;font-size:27px}.comparison{display:flex;align-items:center;justify-content:center;gap:34px;margin:20px 0;padding:16px;background:var(--surface);text-align:center}.comparison div span,.comparison div strong,.comparison div small{display:block}.comparison strong{font-size:25px}.comparison span,.comparison small{font-size:11px;color:var(--muted)}.causal-claim{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:22px;padding:18px 0;border-top:1px solid var(--soft)}.causal-claim>div{padding:12px 16px;background:#f8fbfe}.causal-claim span,.causal-claim strong,.causal-claim small{display:block}.causal-claim strong{font-size:24px}.causal-claim span,.causal-claim small{font-size:11px;color:var(--muted)}.causal-claim>strong{font-size:20px}.executive footer{display:flex;justify-content:space-between;gap:18px;margin-top:18px;padding-top:12px;border-top:2px solid var(--ink);color:var(--muted);font-size:11px}.lede{max-width:760px;margin:16px 0 24px;color:var(--sub);font-size:13px;line-height:1.7}.pill{display:inline-flex;align-items:center;padding:4px 8px;border:1px solid var(--line);font:10px Consolas,monospace;white-space:nowrap}.pill--warn{border-color:#e7c46a;background:var(--warn-bg);color:var(--warn)}.pill--positive{border-color:#9ed8c9;background:var(--positive-bg);color:var(--positive)}.pill--neutral{color:var(--sub)}.finding{border-bottom:1px solid var(--soft)}.finding>summary{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:16px;align-items:center;padding:18px 0;cursor:pointer;list-style:none}.finding>summary::-webkit-details-marker{display:none}.num{font:11px Consolas,monospace;color:var(--faint)}.finding-title small,.finding-title strong{display:block}.finding-title small{margin-bottom:5px;color:var(--muted);font-size:10px}.finding-title strong{font-size:15px}.finding-body{padding:0 0 24px 58px}.finding-copy{padding:16px 18px;background:#f8fbfe}.finding-copy p{color:var(--sub);font-size:13px;line-height:1.65}.finding-copy span,.finding-copy strong{display:block}.finding-copy span{font-size:10px;color:var(--muted)}.finding-copy strong{margin-top:5px;font-size:12px;line-height:1.55}.finding-counts{display:grid;grid-template-columns:repeat(2,1fr);margin-top:14px;border:1px solid var(--soft)}.finding-counts div{padding:14px 16px;border-right:1px solid var(--soft)}.finding-counts div:last-child{border:0}.finding-counts span,.finding-counts strong,.finding-counts small{display:block}.finding-counts span,.finding-counts small{font-size:10px;color:var(--muted)}.finding-counts strong{margin:5px 0;font-size:22px}.current-source{margin-top:16px;padding:14px 16px;border-left:3px solid var(--blue);background:var(--surface)}.current-source span,.current-source strong,.current-source small{display:block}.current-source span,.current-source small{color:var(--muted);font-size:10px}.current-source strong{margin-top:5px;font-size:12px}.current-source p{margin:9px 0 6px;color:var(--ink);font-size:12px;line-height:1.6}.detail-list{margin-top:16px}.detail-list h4{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.06em}.detail-list ul{display:grid;gap:7px;margin:0;padding:0;list-style:none}.detail-list li{padding:10px 12px;border-left:2px solid var(--line);background:#fbfdff}.detail-list--abstention li{border-left-color:var(--warn)}.detail-list li strong,.detail-list li small,.detail-list .evidence-context{display:block}.detail-list li strong{font-size:12px}.detail-list li small,.detail-list .evidence-context{margin-top:4px;color:var(--muted);font:10px Consolas,monospace;overflow-wrap:anywhere}.detail-list .evidence-context{color:var(--warn)}.structured-table-wrap{width:100%;margin:10px 0;overflow-x:auto}.structured-table{width:100%;border-collapse:collapse;color:var(--sub);font:10px Consolas,monospace}.structured-table th,.structured-table td{padding:6px 7px;border:1px solid var(--soft);text-align:left;white-space:nowrap}.structured-table th{color:var(--muted);background:var(--surface);font-weight:500}.finding-id{margin-top:14px;color:var(--faint);font:10px Consolas,monospace}.finding--prior{opacity:.78}.dimension-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-top:24px}.dimension{padding:16px;border:1px solid var(--soft)}.dimension span,.dimension strong{display:block}.dimension span{font-size:10px;color:var(--muted);text-transform:capitalize}.dimension strong{margin:8px 0;font-size:25px}.dimension i{display:block;height:3px;background:var(--soft)}.dimension b{display:block;height:100%;background:var(--blue)}.task-table{width:100%;border-collapse:collapse}.task-table td{padding:13px 8px;border-bottom:1px solid var(--soft);vertical-align:middle}.task-table td:first-child{width:42px;color:var(--faint);font-size:10px}.task-table td:last-child{width:125px;text-align:right}.task-table strong,.task-table small{display:block}.task-table strong{font-size:13px}.task-table small{margin-top:4px;color:var(--muted);font-size:10px}.evidence-card{background:var(--ink);color:#fff;padding:26px}.evidence-top{display:flex;justify-content:space-between;gap:20px;align-items:start}.evidence-top small,.evidence-top strong{display:block}.evidence-top small{color:#93aac8;font:10px Consolas,monospace}.evidence-top strong{margin-top:6px;font-size:22px}.evidence-answer{margin-top:22px;padding:16px;border:1px solid #35506e}.evidence-answer span,.evidence-answer strong,.evidence-answer small{display:block}.evidence-answer span,.evidence-answer small{color:#a9bdd6;font-size:11px}.evidence-answer strong{margin:7px 0;font-size:26px}.source-row{display:grid;grid-template-columns:100px 1fr;gap:12px;margin-top:18px;font-size:11px}.source-row span{color:#93aac8}.source-row code{color:#7cc0f5;overflow-wrap:anywhere}.limitations{margin-top:22px;padding-top:18px;border-top:1px solid #35506e}.limitations h3{font-size:11px;text-transform:uppercase;letter-spacing:.08em}.limitations ul{margin:0;padding-left:18px;color:#c8d7ea;font-size:11px;line-height:1.6}.static-note{margin-top:22px;padding:14px 16px;border:1px dashed var(--line);color:var(--muted);font-size:12px}.page-footer{padding-top:60px;color:var(--faint);font:10px Consolas,monospace;text-align:center;letter-spacing:.08em}@media(max-width:860px){.shell{display:block}.sidebar{position:relative;top:auto;width:auto;height:auto;padding:22px 24px;border-right:0;border-bottom:1px solid var(--soft)}.sidebar nav{grid-template-columns:repeat(4,minmax(0,1fr))}.meta{display:none}.main{padding:36px 24px 64px}.diagnostic-grid,.executive-metrics{grid-template-columns:1fr}.metric,.executive-metrics article{padding:17px 0;border-right:0;border-bottom:1px solid var(--soft)}.summary-meta{grid-template-columns:repeat(2,1fr)}.dimension-grid{grid-template-columns:repeat(2,1fr)}.finding>summary{grid-template-columns:34px minmax(0,1fr)}.finding>summary .pill{grid-column:2;justify-self:start}.finding-body{padding-left:50px}.executive header,.executive footer{display:block}.executive header div:last-child{margin-top:16px;text-align:left}.causal-claim{grid-template-columns:1fr;text-align:center}}@media(max-width:520px){.sidebar nav{grid-template-columns:repeat(2,minmax(0,1fr))}.main{padding-inline:18px}.summary-meta,.dimension-grid{grid-template-columns:1fr}.executive{padding:20px}.comparison{gap:16px}.finding-body{padding-left:0}.finding-counts{grid-template-columns:1fr}.finding-counts div{border-right:0;border-bottom:1px solid var(--soft)}.task-table td:nth-child(1){display:none}}@media print{.sidebar{display:none}.shell{display:block}.main{padding:0}.section{break-inside:avoid}.finding:not([open]) .finding-body{display:none}}
    .hero-proof{display:grid;grid-template-columns:.9fr 1.1fr;margin-top:24px;border-block:2px solid var(--ink)}.hero-proof>div{padding:26px 24px 26px 0}.hero-proof>div+div{padding-left:30px;border-left:1px solid var(--soft)}.hero-proof span,.hero-proof small{display:block;color:var(--muted);font-size:11px}.hero-proof strong{display:block;margin:8px 0;font-size:52px;font-weight:500;letter-spacing:-.06em}.hero-proof strong small{display:inline;margin-left:5px;font-size:11px;letter-spacing:0}.hero-proof p{margin:10px 0 0;color:var(--sub);font-size:13px;line-height:1.6}.hero-proof__flow{display:flex;align-items:center;gap:15px}.hero-proof__flow i{color:var(--blue);font-size:22px;font-style:normal}.claim-quotes{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:18px}.claim-quotes blockquote{margin:0;padding:14px 16px;border-left:3px solid var(--warn);background:var(--warn-bg)}.claim-quotes .claim-quote--current{border-left-color:var(--blue);background:var(--surface)}.claim-quotes span,.claim-quotes strong{display:block}.claim-quotes span{color:var(--muted);font-size:10px}.claim-quotes strong{margin-top:5px;font-size:11px}.claim-quotes p{margin:7px 0 0;font-size:12px;line-height:1.6}.claim-quotes mark,.detail-list mark{padding:1px 3px;background:#ffe69a;color:var(--ink);font-weight:700}.method-note{margin-top:18px;color:var(--muted);font-size:11px}.method-note summary{cursor:pointer}.method-note p{margin:8px 0 0;line-height:1.6}.detail-list li p{margin:7px 0;color:var(--sub);font-size:12px;line-height:1.55}.detail-list details summary,.finding-id summary{cursor:pointer;color:var(--muted);font:400 10px/1.4 Consolas,monospace}.finding-counts .finding-counts__transition{font-size:15px;line-height:1.35}.agent-explanation-label{margin-top:12px;color:#93aac8;font:10px Consolas,monospace;letter-spacing:.04em}.audit-only{margin-top:16px;padding-top:12px;border-top:1px solid #35506e;color:#a9bdd6;font-size:10px}.audit-only summary{cursor:pointer}@media(max-width:860px){.hero-proof,.claim-quotes{grid-template-columns:1fr}.hero-proof>div+div{padding-left:0;border-top:1px solid var(--soft);border-left:0}}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar" aria-label="리포트 탐색">
      <a class="brand" href="#summary"><b>AX Preflight</b><span>Results Console</span></a>
      <div class="eyebrow">화면 목차</div>
      <nav>
        <a href="#summary"><span>01</span>요약</a><a href="#executive"><span>02</span>관리자 1페이지</a><a href="#findings"><span>03</span>진단 신호</a><a href="#readiness"><span>04</span>정적 준비도</a><a href="#tasks"><span>05</span>업무 검증</a><a href="#evidence"><span>06</span>근거 검사 예시</a>
      </nav>
      <dl class="meta"><div><dt>데이터셋</dt><dd>${escapeHtml(readiness.dataset_name)}</dd></div><div><dt>기준일</dt><dd>${escapeHtml(readiness.readiness.as_of_date)}</dd></div><div><dt>비교</dt><dd>의미 비교 v2</dd></div><div><dt>실행</dt><dd>동결 v4</dd></div></dl>
    </aside>
    <main class="main">
      <section class="section" id="summary">
        <header class="section-head"><div><div class="section-index">01 / 업무 진단</div><h1>AI 업무 진단</h1></div><span class="pill pill--warn">정리 후 · 동결 v4</span></header>
        <div class="hero-proof"><div><span>정적 Data Readiness</span><strong>${score}<small>/ 100</small></strong><p>파일 구조 점검은 통과했지만 실제 업무 성공을 보증하지 않습니다.</p></div><div><span>반품 기간 업무</span><div class="hero-proof__flow"><strong>0 / 3</strong><i>→</i><strong>3 / 3</strong></div><p>14일·30일 충돌을 지목하고 정리한 뒤 세 번 모두 30일로 답했습니다.</p></div></div>
        <div class="diagnostic-grid"><div class="metric"><span>반복 안정 처리</span><strong>${after.processable_task_count} / ${after.task_count}</strong><small>3회 모두 같은 의미값으로 답변</small></div><div class="metric"><span>일관된 보류</span><strong>${after.blocked_task_count} / ${after.task_count}</strong><small>3회 모두 보류된 업무</small></div><div class="metric metric--accent"><span>불안정·검토 필요</span><strong>${after.inconclusive_task_count} / ${after.task_count}</strong><small>답변·보류 혼재</small></div></div>
        <div class="summary-meta"><div><span>데이터셋</span><strong>${escapeHtml(readiness.dataset_name)}</strong></div><div><span>비교 규칙</span><strong class="mono">의미 비교 v2</strong></div><div><span>열린 진단 신호</span><strong class="mono">${activeFindings.length}건</strong></div><div><span>관측 실행</span><strong class="mono">${after.observed_run_count}회</strong></div></div>
      </section>

      <section class="executive" id="executive">
        <header><div><small>AX Preflight · AI 업무 도입 전 점검</small><h2>어디를 먼저 검토하면 업무가 풀리는가</h2></div><div><span>데이터셋</span><strong>${escapeHtml(readiness.dataset_name)}</strong></div></header>
        <div class="executive-metrics"><article><span>반복 안정 처리</span><strong>${after.processable_task_count} / ${after.task_count}</strong><small>고유 업무 기준</small></article><article><span>일관된 보류</span><strong>${after.blocked_task_count}</strong><small>3회 모두 보류</small></article><article><span>불안정·검토 필요</span><strong>${after.inconclusive_task_count}</strong><small>답변·보류 혼재</small></article></div>
        <h3>변경 파일과 직접 연결되는 검증된 사례</h3>
        <div class="causal-claim"><div><span>정리 전 · 반품 기간</span><strong>0 / 3</strong><small>충돌 감지 후 보류</small></div><strong aria-hidden="true">→</strong><div><span>정리 후 · 반품 기간</span><strong>3 / 3</strong><small>30일 · 근거 직접 일치</small></div></div>
        <div class="claim-quotes">${returnEvidence}</div>
        <details class="method-note"><summary>비교 규칙 변경과 해석 범위</summary><p>같은 frozen run을 재실행하지 않고 일반 의미 비교 규칙을 적용했습니다. 기존 v1은 Before ${beforeFindings.legacy_diagnostics?.processable_task_count ?? 4}/10, After ${afterFindings.legacy_diagnostics?.processable_task_count ?? 2}/10 처리 가능으로 집계했으나, 표현·단위 차이와 1회 보류를 과도하게 불일치·보류로 셌습니다. v2의 Before ${before.processable_task_count}/10 → After ${after.processable_task_count}/10은 기술적 재분류이며, 변경 파일과 직접 연결되는 인과 주장은 반품 기간 업무에만 한정합니다.</p></details>
        <footer><span>${after.observed_run_count}회 실행 · 의미 비교 v2</span><span>전체 품질 향상이나 일반 정확도를 뜻하지 않습니다.</span></footer>
      </section>

      <section class="section" id="findings">
        <header class="section-head"><div><div class="section-index">03 / 진단 신호</div><h2>발견된 진단 신호</h2></div><span class="pill pill--warn">${activeFindings.length} 열림 · ${previousFindings.length} 수정 후 미재현</span></header>
        <p class="lede">충돌과 반복 보류는 데이터 신호로 구분합니다. 주문 업무의 답변·보류 혼재 2건은 원장이 없어서가 아니라 검색 결과 상위 목록에 따라 원장 노출이 달라지는 제품 한계로 확인했습니다.</p>
        ${findingsHtml}
      </section>

      <section class="section" id="readiness">
        <header class="section-head"><div><div class="section-index">04 / 정적 준비도</div><h2>정적 Data Readiness</h2></div><span class="pill">점수 항목 5</span></header>
        <p class="lede">파싱 가능성·표 누락·완전 중복·수정일·개인정보 marker 패턴을 점검한 보조 지표입니다. 실제 업무 처리 가능성과 별도입니다.</p>
        <div class="dimension-grid">${dimensions}</div>
      </section>

      <section class="section" id="tasks">
        <header class="section-head"><div><div class="section-index">05 / 업무 검증</div><h2>승인된 업무와 후보</h2></div><span class="pill">검증 ${verifiedTaskCount} · 후보 ${tasks.tasks.length - verifiedTaskCount}</span></header>
        <p class="lede">상태는 frozen v4의 3회 반복 결과를 정적 검토용으로 요약한 것입니다. 불안정 검토는 곧 문서 결함을 뜻하지 않습니다.</p>
        <table class="task-table"><tbody>${taskRows}</tbody></table>
      </section>

      <section class="section" id="evidence">
        <header class="section-head"><div><div class="section-index">06 / 근거 검사</div><h2>근거 검사 대표 예시</h2></div><span class="pill pill--positive">근거 직접 일치</span></header>
        <p class="lede">실제 Console에서는 개별 run을 조회했을 때 표시됩니다. 여기서는 심사 스토리와 연결되는 반품 기간 After r1을 대표 예시로 함께 배치했습니다.</p>
        <div class="evidence-card"><div class="evidence-top"><div><small>대표 실행 예시</small><strong>같은 실행의 인용 근거와 값이 직접 일치</strong></div><span class="pill pill--positive">근거 직접 일치</span></div><div class="evidence-answer"><span>승인된 답</span><strong>${escapeHtml(formatAnswer(payload.answer, payload.unit))}</strong><span class="agent-explanation-label">에이전트 설명 · 검증 대상 아님</span><small>${escapeHtml(payload.explanation)}</small></div><div class="limitations"><h3>검사 범위와 한계</h3><ul>${exampleEvidence.limitations.map((item) => `<li>${escapeHtml(limitationCopy[item] ?? item)}</li>`).join('')}<li>근거 직접 일치는 일반 정답 보증이 아니며, 확인 불가는 오답 판정이 아닙니다.</li></ul></div><details class="audit-only"><summary>기술 감사 정보</summary><div class="source-row"><span>인용·일치 출처</span><code>${escapeHtml(exampleEvidence.matched_source_ids.join(', '))}</code></div><div class="source-row"><span>결과 SHA-256</span><code>${escapeHtml(exampleEvidence.delivery_sha256)}</code></div><div class="source-row"><span>실행 ID</span><code>${escapeHtml(exampleRun.run_id)}</code></div></details></div>
        <div class="static-note">조회·실행 컨트롤은 이 검토본에서 제외했습니다. 실제 앱은 read-only frozen 결과 조회와 run 선택을 지원하며, 이 파일은 정보 구조·문구·시각 우선순위 검토에만 사용합니다.</div>
      </section>
      <footer class="page-footer">AX Preflight · Results Console · 동결 v4 · 의미 비교 v2</footer>
    </main>
  </div>
  <script id="ax-source-facts" type="application/json">${jsonForHtml}</script>
</body>
</html>`;

const reviewPrompt = `# Claude에게 그대로 전달할 재검토 요청\n\n첨부한 \`AX_RESULTS_CONSOLE_REVIEW.html\`은 같은 frozen v4 run 60개에 의미 비교 규칙 v2를 적용한 독립형 정적 검토본입니다. run을 재실행하거나 원본 v4를 수정하지 않았습니다. 파일 하단과 \`SOURCE_FACTS.json\`에 화면 원본 사실이 포함되어 있습니다.\n\n이번 수정에서 확인할 사항:\n\n1. 첫 화면에서 \"정적 Readiness 100/100인데 반품 업무는 0/3 실패\"와 \"충돌 정리 후 3/3 답변\"이 30초 안에 이해되는가?\n2. 전체 업무 분류가 반복 안정 6/10 + 일관된 보류 2/10 + 불안정 2/10 = 10으로 명확한가?\n3. 충돌 Finding이 맨 먼저 나오고, 14일과 30일 원문이 즉시 비교되는가?\n4. 3회 중 일부만 보류한 업무가 자료 공백이 아니라 실행 결과 혼재·원인 미확인으로 읽히는가?\n5. 영문 enum, source ID, SHA-256이 관리자 본문이 아니라 접힌 감사 정보에 머무는가?\n6. \"30일 일\" 같은 단위 중복이나 영어 라벨 회귀가 남아 있지 않은가?\n7. 관리자, 현업 담당자, 기술 심사위원 각각에게 정보 계층이 맞는가?\n\n반드시 지킬 사실 범위:\n\n- 의미 비교 v2 결과는 Before 5/10 안정·3/10 일관 보류·2/10 혼재, After 6/10 안정·2/10 일관 보류·2/10 혼재다.\n- 기존 비교 v1의 Before 4/10, After 2/10도 감사 가능하게 남겨둔다. v1은 표현·단위 차이와 한 번 이상의 보류를 과도하게 셌다.\n- v2의 5/10→6/10은 같은 run의 기술적 재분류이며, 전체 인과 개선 주장이 아니다.\n- 데이터 수정과 직접 연결되는 방어 가능한 개선 주장은 반품 기간 업무의 0/3→3/3뿐이다.\n- 혼재 결과는 데이터 원인이 확인된 결함이 아니다.\n- DIRECT_MATCH는 같은 run의 구조화 근거와 값의 좁은 일치이며 일반 정답 보증이 아니다. UNCONFIRMED는 오답을 뜻하지 않는다.\n- Evidence Checker 전체 관측은 60회 중 35건 DIRECT_MATCH이고, 수동 감사 표본은 6/6 PASS일 뿐 전체를 보증하지 않는다.\n\n응답 형식:\n\n- 한 줄 총평\n- 남은 치명적 오해 위험(P0), 제출 전 수정(P1), 이후 개선(P2)\n- 각 항목: 문제 위치 / 이유 / 최소 수정안 / 권장 문구\n- 심사위원 질문 5개와 모범 답변\n- 마지막으로 지금 상태로 제출 가능 / 조건부 가능 / 보류 중 하나\n\n화면에 없는 기능이나 성능을 추정하지 말고, 하루 안에 가능한 수정만 제안해주세요.\n`;

const latestReviewAddendum = `\n## 이번 피드백 회귀 확인\n\n- "감사 정보"와 "기술 감사 정보"가 한 줄의 정상적인 접기 제목으로 보이는가?\n- FAQ의 14일은 정리 전 Before 인용, 현재 FAQ는 정리 후 원문으로 분명히 구분되는가?\n- 노란 하이라이트가 반품 충돌에만 있고 거래처 결제조건 같은 무관한 30일에는 없는가?\n- 이번 달 주문금액이 답변 2회 4,980,700원·보류 1회로 보이며, 기준월과 조회 경로 권고가 구체적인가?\n- query_table 응답이 원시 JSON이 아니라 제목이 있는 작은 표로 보이는가?\n- 예외 승인 Finding이 할인 승인 규정과 일반 예외 절차의 공백을 구분하는가?\n- 불안정 2/10이 파란 강조 없이 중립적으로 보이는가?\n`;

const currentReviewPrompt = reviewPrompt
  .replace(
    '3회 중 일부만 보류한 업무가 자료 공백이 아니라 실행 결과 혼재·원인 미확인으로 읽히는가?',
    '두 주문 업무의 혼재가 자료 공백이나 파일명 불일치가 아니라 확인된 검색 상위-k 한계로 읽히는가?',
  )
  .replace(
    '"30일 일" 같은 단위 중복이나 영어 라벨 회귀가 남아 있지 않은가?',
    '"30일 일", "2026-09-21 date" 같은 단위 중복이나 원시 보류 enum이 남아 있지 않은가?',
  )
  .replace(
    '- 혼재 결과는 데이터 원인이 확인된 결함이 아니다.',
    '- 주문_원장_2026.xlsx와 Orders 테이블은 정상 파싱·인덱싱됐다. 정책 기준명으로 검색해도 BM25 4위로 밀릴 수 있어, 실행별 검색어와 top-k 경로에 따라 원장 발견 여부가 달라진 것이 주문 업무 혼재의 확인된 제품 한계다.',
  );

const currentReviewAddendum = `${latestReviewAddendum}
- 주문 업무 2건이 "검색 경로 한계 확인"으로 표시되고 같은 원인·조치로 설명되는가?
- 대표 근거 카드의 모델 서술이 "에이전트 설명 · 검증 대상 아님"으로 checker 판정과 분리되는가?
- 날짜 답에 \`date\` 단위가 붙지 않고 보류 사유 enum이 한국어로 보이는가?
- 해결된 반품 충돌이 "정리 전 3회 보류 → 정리 후 3회 답변"으로 읽히는가?
`;

const readme = `# Claude final review packet\n\n클로드에 아래 두 파일을 함께 첨부하세요.\n\n1. \`AX_RESULTS_CONSOLE_REVIEW.html\` — 외부 의존성이 없는 정적 대표 화면\n2. \`CLAUDE_REVIEW_PROMPT.md\` — 그대로 복사해서 보낼 검토 요청\n\n\`SOURCE_FACTS.json\`은 클로드가 숫자와 표현 범위를 교차 확인하도록 함께 첨부해도 됩니다. HTML 안에도 같은 JSON이 포함되어 있습니다.\n\n이 패킷은 frozen v4 산출물을 수정하지 않습니다. 제품 동작이나 API 계약 검증용이 아니라, 5분 심사 관점의 정보 구조·문구·시각 우선순위 검토용입니다.\n`;

await mkdir(outputDir, { recursive: true });
await Promise.all([
  writeFile(resolve(outputDir, 'AX_RESULTS_CONSOLE_REVIEW.html'), html, 'utf8'),
  writeFile(resolve(outputDir, 'CLAUDE_REVIEW_PROMPT.md'), `${currentReviewPrompt}${currentReviewAddendum}`, 'utf8'),
  writeFile(resolve(outputDir, 'SOURCE_FACTS.json'), `${JSON.stringify(sourceFacts, null, 2)}\n`, 'utf8'),
  writeFile(resolve(outputDir, 'README.md'), readme, 'utf8'),
]);

console.log(`Wrote Claude review packet to ${outputDir}`);
