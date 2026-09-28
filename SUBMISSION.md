# AX Preflight 심사·제출 안내

AX Preflight의 심사에서 먼저 볼 제품 코드는 `ax_product/`, `ax_scanner/`, `ax_mcp/`, `results_console/`입니다. 루트의 `experiment/`, `artifacts/heldout_*`, `EXPERIMENT_*` 파일은 제품과 분리해 보존한 연구 실험 기록입니다.

공개 소스의 기준 브랜치는
[`main`](https://github.com/syjni/ax-preflight-source)입니다. 실제로 업로드할 파일,
Release와 SHA-256은 [현재 제출 파일 안내](artifacts/submission/CURRENT_SUBMISSION.md)를
기준으로 확인합니다. ZIP과 함께 생성하는 `SOURCE_MANIFEST.json`은 패키징한 정확한
Git commit과 전체 파일 inventory를 기록합니다.

> **검증 환경:** Windows 11, PowerShell, Python 3.12, Node.js에서 최종 로컬 감사를
> 수행했습니다. 공개 저장소의 `Source verification`은 Ubuntu, Python 3.12,
> Node.js 22에서 백엔드 테스트, 프런트엔드 테스트·typecheck·정적 build와 검증
> snapshot 검사를 통과했습니다. macOS와 WSL은 별도로 검증하지 않았습니다.
>
> **Windows ZIP 경로:** 동결 run의 감사 파일명은 의도적으로 길기 때문에 ZIP은 `C:\ax-preflight`처럼 짧은 경로에 푸십시오. 패키지 검사기는 긴 경로도 안전하게 추출·해시 검증하지만, 일반 Python 도구나 탐색기는 깊은 상위 폴더에서 Win32 기존 경로 제한에 걸릴 수 있습니다.

## 5분 read-only 데모

Python 3.12+, Node.js 20+ 환경에서 다음 순서로 실행합니다.

### Windows PowerShell

```powershell
python -m pip install -r requirements.txt
$env:AX_PRODUCT_FROZEN_RESULTS_ROOT = "artifacts/phase6_product_demo_v4/runs"
python -m uvicorn ax_product.api:create_read_only_app_from_env --factory --host 127.0.0.1 --port 8000
```

새 터미널에서 `cd results_console`, `npm ci`, `npm run dev -- --port 5173`을 차례로 실행합니다.

### macOS / Linux

```bash
python -m pip install -r requirements.txt
AX_PRODUCT_FROZEN_RESULTS_ROOT=artifacts/phase6_product_demo_v4/runs \
  python -m uvicorn ax_product.api:create_read_only_app_from_env \
  --factory --host 127.0.0.1 --port 8000
```

새 터미널에서 `cd results_console && npm ci && npm run dev -- --port 5173`을 실행합니다.

브라우저에서 `http://127.0.0.1:5173/`을 열고 다음 순서로 봅니다.

1. `한빛유통 30개 파일 · Before`: 정적 Readiness는 100점이지만 반품 기간 업무는 14일·30일 정책 충돌로 3회 모두 보류됩니다.
2. `한빛유통 30개 파일 · After`: 충돌 문서를 정리한 뒤 같은 업무에 3회 모두 `30일`로 답하고, 인용 근거와 답이 직접 일치합니다.
3. **검색·근거 경로**에서 검색 후보, 읽은 자료와 최종 인용을 확인하고, **관리자 1페이지**에서 수정 대상·권고 조치·Before/After를 PDF로 저장합니다.

## 재현 검증

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.verify_phase6_demo_v3
python -m scripts.verify_phase6_demo_v4

cd results_console
npm ci
npm test
npm run typecheck
npm run build:static
```

Windows에서 `%TEMP%\pytest-of-<사용자>` 접근 권한 오류가 발생하면 저장소 안의 새
임시 폴더를 지정해 테스트를 다시 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-manual
```

공개 저장소의
[`Source verification`](https://github.com/syjni/ax-preflight-source/actions/workflows/ci.yml)
워크플로도 위와 같은 백엔드·프런트엔드·v3/v4 검증을 Ubuntu에서 실행합니다. 이전
snapshot과 검사 규칙의 관계는
[검증 산출물 버전 이력](docs/VERIFICATION_HISTORY.md)에 분리해 보존합니다.

## 제품 흐름

1. scanner가 사용자가 지정한 파일의 접근성·결측·중복·시점·PII 패턴을 정적으로 측정합니다.
2. Kiro product agent가 선택한 실제 업무 질문을 MCP 도구로 수행합니다.
3. 자연어 출력이 아니라 `submit_answer`에 승인된 구조화 payload만 결과가 됩니다.
4. 보류 결과는 같은 run의 tool response와 task identity로 Finding에 집계됩니다.
5. Finding은 원인 자료, 영향 업무·실행 수, 구체적인 권고 조치를 제공합니다.
6. Evidence Checker는 인용된 같은-run 응답에서 답의 근거를 별도로 확인합니다.
7. 라이브 API의 반복 실행 P0는 최대 50개 항목을 영속 예약하고 진행률·부분 실패·안전한 제어·실패 항목 재시도를 제공합니다. 발표용 read-only 배포에서는 이 변경 동작이 비활성화됩니다.

라이브 실행에서 **AWS Kiro CLI는 실행별 AI 에이전트의 오케스트레이터**이고 요청
모델 식별자의 기본값은 `claude-sonnet-5`입니다. runner는 요청된 모델 값을 실행별
agent와 product MCP에 전달합니다. AX Preflight가 구현하는 범위는 scanner,
온보딩 검사, 실행·제출 계약, MCP 데이터 도구, Finding·Evidence 검사, API와
Results Console입니다.

원본 파일과 실행 산출물은 로컬 경로에서 관리하지만, 실제 AI 업무 실행에서는 호출된 data tool이 반환한 문서 일부 또는 구조화 값이 설정된 모델 처리 경계로 전달될 수 있습니다. 공급자 계정의 보존·학습·리전 정책은 별도 확인 대상입니다.

## 현재 범위와 주장 경계

- 대표 결과는 30개 파일과 10개 업무를 두 상태에서 각 3회 실행한 탐색 snapshot입니다. 핵심 개선 주장은 실제로 수정한 반품 기간 업무의 0/3 → 3/3 변화에 한정합니다.
- 근거와 답의 직접 일치는 인용된 구조화 응답에 답 값이 존재한다는 뜻입니다. 업무 정답률 평가는 별도의 기준 데이터와 검토가 필요합니다.
- 연구 실험 기록은 제품 데모와 분리해 보존하며 제품 성능 수치로 합산하지 않습니다.
- read-only 데모는 검증된 결과만 읽고 `POST /api/run`과 `POST /api/batches`를 비활성화합니다.
- 원본 파일과 실행 산출물은 지정된 로컬 경로에 저장됩니다. 라이브 실행에서는 데이터 도구가 반환한 문서 일부와 구조화 값이 설정된 모델 처리 경계로 전달될 수 있습니다.
- 현재 구성은 통제된 프로토타입입니다. 실제 고객 데이터 적용에는 인증, tenant 격리, 비식별화, 접근 통제와 보존·삭제 정책이 필요합니다.
- 현재 AWS 통합 범위는 Kiro CLI 기반 실행 오케스트레이션입니다. Amazon Bedrock 직접 연동과 AWS SDK 구성은 포함하지 않습니다.

상세 구조는 [아키텍처](docs/ARCHITECTURE.md), 발표 흐름은
[3분 시연 대본](docs/DEMO_SCRIPT.md), 반복 결과는
[v4 설명](docs/PHASE6_V4.md), 내부 버전 관계는
[검증 산출물 버전 이력](docs/VERIFICATION_HISTORY.md)을 참고하십시오.
