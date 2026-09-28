import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ApiError, api } from '../api';
import type { DatasetOption, LocalDatasetScanResult, ProductCapabilities } from '../generated/api';
import { Status, type Tone } from './Status';

const issueTone: Record<'info' | 'warning' | 'error', Tone> = {
  info: 'neutral',
  warning: 'warning',
  error: 'danger',
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === 'LOCAL_SCAN_UNAVAILABLE') {
      return '이 실행 모드에서는 로컬 폴더 점검을 사용할 수 없습니다.';
    }
    return error.detail.replace(' · ', ' — ');
  }
  return '폴더 점검을 완료하지 못했습니다. API 터미널의 오류를 확인하세요.';
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

type LocalDatasetPanelProps = {
  capabilities: ProductCapabilities | null;
  capabilitiesError: string;
  selectedDataset: DatasetOption | null;
  onScanned: (result: LocalDatasetScanResult) => void;
  onDeleted: (profile: string) => void;
};

export function LocalDatasetPanel({
  capabilities,
  capabilitiesError,
  selectedDataset,
  onScanned,
  onDeleted,
}: LocalDatasetPanelProps) {
  const [sourcePath, setSourcePath] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [scanning, setScanning] = useState(false);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<LocalDatasetScanResult | null>(null);

  useEffect(() => {
    const profile = selectedDataset?.origin === 'LOCAL' ? selectedDataset.profile : null;
    if (!profile) {
      if (selectedDataset) setResult(null);
      setLoadingAudit(false);
      return;
    }
    if (result?.dataset.profile === profile) return;
    let active = true;
    setLoadingAudit(true);
    setError('');
    api.localDataset(profile)
      .then((next) => { if (active) setResult(next); })
      .catch((nextError: unknown) => { if (active) setError(errorMessage(nextError)); })
      .finally(() => { if (active) setLoadingAudit(false); });
    return () => { active = false; };
  }, [selectedDataset?.profile, selectedDataset?.origin]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!sourcePath.trim() || scanning || !capabilities?.local_dataset_scan) return;
    setScanning(true);
    setError('');
    try {
      const next = await api.createLocalDataset({
        source_path: sourcePath.trim(),
        display_name: displayName.trim() || null,
      });
      setResult(next);
      onScanned(next);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setScanning(false);
    }
  }

  async function removeAudit() {
    if (!result || deleting) return;
    const confirmed = window.confirm(
      '생성된 AX Preflight 점검 기록만 제거합니다. 원본 파일은 삭제하지 않습니다. 계속할까요?',
    );
    if (!confirmed) return;
    setDeleting(true);
    setError('');
    try {
      await api.deleteLocalDataset(result.dataset.profile);
      const removed = result.dataset.profile;
      setResult(null);
      onDeleted(removed);
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setDeleting(false);
    }
  }

  const files = useMemo(() => {
    if (!result) return [];
    return [...result.audit.files].sort((left, right) => {
      const leftProblem = left.parse_status === 'PARSED' && !left.requires_ocr && left.pii_finding_count === 0 ? 1 : 0;
      const rightProblem = right.parse_status === 'PARSED' && !right.requires_ocr && right.pii_finding_count === 0 ? 1 : 0;
      return leftProblem - rightProblem || left.relative_path.localeCompare(right.relative_path);
    });
  }, [result]);
  const visibleFiles = files.slice(0, 100);
  const available = Boolean(capabilities?.local_dataset_scan);

  return <section className="report-section local-audit" id="local-audit" aria-labelledby="local-audit-title">
    <header className="section-heading local-audit__heading">
      <div><div className="section-index">START HERE / 내 자료 점검</div><h2 id="local-audit-title">심사자의 폴더로 직접 확인</h2></div>
      {capabilities && <Status tone={available ? 'positive' : 'neutral'}>{available ? '로컬 점검 가능' : '공개 예시 모드'}</Status>}
    </header>
    <p className="section-lede">PDF·DOCX·XLSX·CSV·TXT가 있는 폴더를 로컬에서 스캔하고, 준비도와 보완할 파일을 이 화면에서 확인합니다.</p>

    {capabilitiesError && <div className="notice notice--danger" role="alert"><strong>실행 기능을 확인하지 못했습니다</strong><span>{capabilitiesError}</span></div>}
    {!capabilities && !capabilitiesError && <div className="state-message">로컬 점검 기능을 확인하는 중…</div>}

    {capabilities && !available && <div className="local-audit__unavailable">
      <div><span className="mono">PUBLIC DEMO</span><h3>여기서는 검증된 예시를 안전하게 둘러볼 수 있습니다.</h3><p>내 파일 점검은 소스를 내려받아 로컬 검토 모드로 실행하면 활성화됩니다. 브라우저가 외부 서버로 파일을 전송하지 않습니다.</p></div>
      <a className="portal-button portal-button--primary" href="https://github.com/syjni/ax-preflight-source#내-자료로-점검하기">로컬 실행 방법 <span>→</span></a>
    </div>}

    {capabilities && available && <>
      <div className="local-audit__boundary" role="note">
        <div><span>01</span><p><strong>원본 위치</strong>입력한 폴더에서 직접 읽고 원본을 복사·수정하지 않습니다.</p></div>
        <div><span>02</span><p><strong>저장 범위</strong>마스킹된 스캔 보고서만 이 저장소의 로컬 artifacts에 저장합니다.</p></div>
        <div><span>03</span><p><strong>AI 실행</strong>{capabilities.ai_task_execution ? 'Kiro 실행이 활성화되어 점검 후 업무 질문도 실행할 수 있습니다.' : '현재는 정적 점검 모드이며 Kiro를 켤 때만 문서 일부가 모델 경계로 전달될 수 있습니다.'}</p></div>
      </div>
      <form className="local-audit__form" onSubmit={submit}>
        <label htmlFor="local-source-path"><span>점검할 폴더의 전체 경로</span><small>Windows 예: C:\review-data · macOS/Linux 예: /Users/me/review-data</small></label>
        <div className="local-audit__path-row"><input id="local-source-path" value={sourcePath} onInput={(event) => setSourcePath(event.currentTarget.value)} placeholder="C:\회사자료" autoComplete="off" spellCheck={false} disabled={scanning} /><button className="primary-action" disabled={scanning || !sourcePath.trim()}>{scanning ? '파일 점검 중…' : '내 자료 점검 시작 →'}</button></div>
        <label className="local-audit__optional" htmlFor="local-display-name"><span>화면에 표시할 이름 <em>선택</em></span><input id="local-display-name" value={displayName} onInput={(event) => setDisplayName(event.currentTarget.value)} placeholder="예: 구매팀 업무 자료" maxLength={80} disabled={scanning} /></label>
      </form>
      {scanning && <div className="local-audit__progress" role="status"><span aria-hidden="true" /><div><strong>폴더를 로컬에서 점검하고 있습니다.</strong><p>파일 수와 크기에 따라 잠시 걸릴 수 있습니다. 이 창을 닫지 마세요.</p></div></div>}
    </>}

    {error && <div className="notice notice--danger local-audit__error" role="alert"><strong>점검을 완료하지 못했습니다</strong><span>{error}</span><p>경로가 실제 폴더인지, API를 실행한 사용자에게 읽기 권한이 있는지 확인한 뒤 다시 시도하세요.</p></div>}
    {loadingAudit && <div className="state-message">저장된 로컬 점검 결과를 불러오는 중…</div>}

    {result && <div className="local-audit__result" aria-live="polite">
      <div className="local-audit__result-title"><div><span className="mono">LOCAL AUDIT COMPLETE</span><h3>{result.audit.display_label}</h3><p>{result.audit.source_root_name} · 기준일 {result.audit.as_of_date}</p></div><Status tone={result.audit.error_file_count ? 'danger' : result.audit.issues.length ? 'warning' : 'positive'}>{result.audit.error_file_count ? '읽기 오류 있음' : result.audit.issues.length ? '검토 항목 있음' : '준비 완료'}</Status></div>
      <div className="local-audit__metrics">
        <div><span>READINESS</span><strong>{Math.round(result.readiness.readiness.readiness_score)}</strong><small>/ 100</small></div>
        <div><span>전체 파일</span><strong>{result.audit.file_count}</strong><small>개</small></div>
        <div><span>파싱 완료</span><strong>{result.audit.parsed_file_count}</strong><small>개</small></div>
        <div><span>보완 항목</span><strong>{result.audit.issues.length}</strong><small>유형</small></div>
      </div>
      <div className="local-audit__actions"><button type="button" onClick={() => document.getElementById('readiness')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>전체 준비도 보기 ↓</button><button type="button" className="is-danger" onClick={() => void removeAudit()} disabled={deleting}>{deleting ? '기록 제거 중…' : '이 점검 기록 제거'}</button></div>

      <div className="local-audit__issues">
        <div className="local-audit__subheading"><div><span className="mono">ACTION LIST</span><h3>먼저 보완할 항목</h3></div><span>{result.audit.issues.length}개 유형</span></div>
        {result.audit.issues.length === 0 ? <div className="state-message">현재 검사 규칙에서 바로 보완할 항목을 찾지 못했습니다.</div> : result.audit.issues.map((issue) => <details key={issue.code} className={`local-audit__issue is-${issue.severity}`} open={issue.severity === 'error'}>
          <summary><Status tone={issueTone[issue.severity]}>{issue.count}</Status><div><strong>{issue.title}</strong><p>{issue.action}</p></div><span>파일 보기 +</span></summary>
          <ul>{(issue.relative_paths ?? []).map((path) => <li key={path}><code>{path}</code></li>)}</ul>
        </details>)}
      </div>

      <details className="local-audit__files">
        <summary><div><span className="mono">FILE REGISTRY</span><strong>점검한 파일 목록</strong></div><span>{result.audit.file_count}개 보기 +</span></summary>
        <div className="local-audit__file-table">
          <div className="local-audit__file-head"><span>파일</span><span>형식</span><span>크기</span><span>상태</span></div>
          {visibleFiles.map((file) => <div className="local-audit__file-row" key={file.relative_path}>
            <code title={file.relative_path}>{file.relative_path}</code><span>{file.extension || '—'}</span><span>{formatBytes(file.size_bytes)}</span><Status tone={file.parse_status === 'ERROR' ? 'danger' : file.parse_status === 'UNSUPPORTED' || file.requires_ocr || file.pii_finding_count ? 'warning' : 'positive'}>{file.parse_status === 'ERROR' ? '오류' : file.parse_status === 'UNSUPPORTED' ? '미지원' : file.requires_ocr ? 'OCR 필요' : file.pii_finding_count ? `개인정보 ${file.pii_finding_count}` : '파싱 완료'}</Status>
          </div>)}
        </div>
        {files.length > visibleFiles.length && <p className="local-audit__file-limit">화면 성능을 위해 앞의 100개만 표시합니다. 전체 {files.length}개 파일은 생성된 로컬 보고서에 기록되어 있습니다.</p>}
      </details>
    </div>}
  </section>;
}
