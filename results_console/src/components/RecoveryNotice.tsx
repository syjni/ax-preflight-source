import type { RunFailure } from '../recovery';

export function RecoveryNotice({ failure, onAction }: { failure: RunFailure; onAction: () => void }) {
  return <div className="recovery-notice" role="alert">
    <span className="recovery-notice__code">{failure.code}</span>
    <strong>{failure.title}</strong>
    <p>{failure.message}</p>
    <button type="button" onClick={onAction}>{failure.actionLabel} →</button>
  </div>;
}
