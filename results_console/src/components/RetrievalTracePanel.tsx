import type { RetrievalStep, RetrievalTrace } from '../generated/api';
import { Status } from './Status';

const toolCopy: Record<RetrievalStep['tool_name'], { title: string; count: (value: number) => string }> = {
  search_documents: { title: '문서 후보 검색', count: (value) => `후보 ${value}개` },
  read_document: { title: '원문 확인', count: (value) => `문서 ${value}개` },
  lookup_value: { title: '값 조회', count: (value) => `결과 ${value}개` },
  query_table: { title: '표 조회', count: (value) => `행 ${value}개` },
};

const limitationCopy: Record<string, string> = {
  'Only successful structured data-tool responses stored for this run are shown.': '이 실행에 저장된 성공한 구조화 데이터 도구 응답만 표시합니다.',
  'Tool request arguments are not stored, so the original search query and filters are not reconstructed.': '도구 요청 인자는 저장되지 않아 원래 검색어와 필터를 복원하지 않습니다.',
  'Successful and failed data-tool attempts stored for this run are shown.': '이 실행에 저장된 성공·실패 데이터 도구 시도를 모두 표시합니다.',
  'Request summaries exclude raw query text and filter values.': '요청 요약은 원문 검색어와 필터 값을 저장하거나 표시하지 않습니다.',
  'Candidate presence or rank is not an accuracy judgment.': '검색 후보 포함 여부와 순위만으로 정확성을 판정하지 않습니다.',
};

function requestSummary(step: RetrievalStep): string[] {
  const summary = step.request_summary;
  if (!summary) return [];
  const items: string[] = [];
  if (summary.query_character_count != null) items.push(`검색어 ${summary.query_character_count}자`);
  if (summary.result_limit != null) items.push(`결과 상한 ${summary.result_limit}`);
  if (summary.source_ids.length) items.push(`자료 ${summary.source_ids.join(', ')}`);
  if (summary.filter_fields.length) items.push(`필터 필드 ${summary.filter_fields.join(', ')}`);
  if (!items.length && summary.parameter_names.length) items.push(`인자 ${summary.parameter_names.join(', ')}`);
  return items;
}

export function RetrievalTracePanel({ data, loading, missing, error }: {
  data: RetrievalTrace | null;
  loading: boolean;
  missing: boolean;
  error: string;
}) {
  return <div className="retrieval-trace" aria-labelledby="retrieval-trace-title">
    <div className="retrieval-trace__heading">
      <div><span>RUN-BOUND TRACE</span><h3 id="retrieval-trace-title">검색·근거 경로</h3></div>
      {data && <Status tone={data.steps.length ? 'positive' : 'neutral'}>{data.steps.length}단계</Status>}
    </div>
    <p>같은 실행에서 기록된 검색 후보와 실제 읽은 자료를 순서대로 보여 줍니다. 최종 답변이 인용한 자료만 별도로 표시합니다.</p>
    {loading && <div className="state-message">검색·근거 경로를 불러오는 중…</div>}
    {missing && <div className="notice"><strong>검색·근거 경로 없음</strong><span>기록이 없다는 사실을 검색 실패나 오답으로 바꾸지 않습니다.</span></div>}
    {error && <div className="notice notice--danger" role="alert">{error}</div>}
    {!data && !loading && !missing && !error && <div className="state-message">대표 흐름 또는 기존 실행을 열면 검색·근거 경로가 표시됩니다.</div>}
    {data && data.steps.length === 0 && <div className="state-message">이 실행에는 저장된 데이터 도구 응답이 없습니다.</div>}
    {data && data.steps.length > 0 && <ol className="retrieval-trace__steps">
      {data.steps.map((step) => {
        const copy = toolCopy[step.tool_name];
        const failed = step.status === 'ERROR';
        const request = requestSummary(step);
        return <li key={step.sequence}>
          <div className="retrieval-trace__step-head">
            <span className="mono">{String(step.sequence).padStart(2, '0')}</span>
            <div><strong>{copy.title}</strong><small className="mono">{step.tool_name}</small></div>
            {failed ? <Status tone="danger">호출 실패</Status> : <em>{copy.count(step.result_count)}{step.truncated ? ' · 일부만 반환' : ''}</em>}
          </div>
          {request.length > 0 && <p className="retrieval-trace__request">요청 요약 · {request.join(' · ')}</p>}
          {failed && <div className="retrieval-trace__failure" role="status"><strong>{step.error_code}</strong><span>실패 시도를 숨기지 않고 후속 성공 단계와 별도로 보존했습니다.</span></div>}
          {!failed && step.candidates.length > 0 && <div className="retrieval-trace__candidates">
            {step.candidates.map((candidate) => <article key={`${step.sequence}-${candidate.rank}-${candidate.source_ids.join('-')}`} className={candidate.cited ? 'is-cited' : ''}>
              <span className="mono">#{candidate.rank}</span>
              <strong>{candidate.title}</strong>
              {candidate.cited ? <Status tone="positive">최종 인용</Status> : <span className="retrieval-trace__candidate-state">후보</span>}
              <details><summary>자료 식별자</summary><code>{candidate.source_ids.join(', ') || '없음'}</code></details>
            </article>)}
          </div>}
          {!failed && step.candidates.length === 0 && <p className="retrieval-trace__empty">표시할 자료 식별자가 없습니다.</p>}
        </li>;
      })}
    </ol>}
    {data && <details className="retrieval-trace__limits"><summary>경로 해석 범위</summary><ul>{data.limitations.map((item) => <li key={item}>{limitationCopy[item] ?? item}</li>)}</ul></details>}
  </div>;
}
