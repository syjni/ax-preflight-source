import { useState } from 'react';
import type { ReadinessResponse } from '../generated/api';
import { readinessRows } from '../viewModel';
import { Status } from './Status';

const descriptionCopy = {
  redundancy: '바이트가 같은 파일 탐지',
  completeness: '평가 대상 표의 누락 셀 점검',
  safety: '등록된 개인정보 탐지 패턴 기반 점검',
  accessibility: '파싱 및 OCR 필요 여부 점검',
  timeliness: '파일 수정 시각 기준 점검',
};

export function ReadinessTable({ data, loading, error }: { data: ReadinessResponse | null; loading: boolean; error: string }) {
  const [open, setOpen] = useState<string | null>('redundancy');
  return <section className="report-section" id="readiness" aria-labelledby="readiness-title">
    <header className="section-heading">
      <div><div className="section-index">04 / 정적 준비도</div><h2 id="readiness-title">정적 Data Readiness</h2></div>
      {data && <Status tone="blue">점수 항목 5</Status>}
    </header>
    <p className="section-lede">실제 업무 진단과 분리된 보조 지표입니다. 각 점수는 Readiness v1 응답을 그대로 표시합니다.</p>
    {loading && <div className="state-message">Readiness 응답을 불러오는 중…</div>}
    {error && <div className="notice notice--danger" role="alert">{error}</div>}
    {data && <div className="readiness-table">
      <div className="table-head" aria-hidden="true"><span>항목</span><span>점수</span><span>상태</span></div>
      {readinessRows(data).map((row) => {
        const expanded = open === row.key;
        return <div className="readiness-row" key={row.key}>
          <button className="readiness-trigger" aria-expanded={expanded} aria-controls={`readiness-detail-${row.key}`} onClick={() => setOpen(expanded ? null : row.key)}>
            <span className="row-index mono">{row.index}</span>
            <span className="row-name"><strong>{row.name}</strong><small>{descriptionCopy[row.key]}</small></span>
            <span className="row-score mono">{Math.round(row.score)}</span>
            <span className="row-bar" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, row.score))}%` }} /></span>
            <span className="row-toggle">{expanded ? '접기 −' : '펼치기 +'}</span>
          </button>
          {expanded && <div className="readiness-detail" id={`readiness-detail-${row.key}`}>
            <div className="detail-group"><h3>집계</h3><dl>{row.counts.map((item) => <div key={item.label}><dt>{item.label}</dt><dd className="mono">{item.value}</dd></div>)}</dl></div>
            <div className="detail-group"><h3>점검 표시</h3><dl>{row.flags.map((item) => <div key={item.label}><dt>{item.label}</dt><dd className="mono">{item.value}</dd></div>)}</dl></div>
            <div className="detail-group detail-group--wide">
              <h3>파일</h3>
              <p>API에서 이 점수 차원의 개별 파일 목록과 observation 연결 정보를 제공하지 않습니다.</p>
            </div>
          </div>}
        </div>;
      })}
    </div>}
    {data && <div className="unscored-observations">
      <div className="unscored-heading"><div><span className="mono">점수 미반영</span><h3>점수 외 관찰</h3></div><Status tone="warning">{data.unscored_observations.length}</Status></div>
      <p>아래 항목은 readiness 점수에 포함되지 않으며, API가 특정 점수 차원과의 연결을 제공하지 않아 관련성을 추정하지 않습니다.</p>
      {data.unscored_observations.length === 0 ? <div className="state-message">표시할 점수 외 관찰이 없습니다.</div> : <div className="observation-list">
        {data.unscored_observations.map((item, index) => <article key={`${item.code}-${index}`}>
          <div><Status tone={item.severity === 'error' ? 'danger' : item.severity === 'warning' ? 'warning' : 'neutral'}>{item.code}</Status><span>{item.message}</span></div>
          <p className="mono">File IDs · {(item.file_ids ?? []).join(', ') || '제공 없음'}</p>
        </article>)}
      </div>}
    </div>}
  </section>;
}
