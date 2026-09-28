export type BenchmarkDemoReport = {
  mode: 'benchmark';
  title: string;
  description: string;
  runDate: string;
  before: { passed: number; total: number; abstained: number; refused: number; wrong: number };
  ceiling: { passed: number; total: number; abstained: number; refused: number; wrong: number };
  groups: Array<{ group: string; before: string; after: string; note: string }>;
  interpretation: string;
  limitation: string;
};

function BenchmarkMetric({ name, value, accent }: { name: string; value: BenchmarkDemoReport['before']; accent?: boolean }) {
  const rate = value.total ? value.passed / value.total * 100 : 0;
  return <div className={`benchmark-metric ${accent ? 'is-accent' : ''}`}>
    <span>{name}</span><strong>{value.passed}<small>/ {value.total}</small></strong>
    <div><i style={{ width: `${rate}%` }} /></div>
    <p className="mono">{rate.toFixed(1)}% · abstain {value.abstained} · refuse {value.refused} · wrong {value.wrong}</p>
  </div>;
}

export function BenchmarkTab({ report }: { report: BenchmarkDemoReport }) {
  return <main className="report-main benchmark-page">
    <div className="benchmark-banner"><span>CONTROLLED</span>통제된 DEV 실험 fixture · 실제 운영 결과 아님</div>
    <section className="report-section benchmark-section">
      <header className="section-heading"><div><div className="section-index">01 / Benchmark</div><h1>{report.title}</h1></div></header>
      <p className="section-lede">{report.description} <span className="mono">{report.runDate}</span></p>
      <div className="benchmark-metrics"><BenchmarkMetric name="Before" value={report.before} /><BenchmarkMetric name="Ceiling" value={report.ceiling} accent /></div>
      <div className="benchmark-table"><div><span>과제 묶음</span><span>Before</span><span>Ceiling</span><span>주된 차이</span></div>{report.groups.map((item) => <div key={item.group}><strong>{item.group}</strong><span className="mono">{item.before}</span><span className="mono accent-text">{item.after}</span><span>{item.note}</span></div>)}</div>
      <div className="benchmark-notes"><div><span>해석</span><p>{report.interpretation}</p></div><div><span>한계</span><p>{report.limitation}</p></div></div>
    </section>
  </main>;
}

