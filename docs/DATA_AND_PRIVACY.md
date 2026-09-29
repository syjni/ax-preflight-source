# 데이터 처리와 개인정보 경계

이 문서는 문서 접근과 결과 저장을 로컬 경로에서 통제하는 AX Preflight 프로토타입의 실제 데이터 흐름과 구현되지 않은 통제를 구분합니다. 도구 응답은 설정된 모델 실행 경계로 전달되며, 이 문서는 프로덕션 보안 또는 규제 준수를 보장하지 않습니다.

## 처리되는 데이터

`runtime_datasets.json`은 dataset profile을 로컬 source root와 scan report에 연결합니다. 문서와 실행 산출물은 로컬 경로에서 처리·저장됩니다.

- 경로 방식의 `POST /api/local-datasets`는 같은 컴퓨터에서 실행 중인 API가 입력 폴더를 제자리에서 읽습니다. 원본 파일을 복사하거나 수정하지 않습니다.
- 선택 방식의 `POST /api/local-datasets/upload`는 브라우저가 선택한 파일을 같은 컴퓨터의 `localhost` API에 multipart로 전송합니다. 파일은 앱이 관리하는 로컬 폴더에 복사되며 외부 서비스로 전송되지 않습니다. 화면에서 점검 기록을 제거하면 이 관리 사본도 함께 삭제되고 사용자가 선택한 원본은 그대로 유지됩니다.
- 이 로컬 정적 점검은 모델을 호출하지 않습니다. 마스킹된 추출문과 구조화된 파일 메타데이터가 `artifacts/local_datasets/` 아래에 저장되며 해당 경로는 Git에서 제외됩니다.
- scanner와 Readiness v1은 로컬 문서 집합에서 생성된 scan report를 읽습니다.
- product MCP의 `search_documents`, `read_document`, `lookup_value`, `query_table`은 질의에 필요한 문서 내용 또는 구조화 값을 모델에 반환합니다.
- 모델에 반환되는 범위는 호출된 도구, 도구 요청의 인자, 검색 결과, 문서 크기와 도구의 잘림 처리 등에 따라 달라질 수 있습니다.
- 따라서 “원본 전체 파일은 절대 모델에 전달되지 않는다”고 단정할 수 없습니다. 특히 문서 읽기 요청과 문서 크기에 따라 상당한 내용이 반환될 수 있으므로 입력 문서 자체의 민감도를 먼저 평가해야 합니다.
- 성공한 data-tool의 구조화된 response는 run별 `tool-responses/*.json`으로 저장될 수 있습니다.

실제 Kiro/모델 사용 시 도구가 반환한 데이터는 해당 모델 실행 경계로 전달됩니다. 로컬 고객 dataset은 OWNER가 자료 등급, 도구 출력 전달, 공급자 정책 검토와 민감정보 검토를 확인한 뒤 project·dataset·model 조합을 승인해야 실행됩니다. 이 승인은 외부 모델 서비스의 보존·학습·지역 정책을 대신하지 않으므로 사용하는 공급자와 계정의 정책을 별도로 확인해야 합니다.

## 실행 기술과 공급자 경계

Kiro CLI는 opt-in 라이브 실행을 오케스트레이션합니다. 요청 모델 식별자의 저장소 기본값은 `claude-sonnet-5`이고, runner는 이 값을 실행별 임시 agent와 product MCP에 전달합니다. 이 저장소에는 AWS SDK 또는 Amazon Bedrock 직접 연동 코드가 없으므로 특정 AWS 서비스의 전송·보존·리전 통제가 적용된다고 단정하지 않습니다. 실제 모델 처리 위치와 정책은 Kiro, 모델 자격 증명, 공급자 계정이 구성된 실행 환경에서 확인해야 합니다.

## 로컬 저장 범위

| 데이터 | 기본 위치 | 현재 동작 |
|---|---|---|
| 로컬 점검 보고서 | `artifacts/local_datasets/<profile>/scan-report.json` | 마스킹된 추출문·메타데이터 저장; 화면에서 기록 제거 가능 |
| 브라우저 선택 관리 사본 | `artifacts/local_datasets/uploads/<upload-id>/` | localhost에서만 저장; 해당 점검 기록 제거 시 함께 삭제; 원본은 삭제하지 않음 |
| Docker 로컬 데이터 | `ax-preflight-data` volume의 `/data/local-datasets/` | 보고서·registry·선택 관리 사본을 컨테이너 밖 로컬 volume에 보존 |
| 계정·세션·로그인 시도·프로젝트·업무·PoC 판단 | `<local-datasets>/access_control/state.json` | 비밀번호는 Argon2id, 세션·CSRF 토큰과 로그인 식별자는 SHA-256 digest로만 저장; 프로젝트 구성원·역할·책임자 판단 저장 |
| 실행 정책·자료 전달 승인·예상 비용 예약 | `<local-datasets>/access_control/state.json` | OWNER 지정 모델·실행 한도, dataset별 분류·model·승인 만료, 실행당 추정 비용을 저장; 모델 자격 증명 원문은 저장하지 않음 |
| 보안 이벤트 | `<local-datasets>/access_control/security-audit.jsonl` | 로그인·권한·업무·전달 승인·실행 예산·보존·PoC 판단 이벤트를 SHA-256 연결 해시로 봉인; 비밀번호와 토큰 제외 |
| 일반 실행 상태와 결과 | `artifacts/product_runs/<run_id>/` | 쓰기 가능한 run별 저장 |
| 반복 실행 상태 | `artifacts/product_batches/<batch_id>/batch.json` | 선택 업무 질문·상태·시도·run ID·구조화 오류 코드를 원자 저장 |
| 실행 업무 context | `<run_id>/run-context.json` | 선택한 task ID·label 또는 ad hoc 질문을 run별로 저장 |
| 업무 승인 registry | `business_task_approvals.json` | 데이터셋·task ID·질문 해시·담당 역할·성공 기준·승인 범위를 저장 |
| 권위 있는 제출 결과 | `<run_id>/delivery.json` | 첫 유효 제출을 write-once로 게시 |
| 구조화 도구 응답 | `<run_id>/tool-responses/*.json` | 성공한 data-tool 응답을 run별로 기록 가능 |
| 근거 검사 결과 | `<run_id>/evidence-check.json` | delivery와 분리해 write-once로 게시 |
| 공식 Phase 6 반복 결과 | `artifacts/phase6_product_demo_v4/runs/` | 검증된 60-run 동결 snapshot, read-only factory에서 조회; v1~v3는 별도 비변조 보존 |

assistant prose와 Kiro `finalText`는 권위 있는 제품 답도 Evidence Checker 또는 Finding 입력도 아닙니다. Evidence Checker와 Failure→Finding 집계기는 `DeliveryEnvelope`, 저장된 업무 context와 동일 run의 구조화 tool response만 사용하며 delivery를 수정하지 않습니다. ad hoc 질문 원문은 업무 label로 저장될 수 있으므로 질문에도 불필요한 개인정보나 비밀값을 넣지 않아야 합니다. 반복 실행의 후보 질문도 배치 항목 label로 복제되므로 같은 최소화 원칙이 적용됩니다.

## 현재 보안 경계와 제한

- 로컬 검토와 라이브 factory는 첫 관리자 설정 이후 로그인을 강제합니다. 비밀번호는 Argon2id로 해시하고, 무작위 서버 세션은 HttpOnly·SameSite=Strict 쿠키로 전달하며 서버에는 digest만 저장합니다.
- 상태 변경 요청은 세션과 별도의 CSRF 토큰을 검사합니다. `OWNER`·`EDITOR`·`VIEWER` 역할에 따라 프로젝트 자료, 업무 등록과 승인을 제한하고, 미소속 프로젝트의 자료는 404로 숨깁니다.
- 실패한 로그인은 기본 15분 창에서 5회까지 허용한 뒤 기본 15분간 제한합니다. 제한 상태는 로컬 상태 파일에 영속되며 식별자는 digest로만 저장합니다. 관리자는 사용자의 모든 서버 세션을 종료할 수 있고, OWNER는 OWNER가 아닌 구성원의 프로젝트 권한을 회수할 수 있습니다.
- 프로젝트별 보관 항목을 화면에서 집계하며 OWNER가 보존 검토 주기와 법적 보존 상태를 기록합니다. 정확한 프로젝트명 재입력으로 점검 보고서, 앱 관리 사본, 구성원·업무·모델 승인, 완료된 쓰기 가능 run과 terminal batch, PoC 판단을 명시적으로 삭제합니다. 실행 중 작업, 법적 보존 또는 감사 원장 무결성 오류가 있으면 삭제하지 않습니다. 삭제 뒤 각 관리 저장소와 감사 로그의 원시 프로젝트 식별자 부재를 검사하고 증명서 ID를 반환합니다. 경로 입력 원본·브라우저에서 선택했던 원본과 frozen 결과는 삭제 대상이 아닙니다.
- 로컬 고객 dataset의 AI 실행은 OWNER가 모델·자료 전달 경계를 승인해야 합니다. 승인은 만료되며 모델 변경 시 일치하지 않는 승인을 사용할 수 없습니다. 개인정보 가능 패턴이 발견된 자료의 `PUBLIC` 분류 승인은 거절하지만, 이 패턴 검사는 DLP나 법적 개인정보 판정을 대체하지 않습니다.
- 서버는 단일 run 예약과 배치 생성·재개·재시도 전에 최근 24시간 실행 수·예상 비용, 배치 크기와 동시 실행 한도를 검사합니다. 비용은 실제 토큰 사용량이나 청구액이 아닌 OWNER가 지정한 실행당 추정치입니다.
- 현재 격리는 한 AX Preflight 인스턴스 안의 프로젝트 수준 접근 제어입니다. 별도 데이터베이스·스토리지 계정에 의한 조직 tenant 물리 격리나 암호화 경계는 아닙니다.
- SSO·MFA, 계정 복구, 중앙 identity provider와 분산·네트워크 수준 rate limit은 아직 없습니다. 인터넷 또는 사내망에 공개할 때는 TLS와 reverse proxy 통제를 함께 구성해야 합니다.
- 현재 보존 방식은 OWNER가 검토 날짜를 기록하고 명시적으로 삭제하는 `MANUAL_DELETE / OWNER_REVIEW`입니다. 법적 보존 중 삭제는 차단하지만 날짜 도래 시 자동 만료를 실행하지 않으며 백업 연계 삭제와 복구 절차도 아직 제품화되지 않았습니다.
- 로컬 파일 권한, 장치 보안과 실행 계정의 권한이 현재 주요 경계입니다.
- 로컬 감사 원장은 연결 해시로 사후 변조를 탐지하지만 OS 관리자에 대한 변경 불가능성을 보장하는 WORM 저장소는 아닙니다. 네트워크 배포, TLS termination, secret manager와 중앙 감사 수집은 이 프로토타입 범위가 아닙니다.
- 민감정보 탐지는 readiness 신호이며 완전한 탐지, 마스킹, 유출 방지 또는 접근 통제를 의미하지 않습니다.
- 신규 실행의 Evidence Checker v3는 frozen v2의 제한된 결정론적 검사를 먼저 적용하고, 명시적으로 폐기된 수량을 현재 직접 근거로 승격하지 않습니다. frozen v1·v2 결과는 비변조 보존합니다. `UNCONFIRMED`는 확인되지 않음을 뜻하며 오답이나 보안 위반 판정이 아닙니다.
- 일반 후보 catalog는 고객 데이터가 아닌 제품 기본값입니다. 기본 공개 기록은 `CONTROLLED_DEMO`이고, 프로젝트 OWNER가 화면에서 승인한 로컬 업무만 `CUSTOMER` 범위로 분리해 기록합니다. 실제 조직에서는 승인 책임자 지정과 변경 관리 절차를 함께 운영해야 합니다.
- 반복 실행은 단일 API 프로세스 안의 영속 상태 머신입니다. 단일 프로세스 기준 실행 수·추정 비용·동시성 한도는 적용되지만 다중 worker lease, tenant별 queue 격리, 분산 원자 quota, 실제 청구액 정산, 자동 만료와 변경 불가능한 중앙 감사 로그는 아직 없습니다.

## 프로덕션 배포 전에 필요한 통제

다음 항목은 현재 구현됐다는 뜻이 아니라 배포 전에 별도 설계·검증해야 할 목록입니다.

1. 사내 identity provider 기반 SSO·MFA, 서비스 identity, 계정 수명·복구와 최소 권한 정기 검토
2. 조직 tenant별 데이터베이스·dataset·run 저장소의 물리·논리 격리와 경로 접근 검증
3. 전송 구간 TLS, 저장 데이터·백업 암호화와 관리형 key rotation
4. secret manager, 자격 증명 수명 관리와 로그·오류 메시지의 비밀값 제거
5. 도구별 필드 allowlist·마스킹·DLP를 포함한 모델 전송 데이터 최소화와 승인 정책 고도화
6. 모델 공급자별 데이터 보존, 학습 사용, 처리 지역과 하위 처리자 검토
7. 현재 검토 주기·법적 보존을 실제 자동 만료, 백업 연계 삭제와 복구 절차로 확장
8. 로컬 해시 체인을 중앙 WORM 감사 저장소, 접근·내보내기·삭제 모니터링과 사고 대응으로 확장
9. 분산·네트워크 수준 rate limit, 실제 사용량 기반 비용·자원 quota와 abuse 방어
10. 의존성·이미지 패치, 취약점 관리, threat modeling, 침투 테스트와 배포 승인

## 운영 전 데이터 점검

실제 회사 문서를 연결하기 전에는 source root의 소유자, 문서 등급, 허용 모델, 허용 지역, 보존 기간을 확인해야 합니다. 샘플 또는 동결 데모 결과를 고객 데이터 처리 안전성의 증거로 확대 해석해서는 안 됩니다.
