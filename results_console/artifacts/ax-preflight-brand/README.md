# AX Preflight responsive QA

검증 일자: 2026-09-28 (Asia/Seoul)

## 화면 캡처

| 폭 | 소개 | 사용 방법 | 결과 콘솔 |
|---:|---|---|---|
| 1440 | `intro-1440x900.png` | `guide-1440x900.png` | `console-1440x900.png` |
| 1024 | `intro-1024x900.png` | `guide-1024x900.png` | `console-1024x900.png` |
| 768 | `intro-768x900.png` | `guide-768x900.png` | `console-768x900.png` |
| 390 | `intro-390x844.png` | `guide-390x844.png` | `console-390x844.png` |
| 320 | `intro-320x844.png` | `guide-320x844.png` | `console-320x844.png` |

`admin-report-print-preview.png`은 Chromium print CSS로 생성한 A4 PDF 1페이지를 PNG로 렌더링한 인쇄 미리보기다.

## 확인 결과

- 루트(`/`)는 소개 탭으로 진입하며 `#intro`, `#guide`, `#console`과 기존 결과 콘솔 섹션 앵커가 동작한다.
- 1440px 결과 콘솔의 280px 사이드바에서 `AX Preflight`와 `Results Console`이 한 줄 안에 들어간다.
- 소개 화면의 히어로 제목은 1440px에서 58px, 브랜드는 15px로 측정되어 제목 위계를 유지한다.
- 390px 상단 라벨은 두 줄 줄바꿈으로 수용하고, 320px에서는 `PROTOTYPE`만 숨긴다.
- 5개 폭의 세 탭에서 오른쪽 잘림 없이 탐색과 주요 콘텐츠가 표시된다.
- 관리자 보고서는 A4 1페이지이며 `AX Preflight · AI 업무 도입 전 점검` 헤더가 한 줄로 유지된다.
