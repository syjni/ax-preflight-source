# AX v5 실행 절차

1. 동결 전: 새 자료 스캔, `scripts.build_v5_candidate`, `scripts.verify_v5_candidate_truth`, `scripts.validate_v5_tool_access`, 새 스트림 검증 테스트와 개발용 실행기 프로브를 완료한다. `scripts.v5_preflight --manifest experiment/v5/CANDIDATE_MANIFEST.json --allow-draft`에서 오류가 없어야 한다.
2. 동결: `python -m scripts.freeze_v5`를 한 번만 실행한다. 기존 동결 매니페스트나 공식 실행 디렉터리가 있으면 거부한다. `python -m scripts.v5_preflight --manifest experiment/frozen/ax-exp-v5-manifest.json`에서 `ready_for_official=true`를 확인한다.
3. 사용자가 공식 시작을 지시한 후: `python -m scripts.v5_official_runner run-all --execute`. 동결 매니페스트 순서대로 r1 전체, r2 전체를 실행한다. 각 슬롯은 새 Kiro 프로세스·세션을 사용한다.
4. `INVALID`가 발생하면 즉시 중단한다. 해당 디렉터리의 `metadata.json`, `submitted-prompt-validation.json`, `stream-response-validation.json`, `runtime-identity-receipt.json`, `stream.jsonl`, 세션 JSONL을 대조하고 원인을 기록한다. 입증된 일시적 입력·런타임 결함에만 별도 재시도 루트에서 한 번 재시도한다. 원래 디렉터리는 보존한다. 모델 답 오답·형식 실패는 `VALID`로 남기며 재실행하지 않는다.
5. 32개 유효 슬롯을 마친 뒤에만 순서·누락·중복·세션/프롬프트/자료/해시·원문/전달 JSON·동결 평가를 전수 감사하고 1차·보조 지표를 집계한다. 감사를 통과하지 못하면 공식 성공률을 보고하지 않는다.

사용할 Python은 현재 작업공간의 의존성 런타임이다. 공식 실행에는 외부 Kiro 접근 권한이 필요하며, 이 문서 자체는 공식 실행을 승인하지 않는다.
