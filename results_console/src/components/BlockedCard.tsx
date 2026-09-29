import type { DeliveryEnvelope } from '../generated/api';
import type { ContextAssessment } from '../provenance';
import { Status } from './Status';

export function BlockedCard({ delivery, context, fixture, onRetry }: { delivery: DeliveryEnvelope; context: ContextAssessment; fixture: boolean; onRetry: () => void }) {
  const interrupted = delivery.reject_reason === 'INTERRUPTED_BY_RESTART';
  return <article className="blocked-card">
    <div className="blocked-head"><div><span className="section-index">REJECTED RUN</span><h3>{interrupted ? '서버 재시작으로 실행 중단' : '전달 결과 없음'}</h3></div><Status tone="danger">{delivery.reject_reason ?? 'REJECTED'}</Status></div>
    {fixture && <p className="fixture-copy">DEV 전용 합성 응답입니다.</p>}
    <p>{interrupted
      ? '외부 모델 호출을 자동 재실행하지 않았습니다. 실행 통제를 다시 확인한 뒤 새 실행 ID로 명시적으로 재시도하세요.'
      : 'DeliveryEnvelope가 실행을 거절했으며 전달된 answer payload가 없습니다.'}</p>
    <dl className="finding-meta">
      <div><dt>Run ID</dt><dd className="mono">{delivery.run_id}</dd></div>
      <div><dt>데이터셋</dt><dd className="mono">{context.origin}</dd></div>
    </dl>
    {interrupted && <button type="button" onClick={onRetry}>실행 조건 확인 후 재시도</button>}
  </article>;
}
