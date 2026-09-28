export type ContextAssessment = {
  kind: 'MATCH' | 'MISMATCH' | 'UNKNOWN';
  selected: string;
  origin: string;
  warning: string | null;
};

export function assessRunContext(selected: string, recorded: string | undefined): ContextAssessment {
  const origin = recorded || 'UNKNOWN';
  if (origin === 'UNKNOWN') return {
    kind: 'UNKNOWN', selected, origin,
    warning: `평가 문맥 확인 불가 · 이 run의 데이터셋 출처는 UNKNOWN입니다. 선택한 ${selected}의 readiness와 같은 데이터에 대한 결과로 해석하지 마세요.`,
  };
  if (origin !== selected) return {
    kind: 'MISMATCH', selected, origin,
    warning: `평가 문맥 불일치 · 선택한 ${selected}의 readiness와 이 run의 출처 ${origin}은 서로 다릅니다. 두 결과를 같은 평가 문맥으로 해석하지 마세요.`,
  };
  return { kind: 'MATCH', selected, origin, warning: null };
}
