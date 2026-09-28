# AX 소개·사용 방법 페이지 프로젝트 브리프

## 1. 한 줄 정의

AX는 실제 AI 업무 테스트를 통해 **어떤 데이터·실행 신호가 어떤 업무를 막거나 흔드는지** 드러내며, 문서 접근과 결과 저장을 사용자가 통제하는 Data Readiness Audit 프로토타입입니다. (출처: `README.md`)

## 2. 해결하려는 문제

정적 Data Readiness는 파일 접근성, 표의 결측, 완전 중복, 수정일 최신성, 개인정보 패턴처럼 문서 집합의 구조적 상태를 측정하지만, 실제 업무 질문에 필요한 기준끼리 의미상 충돌하는지는 같은 방식으로 보증하지 않는다. Readiness 100도 답변 성공을 보장하지 않고, 답변 성공도 Readiness 점수를 다시 계산하지 않는다. (출처: `SUBMISSION.md`, `docs/ARCHITECTURE.md`, `results_console/src/viewModel.ts`)

대표 사례에서 한빛유통 30개 파일의 정적 Readiness는 100점이었지만, 반품 기간 업무는 Before의 3회 실행 모두 답을 내지 못했다. `FAQ_2026.txt`는 14일을, `반품_교환_정책_2026.docx`는 30일을 말해 같은 업무에 충돌하는 기준을 제공했기 때문이다. (출처: `docs/DEMO_SCRIPT.md`)

따라서 AX가 해결하려는 핵심 문제는 “문서가 준비되어 보이는가”가 아니라 “AI 도입 전에 이 업무를 반복해도 되는가, 막히거나 흔들린다면 데이터와 실행 중 어디를 먼저 검토해야 하는가”를 실제 업무 실행으로 드러내는 것이다. (출처: `docs/DEMO_SCRIPT.md`, `README.md`)

이 사례에서 정리한 것은 FAQ의 14일 문장 하나이며, 정리 후 반품 업무는 3회 모두 30일로 답했고 같은 실행의 인용 응답에서도 그 값이 확인됐다. 이 변화는 정적 점수만으로는 보이지 않던 문서 충돌을 실제 업무 테스트가 찾아낸 사례다. (출처: `docs/DEMO_SCRIPT.md`, `docs/PHASE6_V4.md`, `results_console/src/components/ExecutiveReport.tsx`)

## 3. 대상 사용자와 사용 맥락

| 대상 | 언제 쓰는가 | 무엇을 결정하려는가 | 확인 상태 |
|---|---|---|---|
| 데이터셋을 연결하고 업무 질문을 선택·실행하는 사용자 | AI 업무 도입 전, 또는 문서·검색 경로를 정리한 뒤 같은 업무를 다시 확인할 때. (출처: `docs/DEMO_SCRIPT.md`, `results_console/src/components/RunControls.tsx`) | 같은 업무를 반복해도 되는지, 먼저 데이터와 실행 중 어디를 검토할지 판단한다. (출처: `docs/DEMO_SCRIPT.md`) | 구체적인 직무명·조직 규모·산업군은 **미확인**이다. 현재 문서는 역할을 일반적인 “사용자”로만 표현한다. (출처: `docs/ARCHITECTURE.md`, `README.md`) |
| 진단 결과를 공유받는 관리자 | 결과를 1페이지로 검토하거나 PDF·인쇄물로 공유받을 때. (출처: `results_console/src/components/ExecutiveReport.tsx`) | 반복 안정·보류·불안정 현황, 수정 대상, 권고 조치, Before/After 사례를 보고 우선 검토 순서를 정한다. (출처: `results_console/src/components/ExecutiveReport.tsx`, `docs/DEMO_SCRIPT.md`) | UI에는 “관리자 공유용 1페이지”가 명시되어 있으나, 최종 승인권자나 구매자 역할은 **미확인**이다. (출처: `results_console/src/components/ExecutiveReport.tsx`) |
| 심사·데모 검토자 | 검증된 frozen 결과를 읽기 전용으로 재현할 때. (출처: `SUBMISSION.md`, `docs/DEMO_SCRIPT.md`) | 제품 흐름, 주장 경계, 반품 충돌의 좁은 수정 효과를 확인한다. (출처: `SUBMISSION.md`, `docs/DEMO_SCRIPT.md`) | 실제 고객 운영 사용자는 아니며, frozen 데모는 고객 검증 benchmark가 아니다. (출처: `SUBMISSION.md`) |

핵심 사용 맥락은 고객 환경 전체의 AI 성능을 채점하는 것이 아니라, 선택한 업무 질문을 반복 실행해 성공·보류·변동과 그 근거를 업무 단위로 검토하는 것이다. (출처: `README.md`, `docs/PHASE6_V4.md`)

## 4. 동작 방식

1. 사용자가 Results Console에서 제품이 제공하는 업무 테스트 후보를 선택하거나 ad hoc 업무 질문을 입력한다. 후보는 회사별 검증 과제가 아니며, 현재 dataset에 적용 가능한 질문인지는 사용자가 판단한다. (출처: `results_console/src/components/TaskTable.tsx`, `results_console/src/components/RunControls.tsx`, `results_console/src/App.tsx`)
2. 라이브 실행이 명시적으로 활성화된 경우 FastAPI가 run ID, dataset provenance, 선택한 업무 context를 `artifacts/product_runs`에 예약하고 Kiro runner에 실행을 요청한다. (출처: `docs/ARCHITECTURE.md`)
3. Kiro runner는 `.kiro/agents/ax-product.json`을 바탕으로 실행마다 임시 product agent를 만든다. (출처: `docs/ARCHITECTURE.md`)
4. product agent가 사용할 수 있는 도구는 총 5개다. 데이터 도구 4개는 `search_documents`, `read_document`, `lookup_value`, `query_table`이고, 제출 도구 1개는 `submit_answer`다. (출처: `docs/ARCHITECTURE.md`, `README.md`)
5. 성공한 데이터 도구의 구조화 응답은 같은 run의 `tool-responses/*.json`에 write-once로 저장될 수 있으며, 첫 번째 유효한 `SubmitAnswerInput`만 권위 있는 제품 결과가 된다. (출처: `docs/ARCHITECTURE.md`, `docs/DATA_AND_PRIVACY.md`)
6. `submit_answer` 결과는 `DeliveryEnvelope`의 `delivery.json`으로 게시된다. assistant prose, stdout, Kiro `finalText`는 제품 답으로 해석하지 않는다. (출처: `docs/ARCHITECTURE.md`, `SUBMISSION.md`)
7. Failure→Finding 집계기는 `DeliveryEnvelope`, 저장된 업무 context, 같은 run의 구조화 응답만 읽어 보류·충돌·혼재를 업무 단위로 그룹화한다. 새 모델 추론을 하지 않으며 고유 업무 수와 반복 실행 수를 분리한다. (출처: `docs/ARCHITECTURE.md`, `README.md`)
8. Evidence Checker는 승인된 `DeliveryEnvelope`와 그 run에서 인용된 구조화 응답만 읽어 별도의 `evidence-check.json`을 게시한다. 기존 delivery를 수정하지 않으며 Finding·Readiness와도 별도 계약으로 유지된다. (출처: `docs/ARCHITECTURE.md`, `docs/EVIDENCE_CHECKER_V3.md`)

요약 흐름: **업무 질문 → FastAPI → Kiro runner → 실행별 임시 product agent → 4개 데이터 도구 → `submit_answer` → `DeliveryEnvelope` → Failure→Finding / Evidence Checker → Results Console**. (출처: `docs/ARCHITECTURE.md`)

## 5. 핵심 개념 용어집

### 반복 실행 진단

| 개념 | UI의 실제 한국어 라벨 | 한 줄 설명 |
|---|---|---|
| 반복 안정 | **반복 안정 처리** | 같은 업무의 3회 실행이 모두 답변되고 의미값이 같다. (출처: `results_console/src/components/SummarySection.tsx`, `docs/PHASE6_V4.md`) |
| 일관된 보류 | **일관된 보류** | 같은 업무의 3회 실행이 모두 보류됐다. (출처: `results_console/src/components/SummarySection.tsx`, `docs/PHASE6_V4.md`) |
| 불안정·검토 필요 | **불안정·검토 필요** | 답변과 보류가 섞였거나 실제 의미값이 달라 추가 검토가 필요하다. 그 자체로 데이터 문제 판정은 아니다. (출처: `results_console/src/components/SummarySection.tsx`, `docs/PHASE6_V4.md`) |

### Finding 유형

| 코드 | UI의 실제 한국어 라벨 | 한 줄 설명 |
|---|---|---|
| `CONFLICTING_SOURCES` | **문서 충돌** | 같은 업무 실행에서 서로 충돌하는 source가 인용된 데이터 신호다. (출처: `results_console/src/components/FindingCard.tsx`, `README.md`) |
| `MISSING_INFORMATION` | **자료 공백** | 필요한 자료를 찾지 못해 보류된 경우를 업무 수준 Finding으로 표시한다. (출처: `results_console/src/components/FindingCard.tsx`, `results_console/src/components/VerdictBlock.tsx`) |
| `INSUFFICIENT_EVIDENCE` | **근거 부족** | 검색한 자료가 있어도 답을 확정할 근거가 부족해 보류된 경우다. (출처: `results_console/src/components/FindingCard.tsx`, `results_console/src/components/VerdictBlock.tsx`) |
| `MIXED_OUTCOMES` | **실행 결과 혼재** | 같은 업무 반복에서 ANSWERED와 ABSTAINED가 섞인 경우다. 기본 원인 귀속은 미확인이며, 재현된 검색 경로 한계가 있으면 별도로 표시할 수 있다. (출처: `results_console/src/components/FindingCard.tsx`, `docs/PHASE6_V4.md`) |
| `INCONSISTENT_ANSWERS` | **불안정 업무 · 원인 미확인 (의미값 불일치)** | 3회 모두 답변됐지만 v2 의미값이 실제로 다른 경우에만 생성된다. (출처: `results_console/src/components/FindingCard.tsx`, `docs/PHASE6_V4.md`) |

### 근거 검사 판정

| 개념 | 코드 | UI의 실제 한국어 라벨 | 한 줄 설명 |
|---|---|---|---|
| 근거 직접 일치 | `DIRECT_MATCH` | **근거 일치** | 인용된 같은-run 구조화 응답에서 전달 값이 직접 확인됐다. 업무 정답률을 뜻하지 않는다. (출처: `results_console/src/viewModel.ts`, `SUBMISSION.md`) |
| 계산 가능 | `DERIVABLE` | **계산으로 확인** | 허용된 결정적 계산으로 전달 값을 재현했다. 허용 범위는 정확한 합계·차이·행 수이며 나눗셈·비율·단위 변환·의미 추론은 제외된다. (출처: `results_console/src/viewModel.ts`, `results_console/src/components/EvidenceCheckPanel.tsx`) |
| 부분 지지 | `PARTIAL_SUPPORT` | **부분 일치** | 일부 단서는 확인되지만 직접 일치나 단일 계산으로 확정되지 않았다. (출처: `results_console/src/viewModel.ts`) |
| 확인 불가 | `UNCONFIRMED` | **확인 불가** | checker 범위 안에서 근거 지지를 결정적으로 확인하지 못했다. 오답 판정이 아니다. (출처: `results_console/src/viewModel.ts`, `docs/EVIDENCE_CHECKER_V3.md`) |

### 정적 Data Readiness 5개 항목

| UI의 실제 한국어 라벨 | UI의 한 줄 설명 | 해석 |
|---|---|---|
| **완전 중복 파일** | 바이트가 같은 파일 탐지 | 전체 파일, 완전 중복 그룹, 중복 파일 수를 표시한다. (출처: `results_console/src/viewModel.ts`, `results_console/src/components/ReadinessTable.tsx`) |
| **표 데이터 완결성** | 평가 대상 표의 누락 셀 점검 | 평가 대상 표, 전체 셀, 추정 누락 셀을 표시한다. (출처: `results_console/src/viewModel.ts`, `results_console/src/components/ReadinessTable.tsx`) |
| **개인정보 패턴 탐지** | 등록된 개인정보 탐지 패턴 기반 점검 | 탐지 파일과 미탐지 파일 수를 보여 주는 readiness 신호이며 완전한 보안 통제가 아니다. (출처: `results_console/src/viewModel.ts`, `results_console/src/components/ReadinessTable.tsx`, `docs/DATA_AND_PRIVACY.md`) |
| **파일 접근성** | 파싱 및 OCR 필요 여부 점검 | 파싱 파일, OCR 필요 파일, 접근 가능 파일을 표시한다. (출처: `results_console/src/viewModel.ts`, `results_console/src/components/ReadinessTable.tsx`) |
| **수정일 최신성** | 파일 수정 시각 기준 점검 | 유효 수정일, 최신·오래된 파일, 미래·누락·오류 시각을 표시한다. (출처: `results_console/src/viewModel.ts`, `results_console/src/components/ReadinessTable.tsx`) |

## 6. 대표 데모 결과

v4는 동일한 10개 후보 업무를 Before/After에서 각각 3회 실행한 60-run write-once snapshot이며, 30개 회사 파일의 10개 업무를 상태별로 관측한다. (출처: `docs/PHASE6_V4.md`, `docs/DEMO_SCRIPT.md`)

### 현재 제품 표시 기준: 의미 비교 v2

| 업무 분류 | Before | After | 출처 |
|---|---:|---:|---|
| 반복 안정 처리: 3회 모두 같은 의미값으로 답변 | 5 / 10 | 6 / 10 | (출처: `docs/PHASE6_V4.md`) |
| 일관된 보류: 3회 모두 보류 | 3 / 10 | 2 / 10 | (출처: `docs/PHASE6_V4.md`) |
| 불안정·검토 필요: 답변·보류 혼재 또는 실제 의미값 차이 | 2 / 10 | 2 / 10 | (출처: `docs/PHASE6_V4.md`) |

각 상태에서 세 분류의 합은 10개 업무다. 의미 비교 v2는 같은 frozen run을 다시 실행하지 않고 빈 결과, 식별자 집합, 날짜, 정규화된 수치·단위 family, 답 문장의 명시적 단위를 일반 규칙으로 재분류한 현재 제품 표시 기준이다. (출처: `docs/PHASE6_V4.md`)

### frozen 감사 기준: 비교 v1

| 지표 | Before | After | 출처 |
|---|---:|---:|---|
| 관측 run | 30 | 30 | (출처: `docs/PHASE6_V4.md`) |
| ANSWERED | 19 | 21 | (출처: `docs/PHASE6_V4.md`) |
| ABSTAINED | 11 | 9 | (출처: `docs/PHASE6_V4.md`) |
| 3회 모두 같은 문자열·단위로 처리 | 4 / 10 | 2 / 10 | (출처: `docs/PHASE6_V4.md`) |
| 1회 이상 보류 | 5 / 10 | 4 / 10 | (출처: `docs/PHASE6_V4.md`) |
| 문자열·단위 불일치로 inconclusive | 1 / 10 | 4 / 10 | (출처: `docs/PHASE6_V4.md`) |
| Evidence `DIRECT_MATCH` | 17 / 30 | 18 / 30 | (출처: `docs/PHASE6_V4.md`) |

전체 Evidence는 35/60이 `DIRECT_MATCH`이고 25건이 `UNCONFIRMED`다. 전자는 인용 구조화 응답과 답 값의 일치 건수이고, 후자는 결정론적 checker가 자동 확인하지 못한 건수이므로 둘 다 정답·오답률로 읽으면 안 된다. (출처: `docs/PHASE6_V4.md`)

### 반품 업무의 좁은 Before/After

- Before는 3/3 `CONFLICTING_EVIDENCE` 보류, 즉 답변 성공 0/3이었다. (출처: `docs/PHASE6_V4.md`, `docs/DEMO_SCRIPT.md`)
- After는 3/3 `30일 / DIRECT_MATCH`, 즉 답변 성공 3/3이었다. 기존 충돌 Finding은 UI에서 **수정 후 미재현**으로 표시되고 감사용 legacy 문구는 **After에서 재현되지 않음**이다. (출처: `docs/PHASE6_V4.md`, `results_console/src/components/FindingCard.tsx`)
- 실제 변경 파일은 `06_고객지원/FAQ_2026.txt` 1개이므로 수정 효과 주장은 반품 기간 업무의 0/3→3/3에만 한정한다. Before 5/10→After 6/10 전체 차이는 인과 효과로 주장하지 않는다. (출처: `docs/PHASE6_V4.md`, `SUBMISSION.md`)
- 이 v4는 탐색 데모이며 고객 검증 benchmark나 무작위 대조 실험이 아니다. (출처: `SUBMISSION.md`)

## 7. 결과 콘솔 사용법

| 섹션 | 무엇을 보는가 | 어떻게 해석하는가 |
|---|---|---|
| **01 / 요약 — AI 업무 진단** | 정적 Data Readiness 점수, 반품 0/3→3/3 사례, 반복 안정·일관된 보류·불안정의 3개 지표, 현재 실행 결과, dataset·관측 실행·열린 신호·run ID를 본다. (출처: `results_console/src/components/SummarySection.tsx`) | 정적 점수는 보조 신호이고 실제 업무 성공을 보증하지 않는다. 3개 업무 분류로 “반복 가능한가/계속 보류되는가/흔들리는가”를 먼저 파악한다. (출처: `results_console/src/components/SummarySection.tsx`, `docs/ARCHITECTURE.md`) |
| **02 / 관리자 1페이지** | 반복 진단 3개 지표, 반품 수정 사례의 전후 원문, 우선 검토할 열린 신호 최대 5건, 권고 조치와 재검증 업무 수를 본다. `PDF로 저장 / 인쇄`를 사용할 수 있다. (출처: `results_console/src/components/ExecutiveReport.tsx`) | 전체 품질 향상 리포트가 아니라, 변경 파일과 직접 연결되는 반품 사례와 현재 열린 우선순위를 공유하는 1페이지로 해석한다. (출처: `results_console/src/components/ExecutiveReport.tsx`) |
| **03 / 진단 신호** | Finding 유형, 원인 귀속, 영향받은 고유 업무 수, 반복 실행 수, 답변·보류 변형, 권고 조치, 같은-run 원문·구조화 표를 펼쳐 본다. (출처: `results_console/src/App.tsx`, `results_console/src/components/FindingCard.tsx`) | `데이터 신호`, `원인 미확인`, `검색 경로 한계 확인`을 구분한다. 혼재나 의미값 불일치만으로 문서를 고치지 말고, 원인이 재현된 경우에만 조치한다. (출처: `results_console/src/components/FindingCard.tsx`, `docs/PHASE6_V4.md`) |
| **04 / 정적 준비도** | 5개 점수 항목을 펼쳐 집계와 flag를 확인하고, 점수에 포함되지 않은 observation을 별도로 본다. (출처: `results_console/src/components/ReadinessTable.tsx`, `results_console/src/viewModel.ts`) | 실제 업무 진단과 분리된 보조 지표다. 현재 API는 점수 차원별 개별 파일 목록이나 observation 연결을 제공하지 않으므로 UI도 관련성을 추정하지 않는다. (출처: `results_console/src/components/ReadinessTable.tsx`, `results_console/README.md`) |
| **05 / 업무 후보** | 제품 기본값인 업무 테스트 후보 10개 중 질문을 선택해 입력란에 채운다. (출처: `docs/ARCHITECTURE.md`, `results_console/src/components/TaskTable.tsx`) | 후보는 회사별 검증 과제나 customer-verified task가 아니다. 현재 dataset에 적용 가능한지는 사용자가 판단하며 `VERIFIED_BUSINESS_TASK`는 `NOT_ONBOARDED`다. (출처: `docs/ARCHITECTURE.md`, `docs/DATA_AND_PRIVACY.md`, `results_console/src/components/TaskTable.tsx`) |
| **06 / 근거 검사** | 판정 라벨, 인용·일치·미확인 source ID, 계산 상세, 검사 응답, Delivery SHA-256, 검사 한계를 본다. (출처: `results_console/src/components/EvidenceCheckPanel.tsx`) | `DeliveryEnvelope.source_link_status`와 별개인 검사다. 404는 “근거 검사 결과 없음”이지 실행 실패·오답 판정이 아니며, Evidence Checker가 delivery를 수정하지도 않는다. (출처: `results_console/src/components/EvidenceCheckPanel.tsx`, `results_console/README.md`) |

데이터셋 전환, 기존 run ID 조회, 새 질문 실행은 **07 / 조회와 실행**에서 한다. read-only 데모에서는 조회만 가능하고 실행 요청은 의도적으로 거부된다. (출처: `results_console/src/components/Sidebar.tsx`, `results_console/src/components/RunControls.tsx`, `SUBMISSION.md`)

## 8. 로컬 실행 방법

### 검증된 환경

최종 검증 환경은 **Windows 11 + PowerShell + Python 3.12 + Node.js**이며, 실행 요구 버전은 Python 3.12+와 Node.js 20+다. macOS/Linux/WSL 명령은 제공되지만 최종 감사에서 실행 검증되지는 않았다. (출처: `SUBMISSION.md`, `README.md`)

### read-only frozen v4 데모

저장소 루트의 첫 번째 PowerShell에서 다음을 실행한다. (출처: `SUBMISSION.md`)

```powershell
python -m pip install -r requirements.txt
$env:AX_PRODUCT_FROZEN_RESULTS_ROOT = "artifacts/phase6_product_demo_v4/runs"
python -m uvicorn ax_product.api:create_read_only_app_from_env --factory --host 127.0.0.1 --port 8000
```

두 번째 PowerShell에서 다음을 실행한다. (출처: `SUBMISSION.md`)

```powershell
cd results_console
npm ci
npm run dev -- --port 5173
```

브라우저에서 `http://127.0.0.1:5173/`을 연다. read-only factory는 frozen manifest를 검증하고 runner 없이 시작하므로 `POST /api/run`은 HTTP 503을 반환하며 동결 결과를 수정하지 않는다. (출처: `SUBMISSION.md`, `docs/ARCHITECTURE.md`)

### 라이브 Kiro 실행

라이브 실행은 Kiro CLI가 `PATH`에 있거나 `AX_KIRO_CLI`에 실행 파일 경로가 설정되어 있고, 사용 가능한 모델 자격 증명이 있는 환경에서만 opt-in한다. (출처: `README.md`)

```powershell
$env:AX_PRODUCT_RUNNER = "kiro"
$env:AX_PRODUCT_RUN_TIMEOUT_SECONDS = "300"
python -m uvicorn ax_product.api:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

위 명령의 timeout 값은 300초이며, 라이브 실행 결과는 기본적으로 `artifacts/product_runs/<run_id>/`에 기록된다. 모듈 기본값 `ax_product.api:app`과 read-only factory에는 runner가 연결되지 않아 실행 요청이 503을 반환한다. (출처: `README.md`, `docs/ARCHITECTURE.md`)

## 9. 하면 안 되는 주장 목록

| 금지 주장 | 안전한 표현 |
|---|---|
| “모든 데이터와 AI 처리가 완전히 로컬이며 원문이 외부 모델 경계로 나가지 않는다.” | 문서 접근과 산출물 저장은 로컬 경로에서 통제하지만, 도구가 반환한 데이터는 설정된 모델 실행 경계로 전달된다. 문서 읽기와 크기에 따라 원문 상당량이 반환될 수 있으며 공급자별 보존·학습·지역 정책은 별도 확인해야 한다. (출처: `docs/DATA_AND_PRIVACY.md`) |
| “AX가 충돌한 문서를 자동으로 수정한다.” | 현재 product agent에 열거된 도구는 4개 읽기·조회 도구와 `submit_answer`뿐이며 문서 쓰기 도구가 없다. AX는 수정 대상과 권고 조치를 제시하고, 수정 후 동일 업무를 재검증한다. (출처: `docs/ARCHITECTURE.md`, `results_console/src/components/FindingCard.tsx`, `docs/DEMO_SCRIPT.md`) |
| “v4 수치는 정확도 benchmark, 고객 검증 성능, 또는 무작위 대조 실험 결과다.” | v4는 30파일·10업무·2상태를 각 3회 실행한 탐색 snapshot이다. (출처: `SUBMISSION.md`) |
| “After가 전체적으로 개선됐고 그 차이는 FAQ 수정의 인과 효과다.” | 전체 차이의 인과 효과는 주장하지 않으며, 직접 수정한 반품 업무의 0/3→3/3 전환만 좁게 설명한다. (출처: `SUBMISSION.md`, `docs/PHASE6_V4.md`) |
| “`DIRECT_MATCH`는 업무 정답이고 `UNCONFIRMED`는 오답이다.” | `DIRECT_MATCH`는 인용된 같은-run 구조화 응답과 답 값의 일치이고, `UNCONFIRMED`는 자동 확인 범위 밖이라는 뜻이다. (출처: `SUBMISSION.md`, `docs/EVIDENCE_CHECKER_V3.md`) |
| “Readiness 100이면 실제 업무도 성공한다.” | 정적 Readiness와 업무 성공은 별도 신호이며 서로를 보장하거나 다시 계산하지 않는다. (출처: `docs/ARCHITECTURE.md`, `docs/DEMO_SCRIPT.md`) |
| “에이전트의 자연어 최종 답변이 제품의 권위 있는 결과다.” | 첫 유효 `SubmitAnswerInput`과 저장된 `DeliveryEnvelope`만 권위 있는 결과이며 assistant prose·stdout·Kiro `finalText`는 제품 답이 아니다. (출처: `docs/ARCHITECTURE.md`, `SUBMISSION.md`) |
| “제품 기본 업무 10개는 고객이 검증한 업무 catalog다.” | 10개는 제품이 제공하는 일반 업무 후보이고 `VERIFIED_BUSINESS_TASK`는 `NOT_ONBOARDED`다. (출처: `docs/ARCHITECTURE.md`, `docs/DATA_AND_PRIVACY.md`) |
| “개인정보 패턴 탐지가 완전한 마스킹·유출 방지·접근 통제를 제공한다.” | 개인정보 패턴 탐지는 readiness 신호일 뿐 완전한 탐지나 보안 통제가 아니다. (출처: `docs/DATA_AND_PRIVACY.md`) |
| “현재 구현은 프로덕션 보안과 규제 준수를 보장한다.” | API 인증, 사용자별 접근 제어, tenant 격리, 역할 기반 권한, retention·삭제·복구, TLS, secret manager, 중앙 감사 로그 등이 아직 제품화되지 않았다. (출처: `docs/DATA_AND_PRIVACY.md`) |
| “read-only 데모에서 새 Kiro 실행이 가능하다.” | read-only factory는 runner 없이 frozen 결과만 조회하며 `POST /api/run`을 의도적으로 503으로 거부한다. (출처: `SUBMISSION.md`, `docs/ARCHITECTURE.md`) |
| “macOS/Linux/WSL에서도 최종 검증이 끝났다.” | 이식용 명령은 제공되지만 최종 감사에서 검증된 OS는 Windows 11이다. (출처: `SUBMISSION.md`, `README.md`) |

## 10. 현재 `results_console`의 디자인 토큰

### CSS custom properties와 색상

현재 `:root`에 정의된 custom property는 색상 15개이며, 폰트와 간격용 custom property는 없다. (출처: `results_console/src/style.css`)

| 역할 | 변수와 값 | 출처 |
|---|---|---|
| 기본 잉크·규칙 | `--color-ink: #0A1E3D`, `--color-rule-strong: #0A1E3D` | (출처: `results_console/src/style.css`) |
| 주 강조 | `--color-accent: #0F62FE` | (출처: `results_console/src/style.css`) |
| 보조 텍스트 | `--color-sub: #35506E`, `--color-muted: #58748F`, `--color-faint: #8FA3BC` | (출처: `results_console/src/style.css`) |
| 선·약한 규칙 | `--color-line: #C3D6E8`, `--color-line-light: #DFEAF4`, `--color-rule-soft: #DFEAF4` | (출처: `results_console/src/style.css`) |
| 표면·배경 | `--color-surface: #EEF4FA`, `--color-bg: #FFFFFF` | (출처: `results_console/src/style.css`) |
| 경고 | `--color-warn: #C43F5B` | (출처: `results_console/src/style.css`) |
| evidence용 정의값 | `--color-evidence-bg: #0A1E3D`, `--color-evidence-label: #93AAC8`, `--color-evidence-link: #7CC0F5` | (출처: `results_console/src/style.css`) |

### 폰트와 타이포그래피

- 본문 스택은 `IBM Plex Sans` → `Pretendard Variable`/`Pretendard` → `Noto Sans KR` → `Malgun Gothic` → `Apple SD Gothic Neo` → system sans-serif 순서다. `IBM Plex Sans`와 `IBM Plex Mono`는 Google Fonts, Pretendard Variable은 jsDelivr import를 사용한다. (출처: `results_console/src/style.css`)
- 숫자·코드·section index·감사 정보는 `IBM Plex Mono`를 사용하고 tabular numerals를 켠다. (출처: `results_console/src/style.css`)
- body 기본값은 14px, line-height 1.5이며, section heading은 24px, 보조 label은 주로 10–11px, 핵심 지표는 `clamp(34px, 4vw, 52px)` 또는 `clamp(42px, 5vw, 68px)`를 쓴다. (출처: `results_console/src/style.css`)

### 간격·레이아웃

- 간격 토큰은 custom property로 추상화되어 있지 않다. 반복되는 실제 값은 8·10·12·14·16·18·20·24·28·30·32·36·40·48·56·64·72px 계열이며, 새 페이지가 같은 톤을 유지하려면 이 기존 간격 계열을 우선 재사용한다. (출처: `results_console/src/style.css`)
- desktop shell은 280px sidebar와 나머지 report 영역으로 나뉘며, report content의 최대 폭은 1180px이다. main padding은 `56px 64px 32px 96px`, 일반 section의 상단 padding은 72px이다. (출처: `results_console/src/style.css`, `results_console/README.md`)
- 1024px 이하에서는 sidebar가 상단으로 이동하고, 768px 이하에서는 단일 열 중심으로 바뀌며, 520px 이하에서 세부 control을 다시 쌓는다. 별도로 관리자 1페이지 일부는 760px 이하에서 단일 열이 된다. (출처: `results_console/src/style.css`)
- 최소 viewport 폭은 320px이고 `prefers-reduced-motion`에서 애니메이션·transition 시간을 사실상 제거한다. (출처: `results_console/src/style.css`)

### 주요 컴포넌트 스타일

- 전체 톤은 흰 배경, 짙은 네이비 본문, 코발트 blue 강조, raspberry 경고, 연한 blue-gray surface, 1–2px 규칙선 중심이다. 버튼·입력·링크의 `border-radius`는 0이고 stylesheet에 `box-shadow` 선언은 없다. (출처: `results_console/src/style.css`)
- sidebar는 `AX / Results Console` wordmark, report tab, 01–07 anchor 목차, dataset·기준일, 접힌 감사 정보로 구성된다. (출처: `results_console/src/components/Sidebar.tsx`)
- 요약은 큰 숫자와 3열 diagnostic grid, 왼쪽 2px accent rule의 현재 실행 결과를 사용한다. (출처: `results_console/src/components/SummarySection.tsx`, `results_console/src/style.css`)
- 관리자 1페이지는 1px strong border, 3열 metric, 반품 전후 3개 quote, 우선 검토 목록, A4 print stylesheet를 사용한다. (출처: `results_console/src/components/ExecutiveReport.tsx`, `results_console/src/style.css`)
- Finding·Readiness는 전체 카드 배경이나 그림자보다 선, 여백, 접기/펼치기 행으로 계층을 만든다. 충돌 근거는 경고 border와 `#fffaf0`, 수정 후 원문은 accent border와 `--color-surface`로 구분한다. (출처: `results_console/src/components/FindingCard.tsx`, `results_console/src/components/ReadinessTable.tsx`, `results_console/src/style.css`)
- status는 pill이 아니라 2px 세로선과 mono label이며, positive와 blue는 accent color, warning과 danger는 warning color를 공유한다. (출처: `results_console/src/components/Status.tsx`, `results_console/src/style.css`)
- 새 소개·사용 방법 페이지도 **각진 모서리, 무그림자, 얇은 규칙선, 큰 숫자 대비, mono micro-label, navy/cobalt/raspberry 팔레트**를 유지하는 것이 현재 콘솔과 가장 직접적으로 연결되는 시각 지침이다. (근거: `results_console/src/style.css`)

### 프레임워크와 라우팅 방식

- frontend는 React 19.2.8, React DOM 19.2.8, TypeScript 5.9.3, Vite 8.2.2를 사용한다. (출처: `results_console/package.json`)
- `main.tsx`가 단일 `#root`에 `App`을 렌더링하며 React Router 같은 routing dependency는 없다. 현재 탐색은 `App`의 local state로 report/benchmark tab을 바꾸고 sidebar의 `#summary` 같은 in-page anchor로 section을 이동하는 방식이다. (출처: `results_console/src/main.tsx`, `results_console/src/App.tsx`, `results_console/src/components/Sidebar.tsx`, `results_console/package.json`)
- URL query는 개발 빌드의 `?fixture=...` 화면 상태에만 사용되고 production build에서는 fixture switch가 없다. (출처: `results_console/src/App.tsx`, `results_console/README.md`)
- Vite dev server는 `/api`를 기본 `http://127.0.0.1:8000`으로 proxy한다. (출처: `results_console/vite.config.ts`)
- 새 소개 페이지와 사용 방법 페이지의 실제 URL, 다중 페이지 구조, router 도입 여부는 현재 저장소에서 **미확인**이다. 현재 구현에는 해당 route가 없다. (출처: `results_console/src/App.tsx`, `results_console/package.json`)

## 11. 알려진 이슈

### 주문 원장 테이블 검색 노출 문제 — 확인 결과

- 원본 파일은 `04_주문/주문_원장_2026.xlsx`, file ID는 `FILE_950a2b2ed909ef4c`다. scanner는 이를 `PARSED`로 기록하고 11,020자의 표 텍스트와 180개 행을 추출했으며, 구조화 테이블 `TABLE_FILE_950a2b2ed909ef4c_Orders`도 존재한다. (출처: `docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md`)
- 답변에 성공한 실행은 이 테이블에서 최근 주문일 `2026-09-21`과 9월 주문금액 합계 `4,980,700원`을 조회했다. 따라서 표 파일·Orders 테이블 부재나 인덱싱 누락이 원인이 아니다. (출처: `docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md`)
- 정책 기준명 `주문원장_2026`과 실제 파일명 `주문_원장_2026.xlsx`는 tokenizer가 공백·밑줄을 제거해 같은 검색 형태가 되므로 파일명 불일치도 원인이 아니다. (출처: `docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md`)
- 현재 검색은 파일명과 본문을 합친 char 2·3-gram BM25다. 정확한 `주문원장_2026` 검색에서도 원장은 4위였고, `가장 최근 주문`·`이번 달 주문금액` 같은 업무 문장 검색에서는 상위 10개 밖으로 밀렸다. 실행별 query wording과 `top_k` 차이로 원장을 발견한 실행만 `query_table`까지 도달했다. (출처: `docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md`, `docs/DEMO_SCRIPT.md`)
- frozen After에서 “가장 최근 주문”은 답변 1회·보류 2회, “이번 달 주문금액”은 답변 2회·보류 1회였다. 두 Finding은 `MISSING_INFORMATION`이 아니라 `MIXED_OUTCOMES`이며 원인 귀속은 `RETRIEVAL_LIMITATION`, UI 라벨은 **검색 경로 한계 확인**이다. (출처: `docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md`, `results_console/src/components/FindingCard.tsx`)
- 제안된 조치는 기준 원장을 table ID 또는 관리 별칭으로 직접 연결하고, 파일명 exact-match boost나 표 제목 전용 검색 필드를 두며, top-k 밖 기준 자료를 위한 query 확장·구조화 자료 목록 조회를 제공한 뒤 같은 질문·설정으로 3회 이상 재실행하는 것이다. 이 조치는 아직 구현 완료로 확인되지 않았으므로 상태는 **미확인**이다. (출처: `docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md`)

### 함께 고려할 현재 제약

- 실행기 상태 조회 API가 없고 기본 실행 API는 동기식이며, 여러 업무를 한 번에 예약·추적하는 비동기 batch orchestration은 구현되지 않았다. (출처: `results_console/src/components/RunControls.tsx`, `README.md`)
- 현재 readiness API는 점수 차원별 개별 파일 목록과 observation-to-dimension 연결 정보를 제공하지 않는다. (출처: `results_console/src/components/ReadinessTable.tsx`, `results_console/README.md`)
- 인증·사용자별 접근 제어·tenant 분리·장기 보존과 삭제 정책 등 프로덕션 통제는 구현되지 않았다. (출처: `docs/DATA_AND_PRIVACY.md`)
- 소개 페이지와 사용 방법 페이지의 route, 정보 구조, CTA의 최종 목적지는 현재 코드와 문서에서 **미확인**이다. 디자인 산출물은 이를 확정 사실로 가정하지 않아야 한다. (출처: `results_console/src/App.tsx`, `results_console/package.json`)
