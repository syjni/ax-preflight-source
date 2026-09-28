# AX 데이터 준비도 진단 서비스 — Project Plan v3

## 0. 문서 목적

이 문서는 고려대학교 × AWS AI Innovators Challenge 출품을 목표로 하는 **AX 데이터 준비도 진단 서비스**의 실제 구현 및 평가 계획을 정의한다.

v3에서는 이전 버전의 핵심 컨셉을 유지하되, 다음 문제를 보완한다.

- remediation이 defect injection의 역함수가 되는 순환 논리 제거
- cross-file task를 위한 명시적 도구 설계
- LLM 호출량 및 비용 예산화
- counterfactual diagnosis 구현 단순화
- 복합 실패 대신 primary blocker 중심 MVP 평가
- control task 보호 장치
- 실험 결과와 engineering success criteria 분리
- mini end-to-end 실험을 일정 전반부로 이동
- 한국어 검색 기본 구현을 char n-gram BM25로 고정
- 합성 데이터의 현실성 보강
- 중소기업 인터뷰 재포함
- 제출 요건 및 심사 기준 대응 명시

프로젝트의 핵심은 단순한 데이터 품질 점검이 아니라, 기업이 보유한 실제 자료만으로 **AI가 신입사원처럼 업무를 수행할 수 있는지 검증하고**, 실패 원인을 조건을 바꾼 재실험으로 진단한 뒤, 탐지된 문제만을 근거로 개선하고 다시 측정하는 것이다.

---

# 1. 프로젝트 개요

## 1.1 한 줄 정의

중소기업의 PC와 공유 폴더에 흩어진 자료를 분석하여 AI 활용 가능성을 진단하고, **AI를 가상의 신입사원으로 투입해 실제 업무 질문을 수행하게 한 뒤**, 무엇이 부족한지와 무엇을 고치면 업무 성공률이 얼마나 개선되는지를 보여주는 서비스.

## 1.2 핵심 질문

> "지금 우리 회사 자료만 가지고 AI 직원이 실제로 일을 할 수 있는가?"

본 프로젝트는 readiness를 단일 추상 점수보다 **실제 업무 Task 수행 성공률과 실패 원인**으로 보여준다.

## 1.3 핵심 흐름

```text
Company Data
      ↓
Readiness Scan
      ↓
AI Employee Benchmark
      ↓
Failure
      ↓
Counterfactual Diagnosis
      ↓
diagnosis_report.json
      ↓
Report-driven Remediation
      ↓
Re-test
      ↓
Compare with Ceiling
```

---

# 2. 문제 정의

## 2.1 타깃 사용자

- 직원 20~100명 규모 중소기업
- 제조·유통·서비스업
- 전담 데이터팀/AI팀이 없음
- AI 도입 의사는 있으나 데이터 상태를 파악하기 어려움
- 자료가 NAS, 개인 PC, 공유폴더, Excel/CSV, PDF에 흩어져 있음

대표 사용자:

- 경영지원 담당자
- 운영팀장
- 영업관리 담당자
- 대표/실무 책임자

## 2.2 현실적인 데이터 문제

| 위치 | 문제 |
|---|---|
| 개인 PC | 담당자만 위치를 알고 있음 |
| 공유 폴더/NAS | 폴더 구조와 파일명이 비일관적 |
| 메일·메신저 첨부 | 최신본이 첨부파일에만 남음 |
| ERP/쇼핑몰 | 내려받은 CSV가 다시 파편화됨 |
| 종이/스캔 PDF | 텍스트로 바로 사용 불가 |

대표 증상:

- `최종.xlsx`, `최종_진짜최종.xlsx`
- 동일 거래처의 다양한 표기
- 오래된 정책/가격표
- 병합셀, 다중 헤더, 소계 행
- 개인정보 포함
- 스캔 PDF
- authoritative version 불명
- cross-file key 불일치

---

# 3. 프로젝트 가설

## H1. 기업은 현재 보유 데이터의 AI 활용 가능성을 스스로 정확히 판단하기 어렵다.

## H2. 데이터 준비도는 추상 점수보다 실제 업무 성공률로 보여주는 것이 이해하기 쉽다.

## H3. Before / After / Ceiling 조건에서 동일 Task를 반복 실행하면 데이터 개선 효과를 더 신뢰성 있게 측정할 수 있다.

## H4. 실패 원인은 LLM의 설명만으로 추정하지 않고, 한 조건씩 정상 상태로 바꾸어 재실행하는 counterfactual diagnosis로 구분할 수 있다.

## H5. remediation이 진단 결과만을 입력으로 받아야 실제 진단 성능이 Recovery Ratio에 반영된다.

---

# 4. 핵심 제품 컨셉 — AI 신입사원 입사 테스트

## 4.1 개념

기업 데이터를 AI 신입사원에게 제공되는 업무 자료로 본다.

AI Agent가 실제 신입사원이 받을 법한 질문을 수행한다.

예:

- 반품 규정은 어떻게 되나요?
- 한빛상사의 지난달 주문액은 얼마인가요?
- 가장 최근 배송 정책은 무엇인가요?
- 특정 거래처의 마지막 주문일은 언제인가요?
- 반품률이 가장 높은 상품은 무엇인가요?

## 4.2 결과 예시

```text
AI Employee Test

Knowledge Q&A     5 / 8
Operations Q&A    2 / 7
Cross-file Tasks  0 / 5

Total             7 / 20
```

실패 원인:

```text
Missing Data           5
Version Ambiguity      4
Unreadable Source      2
Privacy Block          1
Retrieval Failure      1
Agent Failure          0
```

---

# 5. 실험 설계

## 5.1 세 가지 Dataset Condition

### Ceiling

결함이 없는 이상적인 기준 데이터셋.

- 필요한 파일 존재
- authoritative version 명확
- 정상 schema
- 읽을 수 있는 텍스트
- benchmark 수행에 필요한 key 존재

### Before

Ceiling에 defect injection script를 적용한 상태.

### After

Before에 대해 시스템이 생성한 `diagnosis_report.json`만을 입력으로 remediation을 수행한 상태.

중요:

```text
remediate.py가 읽을 수 있음
✓ diagnosis_report.json
✓ Before dataset

읽을 수 없음
✗ injected_defects.json
✗ Ceiling ground truth
✗ benchmark known_blockers
```

즉, 시스템이 탐지하지 못한 문제는 After에도 남는다.

---

## 5.2 Recovery Ratio

```text
Recovery Ratio
= (After - Before) / (Ceiling - Before)
```

이 값은 목표치가 아니라 **실험 결과로 보고**한다.

---

## 5.3 Defect Detection Coverage

추가 보고:

```text
Injected Defects
Detected Defects
Remediated Defects
Missed Defects
```

예:

```text
Injected    12
Detected     9
Remediated   8
Missed       3
```

---

## 5.4 Control Tasks

총 20개 중 약 5개를 control task로 둔다.

Control task의 required source는 defect injection 대상에서 보호한다.

주입 스크립트는 다음을 강제한다.

```text
protected_sources
=
모든 control task의 required_sources 합집합
```

주입 후:

```text
SHA256(control source before)
==
SHA256(control source after)
```

를 assert 한다.

---

## 5.5 반복 실행

동일 Task를 각 조건에서 3회 실행한다.

API 제한이 심한 경우 2회로 자동 축소한다.

보고:

```text
Before   mean ± std
After    mean ± std
Ceiling  mean ± std
```

---

## 5.6 Benchmark 작성 순서

순환 논리 완화를 위해:

```text
1. Ceiling dataset 생성
2. Benchmark Task 작성
3. Ground Truth 확정
4. 이후 Defect Injection
5. Before 생성
```

가능하면 외부 인원 1명이 일부 Task를 별도로 작성한다.

---

# 6. Remediation 설계

## 6.1 원칙

Remediation은 injected defect ground truth를 직접 보지 않는다.

입력은 오직:

```text
diagnosis_report.json
```

이다.

## 6.2 예시

`diagnosis_report.json`

```json
{
  "issues": [
    {
      "type": "VERSION_AMBIGUITY",
      "target": "반품정책",
      "evidence": [
        "반품정책_2024.pdf",
        "반품정책_최종.pdf"
      ],
      "suggested_action": "select_authoritative_version"
    }
  ]
}
```

`remediate.py`

```text
VERSION_AMBIGUITY
→ authoritative_version policy 적용

SCHEMA_MISMATCH
→ column normalization rule 적용

DUPLICATE
→ duplicate copy 제외

PII_RISK
→ masked copy 생성
```

## 6.3 자동 remediation 범위

MVP에서 자동 적용:

- exact duplicate 제외
- known alias column rename
- canonical value normalization
- authoritative version 선택 규칙
- masked copy 생성

MVP에서 recommendation만 제공:

- missing source 확보
- OCR 수행
- 새로운 데이터 수집
- 사람의 최신본 확인이 필요한 경우

---

# 7. MVP 범위

## 7.1 P0 — 반드시 구현

### Scanner

- recursive folder scan
- metadata
- SHA-256 exact duplicate
- probable version grouping
- TXT/PDF/DOCX/CSV/XLSX parsing
- spreadsheet profiling
- PII detection/masking
- scan PDF detection

### Retrieval

- char 2~3-gram 기반 BM25
- Recall@1 / @3 / @5 평가

### Readiness Engine

- document/table classification
- use-case requirement profile
- blocker detection
- deterministic rules

### AI Employee Agent

Tools:

- `search_documents`
- `read_document`
- `query_table`
- `lookup_value`

### Evaluation

- 15~20 benchmark tasks
- control tasks
- Before / After / Ceiling
- repeated runs
- counterfactual diagnosis
- report-driven remediation
- failure attribution
- Recovery Ratio

### Outputs

JSON artifacts:

- `scan_report.json`
- `benchmark_results.json`
- `diagnosis_report.json`
- `comparison_report.json`

### Dashboard

최종 화면 3개:

1. Scan Results
2. AI Employee Test
3. Before / After / Ceiling

---

## 7.2 P1 — 시간 남으면

- column semantic mapping
- HWPX
- advanced near-duplicate
- advanced spreadsheet understanding
- cost dashboard
- richer recommendation
- benchmark task editor
- Kiwi tokenizer

---

## 7.3 예선에서 하지 않는 것

- ERP 직접 연동
- 메일/메신저 연동
- Drive/SharePoint 직접 연동
- legacy HWP 완전 지원
- 자동 OCR
- multi-user RBAC
- 자동 파일 재구성
- general entity resolution
- production ontology
- 수요 예측
- vector DB
- multi-agent
- shell execution

---

# 8. Use Case

## 8.1 사내 지식 Q&A

대상:

- 정책 문서
- 업무 매뉴얼
- 회의록
- 배송/반품 규정

## 8.2 영업·운영 데이터 Q&A

대상:

- 주문
- 거래처
- 상품
- 재고

## 8.3 Cross-file Q&A

예:

```text
"한빛상사의 2026년 8월 주문액은?"
```

흐름:

```text
lookup_value(customers, customer_name="한빛상사")
→ customer_id=C013

query_table(orders, customer_id=C013, month=2026-08)
→ amount sum
```

cross-file task는 Agent가 raw row를 읽고 머릿속으로 join하지 않도록 tool 설계로 지원한다.

---

# 9. 기능 요구사항

## FR-01 Folder Scan

지정 폴더 재귀 탐색.

## FR-02 Metadata Extraction

- path
- filename
- extension
- size
- modified_at
- hash

## FR-03 Exact Duplicate

SHA-256 기반.

## FR-04 Version Grouping

파일명 패턴과 similarity 기반.

## FR-05 Parsing

- TXT
- PDF
- DOCX
- CSV
- XLSX

## FR-06 HWP Policy

- `.hwpx`: P1
- `.hwp`: `UNSUPPORTED_LEGACY_FORMAT`

## FR-07 Scan Detection

text layer 부족 → `OCR_REQUIRED`

## FR-08 PII Detection

- 주민번호 패턴
- 전화번호
- 계좌번호 후보
- 이메일

## FR-09 PII Masking

클라우드 전송 전 로컬 마스킹.

## FR-10 Spreadsheet Profiling

- data type
- null ratio
- unique ratio
- sample
- merged cells
- row/column count

## FR-11 Canonical Normalization

- `(주)`
- `주식회사`
- 공백
- punctuation
- lowercase
- Unicode normalize

## FR-12 Retrieval

char n-gram BM25.

## FR-13 Use-case Requirement Evaluation

profile 기반 blocker 탐지.

## FR-14 AI Employee Execution

tool 기반 업무 수행.

## FR-15 Failure Attribution

single primary blocker 반환.

## FR-16 Report-driven Remediation

diagnosis report에 나타난 issue만 remediation 대상으로 사용.

## FR-17 Comparison

Before / After / Ceiling 비교.

---

# 10. 비기능 요구사항

## NFR-01 Privacy

원본 디렉터리 전체의 업로드와 영구 저장을 피한다.

필요한 최소한의 masked snippet, row, metadata만 클라우드 LLM에 전송한다.

### 한계

규칙 기반 PII detection은 모든 민감정보 제거를 보장하지 않는다.

privacy counterfactual 실험에서 unmasked synthetic fixture를 사용하는 경우는 **합성 데이터 실험에 한정**한다.

실제 서비스에서는 이러한 진단은 사용자 동의 하에 로컬 환경에서만 수행하는 방향을 목표로 한다.

## NFR-02 Explainability

모든 판정에 evidence를 남긴다.

## NFR-03 Determinism

계산 가능한 판단은 코드가 수행한다.

## NFR-04 Cost Control

LLM 호출 budget 적용.

## NFR-05 Model Replaceability

provider adapter.

## NFR-06 Reproducibility

dataset, injection, remediation, benchmark 모두 script 기반.

## NFR-07 Retrieval Accountability

Agent failure와 retrieval failure를 분리 측정.

---

# 11. 시스템 아키텍처

```text
┌──────────────────────────────┐
│       Customer Environment   │
│                              │
│ Local Scanner                │
│ ├─ crawler                   │
│ ├─ metadata/hash             │
│ ├─ parser                    │
│ ├─ PII detector              │
│ ├─ spreadsheet profiler      │
│ ├─ canonical normalizer      │
│ └─ char n-gram BM25          │
│                              │
│       ▲ Tool Request         │
│       │                      │
│       ▼ Masked Evidence      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│             AWS              │
│                              │
│ Backend API                  │
│                              │
│ Readiness Engine             │
│ ├─ deterministic rules       │
│ ├─ use-case profiles         │
│ └─ LLM semantic analysis     │
│                              │
│ AI Employee Agent            │
│ ├─ search_documents          │
│ ├─ read_document             │
│ ├─ query_table               │
│ └─ lookup_value              │
│                              │
│ Diagnostic Engine            │
│ ├─ counterfactual repair     │
│ └─ primary blocker           │
│                              │
│ Evaluation Engine            │
│ ├─ retrieval metrics         │
│ ├─ task success              │
│ ├─ control stability         │
│ └─ Before/After/Ceiling      │
└──────────────┬───────────────┘
               ▼
        JSON Reports
               ↓
         Web Dashboard
```

---

# 12. 검색 설계

## 기본 방식

MVP:

```text
char 2~3 gram
+
BM25
```

Kiwi는 P1.

## 초기 실험

다음 두 방식만 비교:

- whitespace token BM25
- char n-gram BM25

Recall@5가 더 높은 방식을 채택한다.

## 평가

- Recall@1
- Recall@3
- Recall@5

required_sources를 ground truth로 사용.

---

# 13. Agent Tool Specification

## search_documents

```text
search_documents(query, top_k)
```

## read_document

```text
read_document(document_id, section=None)
```

## query_table

```text
query_table(
    table_id,
    filters,
    select,
    aggregation=None
)
```

## lookup_value

```text
lookup_value(
    table_id,
    match_column,
    value,
    return_column
)
```

예:

```text
lookup_value(
    "customers",
    "customer_name",
    "한빛상사",
    "customer_id"
)
```

반환:

```text
C013
```

이후 `query_table`로 cross-file task 수행.

MVP에서는 join SQL tool을 직접 제공하지 않는다.

---

# 14. Counterfactual Failure Attribution

## 14.1 원칙

Task마다 MVP에서는 하나의 `primary_blocker`만 평가한다.

복합 failure는 본선 확장으로 남긴다.

가능한 한 benchmark 설계 자체도:

```text
1 defect-sensitive task
↔
1 primary blocker
```

로 구성한다.

## 14.2 단일 Counterfactual Mechanism

별도 privacy/version/schema fixture 함수를 만들지 않는다.

공통 함수:

```text
rerun_with_repaired_dimension(task, dimension)
```

이 함수는 해당 dimension에 필요한 source만 Ceiling equivalent로 임시 교체한다.

예:

- retrieval
- privacy
- version
- schema
- readability

## 14.3 Decision Flow

```text
TASK FAIL
 │
 ├─ required source 없음
 │      └─ missing_data
 │
 ├─ retrieval dimension repair → PASS
 │      └─ retrieval_failure
 │
 ├─ version dimension repair → PASS
 │      └─ version_ambiguity
 │
 ├─ schema dimension repair → PASS
 │      └─ schema_mismatch
 │
 ├─ privacy dimension repair → PASS
 │      └─ privacy_block
 │
 ├─ readability dimension repair → PASS
 │      └─ unreadable_source
 │
 └─ 모두 FAIL
        └─ agent_failure
```

## 14.4 역할 분리

Failure classification:

```text
Code / Diagnostic Engine
```

Explanation:

```text
LLM
```

---

# 15. LLM 호출 예산

## 15.1 원칙

최종 반복 실험 전에 mini benchmark로 다음을 측정한다.

- 평균 LLM calls per task
- 평균 tool calls per task
- 평균 input tokens
- 평균 output tokens
- 평균 latency

## 15.2 예상식

예:

```text
20 tasks
× 3 conditions
× 3 repetitions
× avg_calls_per_task
```

Counterfactual diagnosis는 **각 task의 최초 1회 실행에 대해서만 수행**한다.

반복 실행은 성공률/변동성 측정용이며 진단을 반복하지 않는다.

## 15.3 Cache

다음은 캐시한다.

- retrieval result
- parsed document profile
- table profile
- diagnostic result
- repaired dimension fixture

## 15.4 Budget Policy

예시:

```text
MAX_LLM_CALLS = 실제 API 제한 확인 후 설정
```

정책:

```text
80% budget 도달
→ repetitions 3 → 2

95% budget 도달
→ non-critical diagnostic rerun 중단
```

호출 상한은 9/18 실험 결과로 확정한다.

---

# 16. Synthetic Company Dataset

## 한빛유통

- 중소 유통업
- 직원 약 45명

구조:

```text
HANBIT_CLEAN/
├─ 영업/
├─ 상품/
├─ 인사/
├─ 규정/
└─ 회의/
```

## 현실성 보강

회사명과 문서 구조는 synthetic하게 만들되, 다음 수치 분포는 가능한 한 공개 데이터에서 가져온다.

- 주문량
- 가격
- 상품 종류
- 주문 날짜 분포
- 재고 수준

즉:

> Synthetic company structure + real-world-derived numeric distribution

방식을 사용한다.

사용 공개 데이터셋의 출처와 라이선스는 README에 기록한다.

---

# 17. Defect Injection

지원 defect:

```text
D01 Exact Duplicate
D02 Version Conflict
D03 Missing Source
D04 Schema Mismatch
D05 PII
D06 Scanned PDF
D07 Stale Document
D08 Column Alias
D09 High Null Ratio
D10 Cross-file Key Mismatch
```

Injection script는 control task의 required source를 수정하지 못한다.

---

# 18. Benchmark Task

총 20개 목표.

- Knowledge Q&A: 7
- Operations Q&A: 7
- Cross-file: 6

이 중 control task 약 5개.

예:

```json
{
  "task_id": "T07",
  "question": "한빛상사의 2026년 8월 주문액은 얼마인가?",
  "expected_answer": 12450000,
  "required_sources": [
    "거래처목록.xlsx",
    "주문_2026.xlsx"
  ],
  "primary_blocker": "schema_mismatch",
  "control": false
}
```

복합 blocker task는 최소화한다.

---

# 19. 평가 지표

## Scanner

- Exact duplicate Precision / Recall / F1
- Version grouping F1
- PII Precision / Recall / F1

## Retrieval

- Recall@1
- Recall@3
- Recall@5

## Agent

- Task Success Rate
- Mean ± Std
- Control Task Stability

## Failure Attribution

- Primary blocker accuracy

## Diagnosis Coverage

- Injected defects
- Detected defects
- Missed defects

## Closed-loop Result

다음은 **목표치가 아니라 결과로 보고**한다.

- Before → After delta
- Recovery Ratio
- Ceiling gap

## Efficiency

- scan time
- LLM calls
- token usage
- estimated cost
- latency

---

# 20. Engineering Acceptance Criteria

실험 결과가 아니라 시스템 자체 품질 기준이다.

| Metric | Minimum | Target |
|---|---:|---:|
| Exact duplicate F1 | 0.95 | 1.00 |
| PII Recall | 0.85 | 0.95 |
| Version grouping F1 | 0.75 | 0.85 |
| Retrieval Recall@5 | 0.85 | 0.95 |
| Primary blocker accuracy | 0.75 | 0.90 |
| Control task variation | ±1 task | ±0.5 task |

다음은 Acceptance Criterion이 아니라 Reporting Metric이다.

- Recovery Ratio
- Before → After improvement
- Ceiling gap

---

# 21. 데이터 모델

## FileRecord

```text
file_id
path
filename
extension
size
hash
modified_at
file_type
scan_status
pii_status
```

## BenchmarkTask

```text
task_id
category
question
expected_answer
required_sources
primary_blocker
control
```

## TaskRun

```text
run_id
task_id
condition
repeat_index
answer
success
failure_code
sources_used
tool_trace
```

## DiagnosisReport

```text
issue_id
task_id
type
target
evidence
confidence
suggested_action
```

## ComparisonReport

```text
before_score
after_score
ceiling_score
recovery_ratio
control_stability
missed_defects
```

---

# 22. 대회 평가 기준 대응

| 평가 항목 | 대응 |
|---|---|
| 목적 부합성 10 | LLM을 실제 기업 데이터 활용성 진단과 업무 수행 검증에 활용 |
| 기술적 우월성 30 | Hybrid Rule+LLM, tool-using agent, counterfactual diagnosis, BM25 retrieval, reproducible benchmark |
| 서비스 활용성·완성도 30 | 중소기업 AI 도입 문제, scan→test→diagnose→remediate→retest end-to-end flow, dashboard |
| 데이터 활용성 10 | 현실 분포 기반 synthetic enterprise dataset, defect labels, benchmark ground truth, control tasks |
| 코드 품질 10 | scanner/agent/evaluator/remediation/provider 분리, JSON artifacts, reproducible scripts |

---

# 23. 경쟁 환경

## Data Catalog / Governance

- Microsoft Purview
- Collibra
- Atlan

본 프로젝트는 unmanaged local file environment와 task-based readiness에 초점.

## Sensitive Data Discovery

- AWS Macie

PII detection은 readiness blocker 중 하나.

## AI Data Readiness

- Snowflake AI-Ready Data Framework

본 프로젝트 차이:

- AI 도입 전 unmanaged data
- SME-first lightweight diagnosis
- 실제 AI Employee Task 수행
- counterfactual failure diagnosis
- report-driven remediation
- Before / After / Ceiling

## AX Consulting

본 프로젝트:

- 빠른 초기 technical diagnosis
- 반복 가능
- 재진단 가능

## 범용 AI Agent

차이:

- standardized benchmark
- repeatable evaluation
- task ground truth
- control tasks
- failure attribution
- recovery measurement

---

# 24. 사업 가설

## Entry

- 무료/저가 readiness scan
- 기본 AI Employee Test

## Paid

- 정기 재진단
- custom benchmark
- PoC 구축
- 데이터 정리 가이드

## Expansion

- data connector
- monitoring dashboard
- workflow automation
- lightweight ontology

가격은 인터뷰 전까지 가설로만 둔다.

---

# 25. 선행 확인 사항

## 사업단 확인

- 제공 LLM API
- 모델 목록
- 호출 제한
- 부가 AWS 서비스 사용 가능 여부
- 개인 참가 가능 여부
- 수업 과제 아이디어 출품 가능 여부
- 예선 심사 방식
- 제출물 형식
- 제출 마감 시각
- 데모 영상 요구 여부
- repository 공개 요구 여부

---

# 26. 인터뷰

9/21~9/22 사이 가능하면 중소기업 재직자 1명 이상 10~20분 인터뷰.

질문 예:

- 실제 공유폴더 구조가 얼마나 정돈돼 있는지
- `최종`, `진짜최종` 같은 파일명이 실제로 흔한지
- ERP 데이터를 Excel로 내려받아 쓰는지
- 최신본을 누가 확정하는지
- AI 도입에서 가장 막막한 것이 무엇인지
- 어떤 진단 결과라면 돈을 낼 가치가 있다고 느낄지

README에 3~5개 핵심 인사이트만 기록한다.

---

# 27. 구현 일정

## 9/18 — Feasibility Test

- mini clean dataset 10 files
- benchmark 5 tasks
- whitespace BM25 vs char n-gram BM25
- Recall@5 측정
- Agent tool-use 확인
- task당 평균 LLM call 수 측정
- API 제한 확인

산출물:

```text
mini_scan_report.json
mini_benchmark_results.json
api_budget_notes.md
```

---

## 9/19 — Scanner CLI

- folder scan
- parsers
- metadata
- JSON output

React는 시작하지 않는다.

---

## 9/20 — Agent Tools

- search_documents
- read_document
- query_table
- lookup_value

mini cross-file task 성공까지 확인.

---

## 9/21 — Ceiling Dataset + Benchmark

- dataset 20~30 files
- benchmark 20개
- ground truth
- control task 지정
- 공개 데이터 출처 기록

가능하면 사용자 인터뷰.

---

## 9/22 — Mini Full Experiment

중요 milestone.

```text
5 tasks
× 3 conditions
× 2 repetitions
```

다음을 반드시 끝까지 실행:

```text
Ceiling
↓
Defect Injection
↓
Before
↓
Scan
↓
AI Employee
↓
Diagnosis
↓
diagnosis_report.json
↓
Remediation
↓
After
↓
Re-test
↓
Comparison
```

이 날 실제 숫자가 나와야 한다.

---

## 9/23 — Readiness Engine

산출물:

### Use-case Profiles

```text
internal_knowledge_qa
operations_qa
```

### Blocker Rules

```text
VERSION_AMBIGUITY
OCR_REQUIRED
MISSING_SOURCE
SCHEMA_MISMATCH
PRIVACY_RISK
STALE_DATA
```

### Recommendation Mapping

```text
Finding
→ Blocker
→ Evidence
→ Recommended Action
```

---

## 9/24 — Full AI Employee Agent

- full benchmark 20개
- cross-file task
- canonical normalization
- baseline evaluation

---

## 9/25 — Counterfactual Diagnosis

- generic repair-dimension mechanism
- primary blocker attribution
- diagnosis cache
- attribution accuracy

---

## 9/26 — Full Experiment

- Before / After / Ceiling
- repeated runs
- call budget enforcement
- final metrics

---

## 9/27 — Dashboard + Docs

React 3 screens:

1. Scan Results
2. AI Employee Test
3. Comparison

Docs:

- README
- architecture
- evaluation report
- business hypothesis
- competition mapping
- interview insights

---

## 9/28 — Final Submission

- demo recording
- final benchmark
- screenshots
- setup verification
- code cleanup
- submission checklist

---

## 9/29 — Buffer

- bug fixes
- metric rerun
- submission issues

---

# 28. Definition of Done

## P0

- [ ] Scanner CLI
- [ ] TXT/PDF/DOCX/CSV/XLSX parsing
- [ ] exact duplicate
- [ ] probable version grouping
- [ ] PII masking
- [ ] char n-gram BM25
- [ ] Recall@k
- [ ] 4 Agent tools
- [ ] benchmark ≥15
- [ ] control task
- [ ] Before / After / Ceiling
- [ ] report-driven remediation
- [ ] counterfactual diagnosis
- [ ] primary blocker evaluation
- [ ] repeated run
- [ ] JSON artifacts
- [ ] 3 dashboard screens
- [ ] README
- [ ] demo video

## P1

- [ ] column semantic mapping
- [ ] HWPX
- [ ] advanced near-duplicate
- [ ] Kiwi tokenizer
- [ ] advanced spreadsheet structural analysis
- [ ] cost dashboard
- [ ] custom task editor

---

# 29. 발표/데모 시나리오

## Scene 1 — Dirty Company Data

한빛유통 파일 구조.

## Scene 2 — Scan

```text
31 files scanned
4 duplicates
3 version conflicts
2 PII risks
1 unreadable scan
3 schema issues
```

## Scene 3 — AI Employee Test

```text
Before
7.1 ± 0.8 / 20
```

## Scene 4 — Counterfactual Diagnosis

```text
Question:
현재 반품 가능 기간은?

FAIL

Version dimension repaired
→ PASS

Primary blocker:
VERSION_AMBIGUITY
```

## Scene 5 — Report-driven Remediation

```text
diagnosis_report.json
↓
remediate.py
```

중요:

> injected_defects.json은 사용하지 않음

## Scene 6 — Re-test

```text
Before   7.1 ± 0.8
After   14.6 ± 0.7
Ceiling 18.3 ± 0.5
```

그리고:

```text
Injected defects   12
Detected defects    9
Missed defects      3
```

실험 결과는 실제 측정값을 그대로 사용한다.

---

# 30. 최종 성공 정의

기능 수가 아니라 다음을 증명하면 성공이다.

## Detect

AI blocker를 일정 수준 이상 탐지할 수 있는가?

## Validate

AI Employee Benchmark로 실제 업무 수행 가능성을 측정할 수 있는가?

## Diagnose

실패 원인을 counterfactual rerun으로 구분할 수 있는가?

## Improve

진단 보고서만을 이용한 remediation 이후 AI 업무 성공률이 어떻게 변하는가?

## Measure Honestly

탐지 실패와 복구 실패까지 포함해 그대로 보고할 수 있는가?

---

# 31. 연구 근거

## TheAgentCompany

TheAgentCompany: Benchmarking LLM Agents on Consequential Real World Tasks

https://arxiv.org/abs/2412.14161

https://github.com/TheAgentCompany/TheAgentCompany

활용:

- 실제 회사 업무를 Agent task로 평가하는 benchmark 철학
- checkpoint / task 기반 evaluation 아이디어

---

## AIDRIN 2.0

A Framework to Assess Data Readiness for AI

https://arxiv.org/abs/2505.18213

활용:

- readiness dimension 설계 참고

---

## Data Readiness for Scientific AI at Scale

https://arxiv.org/abs/2507.23018

활용:

- 단계별 readiness 개념

---

## Exploratory Visual Analysis for Increasing Data Readiness in AI Projects

https://arxiv.org/abs/2409.03805

활용:

- 실제 task 수행 가능성과 data readiness 연결 관점

---

## SpreadsheetLLM

SpreadsheetLLM: Encoding Spreadsheets for Large Language Models

https://arxiv.org/abs/2407.09025

https://www.microsoft.com/en-us/research/publication/encoding-spreadsheets-for-large-language-models/

활용:

- 전체 spreadsheet를 그대로 보내지 않는 설계 근거

---

## LLM-based Column Type Annotation

Evaluating Knowledge Generation and Self-Refinement Strategies for LLM-based Column Type Annotation

https://arxiv.org/abs/2503.02718

활용:

- P1 column semantic typing 근거

---

# 32. 최종 Product Positioning

기본 설명:

> **기업의 AI 도입 준비도를 설문이나 추상 점수로 평가하지 않고, 실제 사내 자료를 AI 직원에게 제공해 업무를 수행하게 함으로써 검증하는 데이터 준비도 진단 서비스.**

기술적 설명:

> **Task-based AI readiness evaluation with counterfactual failure diagnosis and report-driven remediation.**

짧은 메시지:

> **"AI를 입사시켜 보면, 우리 회사 데이터가 준비됐는지 알 수 있다."**

핵심 발표 문장:

> **"AI가 왜 일을 못 했는지를 추측하지 않고, 조건을 바꿔 재실행해 진단하고, 탐지한 문제만을 근거로 개선합니다."**
