# AX Preflight

**AI Data Readiness Audit · AI 업무 도입 전 점검**

[![Source verification](https://github.com/syjni/ax-preflight-source/actions/workflows/ci.yml/badge.svg)](https://github.com/syjni/ax-preflight-source/actions/workflows/ci.yml)

AX Preflight는 실제 AI 업무를 반복 실행해 **어떤 데이터와 검색 경로가 업무를
막거나 흔드는지** 찾고, 수정 전후의 변화를 근거와 함께 보여주는 서비스입니다.

[공개 데모](https://syjni.github.io/ax-preflight-source/) ·
[심사용 Release](https://github.com/syjni/ax-preflight-source/releases/tag/v0.3.0-submission) ·
[심사자 빠른 시작](docs/REVIEWER_QUICKSTART.md) ·
[심사·제출 가이드](SUBMISSION.md) ·
[소스 저장소](https://github.com/syjni/ax-preflight-source)

## 핵심 결과

**정적 Data Readiness는 100점이었지만, AI는 반품 기간 업무에 3회 모두 답하지
못했습니다. 14일과 30일로 충돌하던 문서를 정리하자 같은 업무에 3회 모두
`30일`이라고 답했고, 기존 충돌은 다시 나타나지 않았습니다.**

| 검증 단계 | 정적 Readiness | 반품 기간 업무 | 관측 결과 |
|---|---:|---:|---|
| Before | 100 / 100 | 0 / 3 답변 | 14일·30일 정책 충돌로 3회 모두 보류 |
| After | 100 / 100 | 3 / 3 답변 | 3회 모두 30일, 인용 근거와 답이 직접 일치 |

![정적 Data Readiness 100점이어도 실제 AI 반품 업무가 3회 모두 보류된 AX Preflight 소개 화면](results_console/artifacts/ax-preflight-brand/intro-1440x900.png)

이 결과는 같은 반품 업무를 상태별로 세 번 실행한 검증 snapshot입니다. AX Preflight는
정적 파일 상태와 실제 업무 수행 결과를 함께 보며, 수정 대상과 재검증 결과를 하나의
흐름으로 연결합니다. 전체 10개 업무의 반복 결과와 해석 기준은
[반복 실행 결과](docs/PHASE6_V4.md)에 공개합니다.

## 무엇을 진단하나

AX·AI 도입 책임자는 준비된 업무와 보완할 업무를 구분하고, 현업·데이터 담당자는
수정할 문서와 검색 경로를 찾으며, 개발팀은 실행별 도구 호출과 근거 연결을 추적할
수 있습니다.

| 진단 영역 | 화면에서 확인하는 내용 |
|---|---|
| 실행 전 온보딩 | 원본 무결성, 파싱 범위, 검색 가능 자료, 평가 정보 분리, 승인 업무 |
| 업무 수행 가능성 | 업무별 답변·보류 상태와 반복 실행의 안정성 |
| 실패 원인 | 출처 충돌, 근거 부족, 정보 부재, 검색 경로 한계 |
| 근거 추적 | 검색 후보 → 읽은 자료 → 최종 인용으로 이어지는 실행 경로 |
| 개선 효과 | 같은 업무의 Before → After 결과와 기존 문제의 재현 여부 |

주요 기능은 검증된 Before → After 대표 흐름, 원인별 복구 안내, 검색·근거 경로,
고객 데이터 온보딩 검사, 최대 50회의 비동기 반복 실행입니다. 반복 실행은 진행률,
부분 실패, 일시정지·재개·중단과 실패 항목 재시도를 기록합니다.

## 구조와 Kiro 기반 실행

```mermaid
flowchart LR
    U["사용자"] --> C["Results Console"] --> A["AX Preflight API"]
    A --> P["온보딩 · 결과 조회"]
    A -. "라이브 실행" .-> K["AWS Kiro CLI"]
    K --> G["실행별 AI 에이전트"]
    G --> M["AX Preflight MCP 도구"]
    M --> D["문서 검색 · 읽기 · 표 조회"]
    D --> S["구조화된 최종 답변"]
    S --> E["진단 항목 · 근거 검사"]
    E --> C
    A --> R[("실행 결과 저장소")]
```

AX Preflight는 **AWS Kiro CLI로 실행별 AI 에이전트를 오케스트레이션**합니다. 각
에이전트는 허용된 MCP 데이터 도구로 자료를 찾고 읽은 뒤 구조화된 최종 답변을
제출합니다. AX Preflight API는 답변, 실행별 근거, 진단 항목과 반복 상태를 저장하고
Results Console에 제공합니다.

현재 라이브 요청의 기본 모델 식별자는 `claude-sonnet-5`입니다. 공개 데모는 검증된
결과를 읽는 모드라서 Kiro와 모델 자격 증명이 필요하지 않습니다. 새로운 데이터로
업무를 실행할 때만 Kiro CLI와 사용 가능한 모델 자격 증명이 필요합니다. 상세 계약과
데이터 흐름은 [아키텍처 문서](docs/ARCHITECTURE.md)에서 확인할 수 있습니다.

## 빠른 실행

권장 실행에는 Docker Desktop만 필요합니다. Python 3.12+와 Node.js 20+를 이미
사용한다면 기존 직접 실행 방식도 선택할 수 있습니다.

### 1. 내 자료로 점검하기

GitHub의 **Code → Download ZIP**으로 소스를 내려받아 `C:\ax-preflight`처럼 짧은
경로에 압축을 풉니다. Docker Desktop을 실행한 뒤 프로젝트 루트의
`start-docker.cmd`를 더블클릭하면 Results Console, 로컬 API, 한국어·영어 OCR을
하나의 컨테이너로 준비하고 브라우저를 엽니다.

```bat
cd /d C:\ax-preflight
start-docker.cmd
```

브라우저가 <http://127.0.0.1:8000/>에서 열리면 다음 순서로 확인합니다.

1. **결과 콘솔 → 내 자료 점검**에서 PDF·DOCX·XLSX·CSV·TXT 파일이나 폴더를
   선택합니다. 파일을 점선 영역에 끌어 놓아도 됩니다.
2. **내 자료 점검 시작**을 눌러 파일 접근성, 표 결측, 중복, 최신성, 개인정보 가능
   패턴, PDF 표와 OCR 결과를 검사합니다.
3. 결과의 **먼저 보완할 항목**에서 해당 파일과 권고 조치를 확인합니다.
4. **전체 준비도 보기**로 이동해 다섯 점수 차원과 온보딩 프리플라이트를 확인합니다.
5. **이 점검 기록 제거**를 누르면 점검 보고서와 앱의 로컬 관리 사본이 함께
   삭제됩니다. 컴퓨터에서 선택했던 원본 파일은 삭제하지 않습니다.

브라우저에서 선택한 파일은 인터넷 서비스가 아닌 같은 컴퓨터의 `localhost` API로만
전달되어 앱의 로컬 관리 폴더에 복사됩니다. 경로 입력 방식을 선택하면 원본을 제자리에서
읽고 복사하지 않습니다. 두 방식 모두 원본을 수정하지 않으며, 이 정적 점검은 모델을
호출하지 않습니다. Docker 데이터는 `ax-preflight-data` 로컬 volume에, 직접 실행
데이터는 Git에서 제외된 `artifacts/local_datasets/`에 저장됩니다. 기본 안전 한도는
5,000개 파일·1 GiB이며
`AX_PRODUCT_LOCAL_SCAN_MAX_FILES`, `AX_PRODUCT_LOCAL_SCAN_MAX_BYTES`로 조정할 수
있습니다.

종료할 때는 `stop-docker.cmd`를 실행합니다. 점검 데이터를 함께 지우려면 먼저 화면에서
각 점검 기록을 제거하십시오. `docker compose down --volumes`는 AX Preflight Docker
volume 전체를 삭제하는 별도 명령입니다.

Docker를 사용하지 않는 Windows 환경에서는 기존 실행기도 유지됩니다.

```bat
cd /d C:\ax-preflight
start-local.cmd
```

이 방식은 Python·Node 의존성을 설치하고 <http://127.0.0.1:5173/>을 엽니다. Tesseract와
`kor`, `eng` 언어팩이 없으면 스캔 PDF를 OCR하지 않고 화면에 설치 필요 상태와 다음
행동을 표시합니다. 일반 텍스트 PDF의 표 추출은 OCR 설치 여부와 무관하게 동작합니다.

직접 실행 명령이 필요하면 첫 번째 터미널에서 다음을 실행합니다.

```bat
cd /d C:\ax-preflight
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
set "AX_PRODUCT_FROZEN_RESULTS_ROOT=artifacts\phase6_product_demo_v4\runs"
.venv\Scripts\python.exe -m uvicorn ax_product.api:create_local_review_app_from_env --factory --host 127.0.0.1 --port 8000
```

두 번째 터미널에서는 다음을 실행합니다.

```bat
cd /d C:\ax-preflight\results_console
npm.cmd ci
npm.cmd run dev -- --port 5173
```

macOS·Linux에서도 `docker compose up --build --detach` 후
<http://127.0.0.1:8000/>을 열 수 있습니다. Python·Node 방식은 같은 의존성을 설치한
뒤 API를 다음처럼 시작하고, 별도 터미널에서
`cd results_console && npm ci && npm run dev -- --port 5173`을 실행합니다.

```bash
AX_PRODUCT_FROZEN_RESULTS_ROOT=artifacts/phase6_product_demo_v4/runs \
  python -m uvicorn ax_product.api:create_local_review_app_from_env \
  --factory --host 127.0.0.1 --port 8000
```

### 2. 검증된 공개 예시 보기

[공개 데모](https://syjni.github.io/ax-preflight-source/)에서 다음 순서로 확인하면 핵심 흐름을
3분 안에 볼 수 있습니다.

1. **소개**에서 정적 점수와 실제 업무 결과의 차이를 확인합니다.
2. **결과 콘솔**의 **검증된 대표 흐름**에서 정리 전 **보류 근거 보기**를 엽니다.
3. 정리 후 **30일 근거 확인**을 열어 답변과 인용 자료를 확인합니다.
4. **검색·근거 경로**에서 검색 후보, 읽은 자료와 최종 인용의 연결을 따라갑니다.
5. **관리자 1페이지**에서 수정 대상과 Before → After 요약을 확인합니다.

공개 예시는 파일 업로드 기능이 없는 정적 페이지입니다. 로컬 소스를 실행하면 같은
예시를 유지하면서 **내 자료 점검**이 활성화됩니다.

### 3. 소스와 검증 결과 재현하기

GitHub의 **Code → Download ZIP**을 사용하거나 저장소를 clone합니다. ZIP에는 `.git`
메타데이터가 없으므로 Git inventory 전용 테스트 2개만 의도적으로 건너뜁니다.

```bash
git clone https://github.com/syjni/ax-preflight-source.git
cd ax-preflight-source
```

가상환경 활성화:

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS · Linux
python3 -m venv .venv
source .venv/bin/activate
```

이후 모든 플랫폼에서 같은 검증 명령을 실행합니다.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.verify_phase6_demo_v4

cd results_console
npm ci
npm test
npm run typecheck
npm run build:static
```

Windows에서 과거 실행이 만든 `%TEMP%\pytest-of-<사용자>` 폴더의 권한 때문에
`PermissionError: [WinError 5]`가 나타나면, 저장소 안의 새 임시 폴더를 지정해 다시
실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-manual
```

GitHub Actions의
[Source verification](https://github.com/syjni/ax-preflight-source/actions/workflows/ci.yml)도
같은 백엔드·프런트엔드·검증 snapshot 검사를 깨끗한 Ubuntu 환경에서 실행합니다.

### 4. 내 자료로 실제 AI 업무 실행

Kiro CLI가 `PATH`에 있고 모델 자격 증명이 설정된 환경에서 라이브 API를 시작합니다.

```powershell
# Windows PowerShell
$env:AX_PRODUCT_RUNNER = "kiro"
$env:AX_PRODUCT_RUN_TIMEOUT_SECONDS = "300"
python -m uvicorn ax_product.api:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

```bash
# macOS · Linux
AX_PRODUCT_RUNNER=kiro AX_PRODUCT_RUN_TIMEOUT_SECONDS=300 \
  python -m uvicorn ax_product.api:create_app_from_env \
  --factory --host 127.0.0.1 --port 8000
```

이 라이브 factory에도 **내 자료 점검**이 포함됩니다. Results Console은 위와 같은
명령으로 실행합니다. 로컬 폴더를 점검한 뒤 데이터셋을 선택하면 온보딩 검사가 먼저
실행되고, 통과한 경우 승인 업무·업무 후보·직접 질문을 실행할 수 있습니다.
구성 형식과 실행 계약은 [제품 기술 문서](ax_product/README.md)에 설명되어 있습니다.

## 현재 범위와 제한사항

- 현재 릴리스는 대회 심사와 통제된 제품 검증을 위한 프로토타입입니다. 프로덕션 적용에는 인증, 사용자별 접근 제어, tenant 격리, 장기 보존·삭제 정책이 추가로 필요합니다.
- 대표 결과는 30개 파일과 10개 업무를 두 상태에서 각 3회 실행한 탐색 snapshot입니다. 핵심 개선 주장은 실제로 수정한 반품 기간 업무의 0/3 → 3/3 변화에 한정합니다.
- 근거와 답의 직접 일치는 인용된 구조화 응답에 답 값이 존재한다는 뜻입니다. 업무 정답률 평가는 별도의 기준 데이터와 검토가 필요합니다.
- 라이브 실행에서는 데이터 도구가 반환한 문서 일부와 구조화 값이 설정된 모델 처리 경계로 전달될 수 있습니다. 공급자 계정의 보존·학습·리전 정책을 함께 확인해야 합니다.
- 반복 실행은 단일 API 프로세스의 영속 큐에서 순차 처리합니다. 분산 worker, 자동 backoff, 동시성·비용 quota와 스케줄·알림은 후속 범위입니다.
- 민감정보 탐지는 데이터 준비 상태를 알리는 보조 신호입니다. 실제 고객 데이터에는 별도의 비식별화, 접근 통제와 보안 검토가 필요합니다.
- 현재 AWS 통합 범위는 Kiro CLI 기반 실행 오케스트레이션입니다. Amazon Bedrock 직접 연동과 AWS SDK 구성은 포함하지 않습니다.
- 최종 패키지는 Windows 11에서 검증했고 공개 CI는 Ubuntu에서 통과했습니다. macOS와 WSL은 별도로 검증하지 않았습니다.

## 저장소 구조

| 경로 | 역할 |
|---|---|
| `ax_scanner/`, `readiness_score.py` | 문서 scan과 정적 Data Readiness 계산 |
| `ax_mcp/` | 문서·구조화 데이터 조회 도구 |
| `ax_product/` | FastAPI, Kiro runner, 제출 계약, 결과 저장과 진단·근거 검사 |
| `results_console/` | React·TypeScript 기반 Results Console |
| `runtime_datasets.json` | dataset profile과 source·scan 경로 연결 |
| `Dockerfile`, `compose.yaml` | 콘솔·API·한국어/영어 OCR을 묶은 심사자 실행 환경 |
| `start-docker.cmd`, `stop-docker.cmd` | Windows Docker 검토 모드 시작·종료 |
| `start-local.cmd` | Python·Node 기반 Windows 직접 실행 |
| `artifacts/local_datasets/` | 직접 실행의 로컬 registry·마스킹 보고서·브라우저 선택 관리 사본 |
| `artifacts/product_runs/` | 새 실행의 결과와 근거 기록 |
| `artifacts/product_batches/` | 반복 실행의 진행률과 제어 상태 |
| `artifacts/phase6_product_demo_v4/runs/` | 현재 검증된 읽기 전용 snapshot |
| `scripts/`, `tests/` | 재현 검증 스크립트와 자동 테스트 |

과거 snapshot과 검사 규칙의 버전 관계는
[검증 산출물 버전 이력](docs/VERIFICATION_HISTORY.md)에서 분리해 관리합니다.

## 상세 문서

- [심사·제출 가이드](SUBMISSION.md)
- [심사자 빠른 시작](docs/REVIEWER_QUICKSTART.md)
- [시스템 구조와 데이터 흐름](docs/ARCHITECTURE.md)
- [데이터 처리와 개인정보 경계](docs/DATA_AND_PRIVACY.md)
- [3분 시연 대본](docs/DEMO_SCRIPT.md)
- [반복 실행 결과와 해석 범위](docs/PHASE6_V4.md)
- [의미 비교 규칙](docs/PHASE6_V4_COMPARISON_V2.md)
- [검색·근거 경로 감사](docs/PHASE6_V4_ORDER_RETRIEVAL_REVIEW.md)
- [검증 산출물 버전 이력](docs/VERIFICATION_HISTORY.md)

설치·테스트·화면 동작에서 재현되는 문제는
[GitHub Issues](https://github.com/syjni/ax-preflight-source/issues)에 실행 환경, 재현
명령, 기대 결과와 실제 결과를 남겨 주십시오. 고객 문서 원문, 모델 자격 증명과
개인정보는 첨부하지 마십시오.
