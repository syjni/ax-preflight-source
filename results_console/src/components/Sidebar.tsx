type SidebarProps = {
  activeTab: 'report' | 'benchmark';
  benchmarkAvailable: boolean;
  onTabChange: (tab: 'report' | 'benchmark') => void;
  dataset: string;
  datasetName?: string;
  asOfDate?: string;
  runId?: string;
};

const contents = [
  ['01', '요약', 'summary'],
  ['02', '관리자 1페이지', 'executive-report'],
  ['03', '진단 신호', 'findings'],
  ['04', '정적 준비도', 'readiness'],
  ['05', '업무 검증', 'tasks'],
  ['06', '근거 검사', 'evidence'],
  ['07', '조회와 실행', 'control'],
  ['08', '반복 실행', 'batch'],
] as const;

export function Sidebar({ activeTab, benchmarkAvailable, onTabChange, dataset, datasetName, asOfDate, runId }: SidebarProps) {
  return <aside className="sidebar" aria-label="리포트 탐색">
    <a className="brand" href="#console" aria-label="AX Preflight Results Console 처음으로">
      <span className="brand-symbol">AX Preflight</span>
      <span className="brand-name">Results Console</span>
    </a>

    <nav className="report-tabs" aria-label="리포트 보기">
      <button className={activeTab === 'report' ? 'is-active' : ''} onClick={() => onTabChange('report')}>진단 리포트</button>
      {benchmarkAvailable && <button className={activeTab === 'benchmark' ? 'is-active' : ''} onClick={() => onTabChange('benchmark')}>실험 결과</button>}
    </nav>

    {activeTab === 'report' && <>
      <div className="sidebar-group">
        <div className="sidebar-label">화면 목차</div>
        <nav className="contents-nav" aria-label="리포트 목차">
          {contents.map(([index, label, id]) => <a key={id} href={`#${id}`}><span>{index}</span>{label}</a>)}
        </nav>
      </div>

      <dl className="report-meta">
        <div><dt>데이터셋</dt><dd>{datasetName ?? dataset}</dd></div>
        <div><dt>기준일</dt><dd>{asOfDate ?? '—'}</dd></div>
      </dl>
      <details className="sidebar-audit"><summary>기술 감사 정보</summary><dl>
        <div><dt>프로필</dt><dd className="mono">{dataset}</dd></div>
        <div><dt>실행 ID</dt><dd className="mono">{runId ?? '—'}</dd></div>
      </dl></details>
    </>}
  </aside>;
}
