import { useEffect, useState, type ReactNode } from 'react';

export type PrimaryTab = 'intro' | 'guide' | 'console';

const primaryTabs: Array<{ id: PrimaryTab; label: string; number: string }> = [
  { id: 'intro', label: '소개', number: '01' },
  { id: 'guide', label: '사용 방법', number: '02' },
  { id: 'console', label: '결과 콘솔', number: '03' },
];

export const consoleSectionHashes = new Set([
  'summary',
  'local-audit',
  'featured-case',
  'executive-report',
  'findings',
  'readiness',
  'tasks',
  'evidence',
  'control',
]);

export function tabFromHash(hash: string): PrimaryTab {
  const value = hash.replace(/^#/, '');
  if (value === 'intro' || value === 'guide' || value === 'console') return value;
  if (consoleSectionHashes.has(value)) return 'console';
  return 'intro';
}

const findings = [
  { name: '문서 충돌', mean: '서로 다른 자료가 같은 업무에 상충하는 근거를 줌', rec: '현행 기준 문서를 지정하고 나머지에 폐기·대체 표시' },
  { name: '자료 공백', mean: '필요한 정보를 찾지 못함', rec: '담당 부서와 기준 문서를 확인해 문서화' },
  { name: '근거 부족', mean: '자료는 있으나 답을 확정할 근거가 부족', rec: '수치·기한·조건·책임자를 명시' },
  { name: '실행 결과 혼재', mean: '같은 업무가 실행마다 답변·보류로 갈림', rec: '문서부터 고치지 말고 조회 경로를 먼저 비교' },
  { name: '의미값 불일치', mean: '3회 모두 답했지만 값이 서로 다름', rec: '문서부터 고치지 말고 같은 설정으로 다시 실행해 차이를 비교' },
];

const scopeNow = ['내 폴더의 로컬 준비도 점검', '업무 반복 실행', 'Finding 집계와 권고', '정리 전후 재검증', '근거 검사', '관리자용 1페이지 리포트'];
const scopeNot = ['문서 자동 수정', '정확도 benchmark', '고객 검증 업무 catalog', '인증·권한·tenant 격리 등 프로덕션 보안'];

const guideSteps = [
  { number: '01', where: '내 자료 점검', text: '로컬 실행에서는 문서 폴더의 전체 경로를 입력해 준비도와 파일별 보완 항목을 확인합니다.' },
  { number: '02', where: '검증된 대표 흐름', text: '예시의 정적 점수와 반품 업무 0/3 → 3/3을 비교합니다.' },
  { number: '03', where: '진단 신호 01 · 문서 충돌', text: '문서 충돌을 펼쳐 정리 전·후 원문과 “30일” 근거 직접 일치를 확인합니다.' },
];

const distribution = [
  { label: '정리 전', nums: '5 · 3 · 2', cells: ['stable', 'stable', 'stable', 'stable', 'stable', 'hold', 'hold', 'hold', 'unstable', 'unstable'] },
  { label: '정리 후', nums: '6 · 2 · 2', cells: ['stable', 'stable', 'stable', 'stable', 'stable', 'stable', 'hold', 'hold', 'unstable', 'unstable'] },
];

const anatomy = [
  { number: '1', title: '유형 라벨', desc: '문서 충돌 · 자료 공백 · 근거 부족 · 실행 결과 혼재 · 의미값 불일치 중 하나' },
  { number: '2', title: '업무 질문', desc: '에이전트에게 반복 실행시킨 실제 업무 질문' },
  { number: '3', title: '원인 표시', desc: '데이터 신호 · 원인 미확인 · 검색 경로 한계 확인' },
  { number: '4', title: '권고 조치', desc: 'Finding 유형별로 정해진 다음 행동' },
  { number: '5', title: '영향 업무 수와 실행 수', desc: '이 Finding에 묶인 고유 업무 수와 관측된 실행 총 횟수' },
  { number: '6', title: '인용 원문', desc: '에이전트가 도구로 조회한 문서의 해당 문장' },
  { number: '7', title: '접힌 감사 정보', desc: '기본은 접힌 상태. 펼쳐서 실행 기록을 확인' },
];

const verdicts = [
  { code: 'DIRECT_MATCH', name: '근거 직접 일치', desc: '같은 실행에서 인용한 도구 응답에 답 값이 직접 나타남', tone: 'accent' },
  { code: 'DERIVABLE', name: '계산으로 확인', desc: '허용된 계산(정확한 합계·차이·행 수)으로 답 값을 재현함', tone: 'accent' },
  { code: 'PARTIAL_SUPPORT', name: '부분 일치', desc: '단서는 있지만 직접 일치나 단일 계산으로 확정되지 않음', tone: 'sub' },
  { code: 'UNCONFIRMED', name: '확인 불가', desc: '현재 검사 규칙으로는 자동 확인하지 못함', tone: 'line' },
];

function NumberBadge({ children }: { children: ReactNode }) {
  return <span className="guide-number-badge">{children}</span>;
}

function IntroPage() {
  return <div className="portal-page" data-screen-label="소개">
    <section className="portal-hero" data-screen-label="소개 01 첫 화면">
      <div className="portal-eyebrow"><span>AX Preflight</span><span>AI Data Readiness Audit</span><span className="portal-eyebrow__prototype">PROTOTYPE</span></div>
      <h1>파일 점검은 100점이었지만, AI는 반품 기간을 답하지 못했습니다.</h1>
      <p className="portal-hero__lede">AX Preflight는 내 폴더를 로컬에서 먼저 점검하고, 실제 업무 질문을 AI 에이전트에게 반복 실행해 어떤 문서와 실행 경로가 업무를 막거나 흔드는지 근거와 함께 보여줍니다.</p>
      <div className="portal-hero__metrics">
        <div className="portal-hero__metric">
          <span className="portal-rail" aria-hidden="true" />
          <div><span className="portal-label">정적 DATA READINESS</span><div className="portal-score"><strong>100</strong><span>/ 100</span></div><p>접근성 · 결측 · 중복 · 최신성 · 개인정보 패턴</p></div>
        </div>
        <div className="portal-hero__metric portal-hero__metric--warning">
          <span className="portal-rail" aria-hidden="true" />
          <div><span className="portal-label">반품 기간 업무 · 정리 전</span><div className="portal-score"><strong>0</strong><span>/ 3</span></div><p>3회 반복 실행 모두 보류</p></div>
        </div>
      </div>
      <div className="portal-actions">
        <a className="portal-button portal-button--primary" href="#local-audit">내 자료 점검하기 <span>→</span></a>
        <a className="portal-button" href="#featured-case">검증된 예시 보기 <span>→</span></a>
      </div>
    </section>

    <section className="portal-section" data-screen-label="소개 02 문제">
      <div className="portal-section__index">02 / 문제</div>
      <h2>파일 접근성·결측·중복·최신성·개인정보 패턴을 모두 통과해도, 같은 업무에 서로 다른 기준을 주는 문서는 드러나지 않습니다.</h2>
      <div className="portal-quote-grid">
        <figure><figcaption>FAQ_2026.txt</figcaption><blockquote>“온라인몰 고객 문의에는 상품 수령 후 <mark>14일</mark> 이내 반품 가능하다고 안내한다.”</blockquote></figure>
        <figure><figcaption>반품_교환_정책_2026.docx</figcaption><blockquote>“반품 가능 기간은 구매일로부터 <mark>30일</mark>입니다.”</blockquote></figure>
      </div>
    </section>

    <section className="portal-section" data-screen-label="소개 03 작동 방식">
      <div className="portal-section__index">03 / 작동 방식</div>
      <h2>업무 질문 하나를 세 번 실행하고, 제출된 답만 집계합니다.</h2>
      <ol className="portal-process">
        <li><div><span>STEP 01</span><span>→</span></div><strong>업무 질문 선택</strong></li>
        <li><div><span>STEP 02</span><span>→</span></div><strong>에이전트가 읽기 전용 도구 4개로 문서·표 조회</strong></li>
        <li><div><span>STEP 03</span><span>→</span></div><strong><code>submit_answer</code>로 구조화된 답 또는 보류 사유 제출</strong></li>
        <li className="portal-process__last"><div><span>STEP 04</span><span>■</span></div><strong>반복 실행 결과를 Finding과 근거 검사로 집계</strong></li>
      </ol>
      <div className="portal-principles">
        <p>결과로 인정하는 것은 제출된 구조화 답뿐입니다.</p>
        <p>에이전트가 마지막에 덧붙인 문장은 제품 결과에 들어가지 않습니다.</p>
        <p>에이전트에게는 쉘·파일 쓰기 도구가 없습니다.</p>
      </div>
    </section>

    <section className="portal-section" data-screen-label="소개 04 무엇을 알려주는가">
      <div className="portal-section__index">04 / 무엇을 알려주는가</div>
      <div className="portal-overline">업무 분류</div>
      <div className="portal-classifications">
        <div className="portal-classification portal-classification--accent"><span>STABLE</span><strong>반복 안정 처리</strong><p>3회 모두 같은 의미값으로 답변</p></div>
        <div className="portal-classification portal-classification--sub"><span>CONSISTENT HOLD</span><strong>일관된 보류</strong><p>3회 모두 보류</p></div>
        <div className="portal-classification portal-classification--warning"><span>UNSTABLE</span><strong>불안정·검토 필요</strong><p>답변·보류 혼재 또는 의미값 차이</p></div>
      </div>
      <div className="portal-overline portal-overline--spaced">FINDING 유형</div>
      <div className="portal-findings">{findings.map((finding) => <article key={finding.name}><h3>{finding.name}</h3><p>{finding.mean}</p><div><span>권고</span><p>{finding.rec}</p></div></article>)}</div>
    </section>

    <section className="portal-section" data-screen-label="소개 05 사례">
      <div className="portal-section__index">05 / 사례</div>
      <article className="portal-case">
        <header><span className="portal-warning-text">사례 A</span><h3>문서 충돌</h3></header>
        <div className="portal-case__grid">
          <div className="portal-case__column">
            <div className="portal-case__outcome portal-case__outcome--warning"><span className="portal-rail" aria-hidden="true" /><div><span>정리 전</span><div><strong>0 / 3</strong><span>보류</span></div></div></div>
            <figure className="portal-case__quote portal-case__quote--warning"><figcaption>FAQ_2026.txt</figcaption><blockquote>“온라인몰 고객 문의에는 상품 수령 후 <strong>14일</strong> 이내 반품 가능하다고 안내한다.”</blockquote></figure>
          </div>
          <div className="portal-case__column">
            <div className="portal-case__outcome"><span className="portal-rail" aria-hidden="true" /><div><span>정리 후</span><div><strong>3 / 3</strong><span>“30일”</span><em>근거 직접 일치</em></div></div></div>
            <figure className="portal-case__quote"><figcaption>FAQ_2026.txt · 정리 후</figcaption><blockquote>“반품 가능 여부는 구매일, 상품 상태, 영수증 보유 여부를 함께 확인한다.”</blockquote></figure>
          </div>
        </div>
        <p className="portal-case__change"><span>변경</span>FAQ의 14일 문장 하나를 정리</p>
      </article>
      <article className="portal-case portal-case--second">
        <header><span>사례 B</span><h3>검색 경로 한계</h3></header>
        <div className="portal-case__grid">
          <div><div className="portal-overline">업무 질문</div><p className="portal-case__question">“가장 최근 주문은 언제인가요?”</p><div className="portal-runs"><span>R1</span><span>R2</span><span className="is-answered">R3</span><strong>답변 1회 · 보류 2회</strong></div><div className="portal-legend"><span><i className="is-answered" />답변</span><span><i />보류</span></div></div>
          <div className="portal-case__explanation"><p>주문 원장은 존재했지만 업무 문장 검색에서 순위가 밀려 일부 실행만 원장에 도달했습니다.</p><p>AX Preflight는 이것을 자료 공백으로 단정하지 않고 <strong>검색 경로 한계</strong>로 분류합니다.</p></div>
        </div>
      </article>
    </section>

    <section className="portal-section" data-screen-label="소개 06 신뢰 장치">
      <div className="portal-section__index">06 / 결과를 믿을 수 있게 하는 장치</div>
      <div className="portal-trust">
        <div><span>×3</span><h3>3회 반복 실행</h3><p>한 번의 성공·실패로 판단하지 않습니다.</p></div>
        <div><span>1×</span><h3>한 번 쓰면 바뀌지 않는 결과</h3><p>제출된 답과 도구 응답은 덮어쓸 수 없습니다.</p></div>
        <div><span>=</span><h3>범위를 밝힌 근거 검사</h3><p>같은 실행에서 인용한 응답과 답 값의 일치만 확인합니다. 확인 불가는 오답이 아닙니다.</p></div>
      </div>
    </section>

    <section className="portal-section portal-section--last" data-screen-label="소개 07 현재 범위">
      <div className="portal-section__index">07 / 현재 범위</div>
      <div className="portal-scope">
        <div><span>지금 하는 것</span><ul>{scopeNow.map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div className="portal-scope__not"><span>아직 아닌 것</span><ul>{scopeNot.map((item) => <li key={item}>{item}</li>)}</ul></div>
      </div>
      <p className="portal-scope__note">데모는 합성 데이터 30개 파일·10개 업무를 정리 전후 각 3회 실행한 탐색 스냅샷입니다. 수정 효과는 직접 정리한 반품 기간 업무에 한정해 설명합니다.</p>
    </section>
  </div>;
}

function GuidePage() {
  const [runOpen, setRunOpen] = useState(true);
  return <div className="portal-page" data-screen-label="사용 방법">
    <div className="guide-heading"><div className="portal-eyebrow"><span>AX Preflight</span><span>사용 방법</span></div><h1>결과 콘솔 읽는 법</h1></div>
    <section className="portal-section guide-section" data-screen-label="사용 방법 01 순서">
      <div className="portal-section__index">01 / 3분 안에 보는 순서</div>
      <ol className="guide-steps">{guideSteps.map((step) => <li key={step.number}><span>{step.number}</span><div><strong>{step.where}</strong><p>{step.text}</p></div></li>)}</ol>
      <p className="guide-note">로컬 실행에서는 결과 콘솔 맨 위의 내 자료 점검부터 시작합니다. 공개 화면에서는 검증된 대표 흐름을 둘러볼 수 있고, 다른 데이터셋 전환과 기존 실행 조회는 07 / 조회와 실행에서 합니다.</p>
    </section>
    <section className="portal-section guide-section" data-screen-label="사용 방법 02 숫자 읽는 법">
      <div className="portal-section__index">02 / 숫자 읽는 법</div>
      <div className="guide-legend"><span><i className="is-stable" />반복 안정</span><span><i className="is-hold" />일관된 보류</span><span><i className="is-unstable" />불안정</span><span>1칸 = 업무 1개 · 합계 10</span></div>
      <div className="guide-distribution">{distribution.map((row) => <div className="guide-distribution__row" key={row.label}><div><span>{row.label}</span><strong>{row.nums}</strong></div><div>{row.cells.map((cell, index) => <i className={`is-${cell}`} key={`${row.label}-${index}`} />)}</div></div>)}</div>
      <p className="guide-callout guide-callout--warning">전체 수치 변화는 수정 효과로 해석하지 않습니다.</p>
    </section>
    <section className="portal-section guide-section" data-screen-label="사용 방법 03 Finding 카드">
      <div className="portal-section__index">03 / Finding 카드 읽는 법</div>
      <div className="guide-anatomy">
        <article className="guide-finding-card">
          <div className="guide-finding-card__body">
            <div className="guide-finding-card__row"><NumberBadge>1</NumberBadge><span className="guide-finding-card__type">01 · 문서 충돌</span></div>
            <div className="guide-finding-card__row guide-finding-card__row--start"><NumberBadge>2</NumberBadge><strong>반품 가능 기간은 며칠인가요?</strong></div>
            <div className="guide-finding-card__row"><NumberBadge>3</NumberBadge><span className="guide-finding-card__cause">원인 · 데이터 신호</span></div>
            <div className="guide-finding-card__row guide-finding-card__action"><NumberBadge>4</NumberBadge><div><span>권고 조치</span><p>현행 기준 문서를 지정하고 나머지에 폐기·대체 표시</p></div></div>
            <div className="guide-finding-card__row"><NumberBadge>5</NumberBadge><div className="guide-finding-card__counts"><div><span>영향 업무 </span><strong>1</strong></div><div><span>반복 실행 </span><strong>3</strong></div></div></div>
            <div className="guide-finding-card__row guide-finding-card__row--start"><NumberBadge>6</NumberBadge><div className="guide-finding-card__quotes"><div><span>FAQ_2026.txt</span>“…상품 수령 후 <strong>14일</strong> 이내 반품 가능하다고 안내한다.”</div><div><span>반품_교환_정책_2026.docx</span>“반품 가능 기간은 구매일로부터 <strong>30일</strong>입니다.”</div></div></div>
          </div>
          <div className="guide-finding-card__footer"><NumberBadge>7</NumberBadge><span>▸ 감사 정보</span></div>
        </article>
        <ol className="guide-anatomy__list">{anatomy.map((item) => <li key={item.number}><NumberBadge>{item.number}</NumberBadge><div><strong>{item.title}</strong><p>{item.desc}</p></div></li>)}</ol>
      </div>
    </section>
    <section className="portal-section guide-section" data-screen-label="사용 방법 04 근거 검사">
      <div className="portal-section__index">04 / 근거 검사 판정</div>
      <div className="guide-verdicts">{verdicts.map((verdict) => <div className={`guide-verdict guide-verdict--${verdict.tone}`} key={verdict.code}><span>{verdict.code}</span><strong>{verdict.name}</strong><p>{verdict.desc}</p></div>)}</div>
      <p className="guide-callout">근거 직접 일치는 정답 보증이 아니고, 확인 불가는 오답 판정이 아닙니다.</p>
      <p className="guide-callout"><strong>데이터 처리 경계 · </strong>원본 파일과 실행 산출물은 로컬 경로에서 관리합니다. 실제 AI 업무 실행에서는 요청한 도구가 반환한 문서 일부 또는 구조화 값이 설정된 모델 처리 경계로 전달될 수 있습니다.</p>
    </section>
    <section className="portal-section guide-section guide-section--last" data-screen-label="사용 방법 05 직접 실행하기">
      <button className="guide-run-toggle" type="button" aria-expanded={runOpen} onClick={() => setRunOpen((open) => !open)}><span>05 / 직접 실행하기</span><span>{runOpen ? '접기 ▴' : '펼치기 ▾'}</span></button>
      {runOpen && <div className="guide-run">
        <div className="guide-environment"><span>검증 환경</span><span>Windows 11 · PowerShell · Python 3.12+ · Node.js 20+</span></div>
        <p className="guide-note">Windows에서는 저장소 루트의 <code>start-local.cmd</code>를 실행하면 아래 두 프로세스가 자동으로 시작됩니다.</p>
        <div className="guide-terminals">
          <div><span>TERMINAL 1 · 로컬 검토 API</span><pre>{`python -m pip install -r requirements.txt
$env:AX_PRODUCT_FROZEN_RESULTS_ROOT = "artifacts/phase6_product_demo_v4/runs"
python -m uvicorn ax_product.api:create_local_review_app_from_env --factory --host 127.0.0.1 --port 8000`}</pre></div>
          <div><span>TERMINAL 2 · 결과 콘솔</span><pre>{`cd results_console
npm ci
npm run dev -- --port 5173`}</pre><a href="http://127.0.0.1:5173/">→ http://127.0.0.1:5173/</a></div>
        </div>
        <p className="guide-callout guide-callout--warning">로컬 검토 모드에서는 내 폴더의 정적 점검과 검증된 예시 조회가 활성화됩니다. AI 업무 실행은 Kiro CLI와 모델 자격 증명이 있는 라이브 모드에서만 켤 수 있습니다.</p>
      </div>}
    </section>
  </div>;
}

function PortalHeader({ tab }: { tab: PrimaryTab }) {
  return <header className="portal-header">
    <div className="portal-header__inner">
      <a className="portal-brand" href="#intro" aria-label="AX Preflight 소개로"><span>AX Preflight</span><span>AI Data Readiness Audit</span></a>
      <nav className="portal-nav" aria-label="주요 화면">
        {primaryTabs.map((item) => <a className={tab === item.id ? 'is-active' : ''} aria-current={tab === item.id ? 'page' : undefined} href={`#${item.id}`} key={item.id}><span>{item.number}</span>{item.label}</a>)}
      </nav>
    </div>
  </header>;
}

function PortalFooter() {
  return <footer className="portal-footer"><div><span>AX Preflight · AI Data Readiness Audit · AI 업무 도입 전 점검</span><span>고려대 × AWS LLM INNOVATORS CHALLENGE</span></div></footer>;
}

export function Portal({ consoleContent }: { consoleContent: ReactNode }) {
  const [tab, setTab] = useState<PrimaryTab>(() => typeof window === 'undefined' ? 'intro' : tabFromHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setTab(tabFromHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, '');
    const frame = window.requestAnimationFrame(() => {
      if (consoleSectionHashes.has(hash)) document.getElementById(hash)?.scrollIntoView({ block: 'start' });
      else if (!hash || hash === 'intro' || hash === 'guide' || hash === 'console') window.scrollTo({ top: 0 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [tab]);

  return <div className="portal-shell" data-active-tab={tab}>
    <PortalHeader tab={tab} />
    {tab === 'intro' && <main className="portal-main"><IntroPage /></main>}
    {tab === 'guide' && <main className="portal-main"><GuidePage /></main>}
    {tab === 'console' && consoleContent}
    <PortalFooter />
  </div>;
}
