# AX Preflight 심사·제출 안내

AX Preflight의 심사에서 먼저 볼 제품 코드는 `ax_product/`, `ax_scanner/`, `ax_mcp/`, `results_console/`입니다. 루트의 `experiment/`, `artifacts/heldout_*`, `EXPERIMENT_*` 파일은 제품과 분리해 보존한 연구 실험 기록입니다.

현재 제출 준비 브랜치는 `codex/ax-preflight-brand`입니다. ZIP과 함께 생성하는 최종 감사의 `SOURCE_MANIFEST.json`이 브랜치 이름보다 우선해 패키징한 정확한 Git commit을 기록합니다.

> **검증 환경:** Windows 11, PowerShell, Python 3.12, Node.js에서 검증했습니다. macOS/Linux/WSL 명령은 이식성을 고려해 제공하지만 이번 최종 감사에서는 실행하지 못했습니다.
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

### macOS / Linux — 제공되지만 최종 감사에서 미검증

```bash
python -m pip install -r requirements.txt
AX_PRODUCT_FROZEN_RESULTS_ROOT=artifacts/phase6_product_demo_v4/runs \
  python -m uvicorn ax_product.api:create_read_only_app_from_env \
  --factory --host 127.0.0.1 --port 8000
```

새 터미널에서 `cd results_console && npm ci && npm run dev -- --port 5173`을 실행합니다.

브라우저에서 `http://127.0.0.1:5173/`을 열고 다음 순서로 봅니다.

1. `한빛유통 30개 파일 · Before`: 30회 중 19회 ANSWERED, 의미 비교 v2에서 10업무 중 5개가 세 번 모두 같은 의미로 답했습니다. 반품 충돌은 3/3 보류입니다.
2. `한빛유통 30개 파일 · After`: 30회 중 21회 ANSWERED, 의미 비교 v2에서 10업무 중 6개가 반복 안정입니다. 답변·보류 혼재와 값 불일치는 데이터 원인이 입증되지 않으면 `데이터 원인 미확인`으로 보여 줍니다.
3. 반품 업무는 After 3/3 `30일 / DIRECT_MATCH`이고 기존 충돌은 `After에서 재현되지 않음`입니다. 관리자 1페이지에서 수정 대상·권고 조치·Before/After를 PDF로 저장할 수 있습니다.

## 재현 검증

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/verify_phase5_preservation.py
python -m scripts.verify_phase6_demo
python -m scripts.verify_phase6_demo_v2
python -m scripts.verify_phase6_demo_v3
python -m scripts.verify_phase6_demo_v4
cd results_console
npm test
npm run build
```

Node.js가 없는 Linux/WSL에서는 checksum을 검증한 임시 Node 22 환경과 임시 console 복사본으로 `bash scripts/verify_linux_frontend.sh`를 실행할 수 있습니다. 이번 최종 감사에서는 host의 WSL 실행이 `E_ACCESSDENIED`로 차단되어 이 경로를 재검증하지 못했습니다.

v3 verifier는 기존 26개 run의 비변조를 계속 확인합니다. v4 verifier는 v3 parent hash, 60개 run의 정확한 10×2×3 행렬, Evidence v2 재계산, 35/60 `DIRECT_MATCH`, 반복 불일치 Finding, 파일 inventory를 확인합니다.

## 제품 흐름

1. scanner가 사용자가 지정한 파일의 접근성·결측·중복·시점·PII 패턴을 정적으로 측정합니다.
2. Kiro product agent가 선택한 실제 업무 질문을 MCP 도구로 수행합니다.
3. 자연어 출력이 아니라 `submit_answer`에 승인된 구조화 payload만 결과가 됩니다.
4. 보류 결과는 같은 run의 tool response와 task identity로 Finding에 집계됩니다.
5. Finding은 원인 자료, 영향 업무·실행 수, 구체적인 권고 조치를 제공합니다.
6. Evidence Checker는 인용된 같은-run 응답에서 답의 근거를 별도로 확인합니다.
7. 라이브 API의 반복 실행 P0는 최대 50개 항목을 영속 예약하고 진행률·부분 실패·안전한 제어·실패 항목 재시도를 제공합니다. 발표용 read-only 배포에서는 이 변경 동작이 비활성화됩니다.

라이브 실행에서 Kiro CLI는 오케스트레이터이고 요청 모델 식별자의 기본값은 `claude-sonnet-5`입니다. runner는 요청된 모델 값을 실행별 agent와 product MCP에 전달합니다. 이 저장소에는 AWS SDK나 Amazon Bedrock 직접 연동 코드가 없으므로 구현되지 않은 AWS 서비스를 사용한다고 주장하지 않습니다. scanner·실행 계약·MCP·Finding/Evidence·API·화면은 AX Preflight 구현 범위입니다.

원본 파일과 실행 산출물은 로컬 경로에서 관리하지만, 실제 AI 업무 실행에서는 호출된 data tool이 반환한 문서 일부 또는 구조화 값이 설정된 모델 처리 경계로 전달될 수 있습니다. 공급자 계정의 보존·학습·리전 정책은 별도 확인 대상입니다.

## 주장 경계

- v4는 30파일·10업무·2상태를 각 3회 실행한 탐색 데모이지 고객 검증 benchmark나 무작위 대조 실험이 아닙니다.
- 2파일·1업무 결과는 반복 3회의 단순 sanity demo입니다.
- After가 전체적으로 개선됐거나 악화됐다고 주장하지 않습니다. 현재 의미 비교 v2의 반복 안정은 Before 5/10, After 6/10이며, 기존 비교 v1의 4/10·2/10은 표현·단위 차이와 한 번 이상의 보류를 과도하게 불안정으로 분류한 감사 이력으로만 보존합니다. 실제 수정한 반품 충돌의 0/3→3/3 전환만 좁게 설명합니다.
- 기존 16업무 연구 실험은 제품 데모와 섞어 성능 수치로 주장하지 않습니다.
- `UNCONFIRMED`는 오답 판정이 아니라 자동 확인 범위 밖이라는 뜻이며, `DIRECT_MATCH`도 업무 정답률이 아니라 인용 구조화 응답과 답 값의 일치입니다.
- read-only 데모는 frozen 결과를 수정하지 않으며 `POST /api/run`과 `POST /api/batches`를 의도적으로 거부합니다.
- 모델 데이터가 “외부로 나가지 않는다”고 주장하지 않습니다. 로컬 저장과 모델 처리 경계를 구분하며, 인증·tenant 격리·민감정보 차단은 아직 프로덕션 수준으로 구현되지 않았습니다.

상세 구조는 [아키텍처](docs/ARCHITECTURE.md), 발표 흐름은 [3분 시연 대본](docs/DEMO_SCRIPT.md), 반복 결과는 [v4 설명](docs/PHASE6_V4.md), [안정성 후속 검토](docs/PHASE6_V4_STABILITY_REVIEW.md), [DIRECT_MATCH 감사](docs/PHASE6_V4_DIRECT_MATCH_AUDIT.md), Evidence Checker 변경 근거는 [확장 규칙](docs/EVIDENCE_CHECKER_V3.md)을 참고하십시오.
