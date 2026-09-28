import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent, type InputHTMLAttributes } from 'react';
import { ApiError, api } from '../api';
import type { DatasetOption, LocalDatasetFile, LocalDatasetScanResult, ProductCapabilities } from '../generated/api';
import { Status, type Tone } from './Status';

const issueTone: Record<'info' | 'warning' | 'error', Tone> = {
  info: 'neutral', warning: 'warning', error: 'danger',
};

type SelectedUpload = { file: File; relativePath: string };
type DropEntry = {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (success: (file: File) => void, failure?: (error: DOMException) => void) => void;
  createReader?: () => { readEntries: (success: (entries: DropEntry[]) => void, failure?: (error: DOMException) => void) => void };
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === 'LOCAL_SCAN_UNAVAILABLE') return '이 실행 모드에서는 로컬 자료 점검을 사용할 수 없습니다.';
    return error.detail.replace(' · ', ' — ');
  }
  return '자료 점검을 완료하지 못했습니다. API 터미널의 오류를 확인하세요.';
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function normalizeUploads(files: File[]): SelectedUpload[] {
  return files.map((file) => ({
    file,
    relativePath: (file.webkitRelativePath || file.name).replaceAll('\\', '/'),
  }));
}

function readFileEntry(entry: DropEntry, relativePath: string): Promise<SelectedUpload> {
  return new Promise((resolve, reject) => {
    if (!entry.file) {
      reject(new Error('Dropped file entry is unavailable.'));
      return;
    }
    entry.file((file) => resolve({ file, relativePath }), reject);
  });
}

async function readDirectoryEntry(entry: DropEntry, prefix: string): Promise<SelectedUpload[]> {
  const reader = entry.createReader?.();
  if (!reader) return [];
  const entries: DropEntry[] = [];
  while (true) {
    const batch = await new Promise<DropEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (batch.length === 0) break;
    entries.push(...batch);
  }
  return (await Promise.all(entries.map((child) => readDropEntry(child, `${prefix}${entry.name}/`)))).flat();
}

async function readDropEntry(entry: DropEntry, prefix = ''): Promise<SelectedUpload[]> {
  if (entry.isFile) return [await readFileEntry(entry, `${prefix}${entry.name}`)];
  if (entry.isDirectory) return readDirectoryEntry(entry, prefix);
  return [];
}

async function uploadsFromDrop(event: DragEvent<HTMLElement>): Promise<SelectedUpload[]> {
  const entries: DropEntry[] = [];
  for (const item of Array.from(event.dataTransfer.items ?? [])) {
    const getter = (item as unknown as { webkitGetAsEntry?: () => DropEntry | null }).webkitGetAsEntry;
    const entry = getter?.call(item);
    if (entry) entries.push(entry);
  }
  if (entries.length) return (await Promise.all(entries.map((entry) => readDropEntry(entry)))).flat();
  return normalizeUploads(Array.from(event.dataTransfer.files));
}

function sourceRootName(files: SelectedUpload[]): string {
  const firstSegments = files.map(({ relativePath }) => relativePath.split('/')[0]).filter(Boolean);
  if (firstSegments.length && firstSegments.every((value) => value === firstSegments[0]) && files.some(({ relativePath }) => relativePath.includes('/'))) {
    return firstSegments[0];
  }
  return files.length === 1 ? files[0].file.name : `선택한 파일 ${files.length}개`;
}

function fileStatus(file: LocalDatasetFile): { tone: Tone; label: string } {
  if (file.parse_status === 'ERROR') return { tone: 'danger', label: '오류' };
  if (file.parse_status === 'UNSUPPORTED') return { tone: 'warning', label: '미지원' };
  if (file.pdf_table_status === 'ERROR') return { tone: 'warning', label: 'PDF 표 확인' };
  if (file.requires_ocr) return { tone: 'warning', label: 'OCR 필요' };
  if (file.ocr_status === 'COMPLETED') {
    return { tone: 'positive', label: `OCR 완료${file.ocr_mean_confidence == null ? '' : ` ${Math.round(file.ocr_mean_confidence)}%`}` };
  }
  if (file.pii_finding_count) return { tone: 'warning', label: `개인정보 ${file.pii_finding_count}` };
  return { tone: 'positive', label: file.pdf_table_count ? `PDF 표 ${file.pdf_table_count}` : '파싱 완료' };
}

type LocalDatasetPanelProps = {
  capabilities: ProductCapabilities | null;
  capabilitiesError: string;
  selectedDataset: DatasetOption | null;
  onScanned: (result: LocalDatasetScanResult) => void;
  onDeleted: (profile: string) => void;
};

export function LocalDatasetPanel({ capabilities, capabilitiesError, selectedDataset, onScanned, onDeleted }: LocalDatasetPanelProps) {
  const folderInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [method, setMethod] = useState<'upload' | 'path'>('upload');
  const [uploads, setUploads] = useState<SelectedUpload[]>([]);
  const [dragging, setDragging] = useState(false);
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

  const uploadBytes = uploads.reduce((sum, item) => sum + item.file.size, 0);
  const uploadTooLarge = Boolean(capabilities && uploadBytes > capabilities.max_upload_bytes);
  const uploadTooMany = Boolean(capabilities && uploads.length > capabilities.max_upload_files);
  const canSubmit = method === 'upload'
    ? uploads.length > 0 && !uploadTooLarge && !uploadTooMany
    : Boolean(sourcePath.trim());

  function selectUploads(next: SelectedUpload[]) {
    const unique = new Map<string, SelectedUpload>();
    next.forEach((item) => unique.set(item.relativePath.toLocaleLowerCase(), item));
    setUploads([...unique.values()].sort((left, right) => left.relativePath.localeCompare(right.relativePath)));
    setError('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || scanning || !capabilities?.local_dataset_scan) return;
    setScanning(true);
    setError('');
    try {
      const next = method === 'upload'
        ? await api.uploadLocalDataset(uploads, displayName.trim() || null, sourceRootName(uploads))
        : await api.createLocalDataset({ source_path: sourcePath.trim(), display_name: displayName.trim() || null });
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
    const confirmed = window.confirm(result.audit.source_mode === 'UPLOAD'
      ? '점검 기록과 AX Preflight 관리 폴더의 로컬 복사본을 제거합니다. 원래 파일은 삭제하지 않습니다. 계속할까요?'
      : '생성된 AX Preflight 점검 기록만 제거합니다. 원본 파일은 삭제하지 않습니다. 계속할까요?');
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
      const leftProblem = fileStatus(left).tone === 'positive' ? 1 : 0;
      const rightProblem = fileStatus(right).tone === 'positive' ? 1 : 0;
      return leftProblem - rightProblem || left.relative_path.localeCompare(right.relative_path);
    });
  }, [result]);
  const visibleFiles = files.slice(0, 100);
  const available = Boolean(capabilities?.local_dataset_scan);

  return <section className="report-section local-audit" id="local-audit" aria-labelledby="local-audit-title">
    <header className="section-heading local-audit__heading">
      <div><div className="section-index">START HERE / 내 자료 점검</div><h2 id="local-audit-title">심사자의 파일로 직접 확인</h2></div>
      {capabilities && <Status tone={available ? 'positive' : 'neutral'}>{available ? '로컬 점검 가능' : '공개 예시 모드'}</Status>}
    </header>
    <p className="section-lede">파일이나 폴더를 선택하면 PDF·DOCX·XLSX·CSV·TXT의 준비도, PDF 표와 OCR 결과, 보완할 파일을 이 화면에서 확인합니다.</p>

    {capabilitiesError && <div className="notice notice--danger" role="alert"><strong>실행 기능을 확인하지 못했습니다</strong><span>{capabilitiesError}</span></div>}
    {!capabilities && !capabilitiesError && <div className="state-message">로컬 점검 기능을 확인하는 중…</div>}
    {capabilities && !available && <div className="local-audit__unavailable">
      <div><span className="mono">PUBLIC DEMO</span><h3>여기서는 검증된 예시를 안전하게 둘러볼 수 있습니다.</h3><p>내 파일 점검은 소스를 내려받아 로컬 검토 모드로 실행하면 활성화됩니다. 브라우저가 외부 서버로 파일을 전송하지 않습니다.</p></div>
      <a className="portal-button portal-button--primary" href="https://github.com/syjni/ax-preflight-source#내-자료로-점검하기">로컬 실행 방법 <span>→</span></a>
    </div>}

    {capabilities && available && <>
      <div className="local-audit__boundary" role="note">
        <div><span>01</span><p><strong>내 컴퓨터 안에서 처리</strong>선택한 파일은 <code>127.0.0.1</code>의 로컬 API에만 전달되며 외부 서비스로 업로드하지 않습니다.</p></div>
        <div><span>02</span><p><strong>두 가지 선택 방식</strong>브라우저 선택은 관리 폴더에 로컬 복사하고, 경로 입력은 원본 위치에서 읽기만 합니다.</p></div>
        <div><span>03</span><p><strong>AI 실행 경계</strong>{capabilities.ai_task_execution ? 'Kiro 실행을 별도로 켠 경우에만 업무 질문을 모델로 보낼 수 있습니다.' : '현재 정적 점검에는 모델 호출이 없습니다.'}</p></div>
      </div>
      <div className="local-audit__capabilities">
        <Status tone={capabilities.ocr_available ? 'positive' : 'warning'}>{capabilities.ocr_available ? 'OCR 사용 가능' : 'OCR 추가 설치 필요'}</Status>
        <span>PDF 표 추출 {capabilities.pdf_table_extraction ? '사용' : '미사용'}</span>
        <span>{capabilities.ocr_available ? `${capabilities.ocr_engine} · ${(capabilities.ocr_languages ?? []).join(', ') || '기본 언어'}` : capabilities.ocr_install_hint}</span>
      </div>
      <form className="local-audit__form" onSubmit={submit}>
        <div className="local-audit__method" role="tablist" aria-label="자료 선택 방식">
          <button type="button" role="tab" aria-selected={method === 'upload'} className={method === 'upload' ? 'is-active' : ''} onClick={() => setMethod('upload')}>파일·폴더 선택</button>
          <button type="button" role="tab" aria-selected={method === 'path'} className={method === 'path' ? 'is-active' : ''} onClick={() => setMethod('path')}>폴더 경로 입력</button>
        </div>

        {method === 'upload' ? <div className="local-audit__upload-panel" role="tabpanel">
          <input ref={folderInput} className="local-audit__hidden-input" type="file" multiple {...({ webkitdirectory: '', directory: '' } as InputHTMLAttributes<HTMLInputElement>)} onChange={(event) => selectUploads(normalizeUploads(Array.from(event.currentTarget.files ?? [])))} />
          <input ref={fileInput} className="local-audit__hidden-input" type="file" multiple accept={capabilities.supported_extensions.join(',')} onChange={(event) => selectUploads(normalizeUploads(Array.from(event.currentTarget.files ?? [])))} />
          <div className={`local-audit__dropzone${dragging ? ' is-dragging' : ''}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void uploadsFromDrop(event).then(selectUploads).catch((nextError) => setError(errorMessage(nextError))); }}>
            <span className="mono">LOCAL FILE PICKER</span><strong>여기에 파일이나 폴더를 놓으세요.</strong><p>선택 내용은 이 컴퓨터의 AX Preflight API로만 전달됩니다.</p>
            <div><button type="button" onClick={() => folderInput.current?.click()}>폴더 선택</button><button type="button" onClick={() => fileInput.current?.click()}>파일 선택</button></div>
          </div>
          {uploads.length > 0 && <div className="local-audit__selection" aria-live="polite">
            <div><strong>{uploads.length}개 파일 선택</strong><span>{formatBytes(uploadBytes)} · {sourceRootName(uploads)}</span></div>
            <button type="button" onClick={() => setUploads([])}>선택 비우기</button>
            {(uploadTooMany || uploadTooLarge) && <p role="alert">{uploadTooMany ? `한 번에 ${capabilities.max_upload_files.toLocaleString()}개까지 선택할 수 있습니다.` : `전체 크기는 ${formatBytes(capabilities.max_upload_bytes)} 이하여야 합니다.`}</p>}
            <ul>{uploads.slice(0, 5).map(({ relativePath, file }) => <li key={relativePath}><code>{relativePath}</code><span>{formatBytes(file.size)}</span></li>)}</ul>
            {uploads.length > 5 && <small>외 {uploads.length - 5}개 파일</small>}
          </div>}
          <p className="local-audit__retention">검사를 다시 열 수 있도록 로컬 관리 복사본을 보관합니다. <strong>이 점검 기록 제거</strong>를 누르면 관리 복사본도 삭제되며 원래 파일은 유지됩니다.</p>
        </div> : <div className="local-audit__path-panel" role="tabpanel">
          <label htmlFor="local-source-path"><span>점검할 폴더의 전체 경로</span><small>Windows 예: C:\review-data · macOS/Linux 예: /tmp/ax-review-data</small></label>
          <div className="local-audit__path-row"><input id="local-source-path" value={sourcePath} onInput={(event) => setSourcePath(event.currentTarget.value)} placeholder="C:\회사자료" autoComplete="off" spellCheck={false} disabled={scanning} /></div>
          <p className="local-audit__retention">경로 입력 방식은 해당 위치에서 직접 읽으며 원본 파일을 복사하거나 수정하지 않습니다.</p>
        </div>}
        <div className="local-audit__submit-row">
          <label className="local-audit__optional" htmlFor="local-display-name"><span>화면에 표시할 이름 <em>선택</em></span><input id="local-display-name" value={displayName} onInput={(event) => setDisplayName(event.currentTarget.value)} placeholder="예: 구매팀 업무 자료" maxLength={80} disabled={scanning} /></label>
          <button className="primary-action" disabled={scanning || !canSubmit}>{scanning ? '파일 점검 중…' : '내 자료 점검 시작 →'}</button>
        </div>
      </form>
      {scanning && <div className="local-audit__progress" role="status"><span aria-hidden="true" /><div><strong>자료를 로컬에서 점검하고 있습니다.</strong><p>PDF 표와 OCR 처리 여부에 따라 잠시 걸릴 수 있습니다. 이 창을 닫지 마세요.</p></div></div>}
    </>}

    {error && <div className="notice notice--danger local-audit__error" role="alert"><strong>점검을 완료하지 못했습니다</strong><span>{error}</span><p>선택한 파일의 권한과 용량을 확인한 뒤 다시 시도하세요. 경로 방식은 API 사용자가 읽을 수 있는 폴더여야 합니다.</p></div>}
    {loadingAudit && <div className="state-message">저장된 로컬 점검 결과를 불러오는 중…</div>}

    {result && <div className="local-audit__result" aria-live="polite">
      <div className="local-audit__result-title"><div><span className="mono">LOCAL AUDIT COMPLETE</span><h3>{result.audit.display_label}</h3><p>{result.audit.source_root_name} · 기준일 {result.audit.as_of_date} · {result.audit.source_mode === 'UPLOAD' ? '로컬 관리 복사본' : '원본 경로 읽기'}</p></div><Status tone={result.audit.error_file_count ? 'danger' : result.audit.issues.length ? 'warning' : 'positive'}>{result.audit.error_file_count ? '읽기 오류 있음' : result.audit.issues.length ? '검토 항목 있음' : '준비 완료'}</Status></div>
      <div className="local-audit__metrics">
        <div><span>READINESS</span><strong>{Math.round(result.readiness.readiness.readiness_score)}</strong><small>/ 100</small></div>
        <div><span>전체 파일</span><strong>{result.audit.file_count}</strong><small>개</small></div>
        <div><span>PDF 표</span><strong>{result.audit.pdf_table_count}</strong><small>개</small></div>
        <div><span>OCR 완료</span><strong>{result.audit.ocr_completed_file_count}</strong><small>개</small></div>
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
          {visibleFiles.map((file) => { const status = fileStatus(file); return <div className="local-audit__file-row" key={file.relative_path}>
            <code title={file.relative_path}>{file.relative_path}</code><span>{file.extension || '—'}</span><span>{formatBytes(file.size_bytes)}</span><Status tone={status.tone}>{status.label}</Status>
          </div>; })}
        </div>
        {files.length > visibleFiles.length && <p className="local-audit__file-limit">화면 성능을 위해 앞의 100개만 표시합니다. 전체 {files.length}개 파일은 생성된 로컬 보고서에 기록되어 있습니다.</p>}
      </details>
    </div>}
  </section>;
}
