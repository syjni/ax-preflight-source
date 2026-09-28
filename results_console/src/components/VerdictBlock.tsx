import type { DeliveryEnvelope } from '../generated/api';
import { Status } from './Status';

export function VerdictBlock({ delivery }: { delivery: DeliveryEnvelope }) {
  const payload = delivery.payload;
  if (delivery.delivery_status !== 'DELIVERED' || !payload) return null;
  const answered = payload.status === 'ANSWERED';
  return <div className="verdict-block">
    <div className="verdict-label">DELIVERY VERDICT</div>
    <div className="verdict-main">
      <Status tone={answered ? 'positive' : 'warning'}>{answered ? '답변' : '보류'}</Status>
      {answered ? <div className="answer-display">{Array.isArray(payload.answer) ? payload.answer.join(', ') : String(payload.answer ?? '—')}{payload.unit && <small> {payload.unit}</small>}</div>
        : <div className="answer-display answer-display--muted">{payload.abstention_reason === 'NOT_FOUND' ? '필요한 자료를 찾지 못해 보류' : payload.abstention_reason === 'INSUFFICIENT_EVIDENCE' ? '근거가 부족해 보류' : payload.abstention_reason === 'CONFLICTING_EVIDENCE' ? '근거가 충돌해 보류' : '사유 미기록'}</div>}
    </div>
    <span className="agent-explanation-label verdict-explanation-label">에이전트 설명 · 검증 대상 아님</span>
    <p>{payload.explanation}</p>
    <div className={`source-link source-link--${String(delivery.source_link_status ?? 'none').toLowerCase()}`}>
      <span>Delivery source link</span>
      <strong className="mono">{delivery.source_link_status ?? '없음'}</strong>
      <p>{delivery.source_link_status === 'NOT_CHECKED'
        ? 'Source ID의 연결 및 답변 지지를 아직 검사하지 않은 상태입니다.'
        : delivery.source_link_status === 'LINKED'
          ? '연결 상태 기록입니다. 아래 Evidence Checker 판정과는 별개입니다.'
          : 'DeliveryEnvelope에 저장된 연결 상태이며 Evidence Checker 판정과 합치지 않습니다.'}</p>
    </div>
  </div>;
}
