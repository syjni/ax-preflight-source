import type { ReactNode } from 'react';

export type Tone = 'neutral' | 'blue' | 'warning' | 'danger' | 'positive';

export function Status({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`status status--${tone}`}>{children}</span>;
}

