import type { DeliveryEnvelope } from '../generated/api';
import type { ContextAssessment } from '../provenance';
import { Status } from './Status';

export function BlockedCard({ delivery, context, fixture }: { delivery: DeliveryEnvelope; context: ContextAssessment; fixture: boolean }) {
  return <article className="blocked-card">
    <div className="blocked-head"><div><span className="section-index">REJECTED RUN</span><h3>전달 결과 없음</h3></div><Status tone="danger">{delivery.reject_reason ?? 'REJECTED'}</Status></div>
    {fixture && <p className="fixture-copy">DEV 전용 합성 응답입니다.</p>}
    <p>DeliveryEnvelope가 실행을 거절했으며 전달된 answer payload가 없습니다.</p>
    <dl className="finding-meta">
      <div><dt>Run ID</dt><dd className="mono">{delivery.run_id}</dd></div>
      <div><dt>데이터셋</dt><dd className="mono">{context.origin}</dd></div>
    </dl>
  </article>;
}
