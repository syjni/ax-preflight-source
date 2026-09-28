import type { FeaturedCase, FeaturedRunReference } from '../api';

type FeaturedCaseJourneyProps = {
  cases: FeaturedCase[];
  currentDataset: string;
  currentRunId: string | null;
  loadingRunId: string | null;
  error: string;
  onOpen: (reference: FeaturedRunReference) => void;
};

function StageButton({
  reference,
  currentDataset,
  currentRunId,
  loadingRunId,
  onOpen,
}: {
  reference: FeaturedRunReference;
  currentDataset: string;
  currentRunId: string | null;
  loadingRunId: string | null;
  onOpen: (reference: FeaturedRunReference) => void;
}) {
  const selected = currentDataset === reference.dataset && currentRunId === reference.run_id;
  const loading = loadingRunId === reference.run_id;
  return <button
    type="button"
    className={`featured-case__stage featured-case__stage--${reference.phase.toLowerCase()}${selected ? ' is-selected' : ''}`}
    aria-pressed={selected}
    disabled={Boolean(loadingRunId)}
    onClick={() => onOpen(reference)}
  >
    <span className="featured-case__phase">{reference.label}</span>
    <strong>{reference.result}</strong>
    <span className="featured-case__detail">{reference.detail}</span>
    <span className="featured-case__action">{loading ? '불러오는 중…' : selected ? '현재 보고 있는 실행' : `${reference.action_label} →`}</span>
  </button>;
}

export function FeaturedCaseJourney(props: FeaturedCaseJourneyProps) {
  const featured = props.cases[0];
  if (!featured) return null;

  return <section className="featured-case" id="featured-case" aria-labelledby="featured-case-title">
    <div className="featured-case__copy">
      <div className="section-index">검증된 대표 흐름</div>
      <h2 id="featured-case-title">{featured.title}</h2>
      <p>{featured.summary}</p>
      <small>{featured.question}</small>
    </div>
    <div className="featured-case__stages">
      <StageButton reference={featured.before} currentDataset={props.currentDataset} currentRunId={props.currentRunId} loadingRunId={props.loadingRunId} onOpen={props.onOpen} />
      <span className="featured-case__arrow" aria-hidden="true">→</span>
      <StageButton reference={featured.after} currentDataset={props.currentDataset} currentRunId={props.currentRunId} loadingRunId={props.loadingRunId} onOpen={props.onOpen} />
    </div>
    {props.error && <div className="notice notice--danger" role="alert">{props.error}</div>}
  </section>;
}
