import type { TimeValue } from './types';

export const pad = (n: number) => String(n).padStart(2, '0');

export function toMs(v: TimeValue | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

// 경과 시간 — 모든 화면 한 형식(SPEC-002 §5.2 D-28): `N시간 M분` · 1시간 미만 `M분` · 1분 미만 `방금`
export function fmtElapsed(since: TimeValue | null | undefined, now: number): string {
  const t = toMs(since);
  if (t === null) return '';
  const m = Math.floor(Math.max(0, now - t) / 60000);
  if (m < 1) return '방금';
  return m < 60 ? m + '분' : Math.floor(m / 60) + '시간 ' + (m % 60) + '분';
}

export function elapsedSec(since: TimeValue | null | undefined, now: number): number {
  const t = toMs(since);
  return t === null ? 0 : Math.max(0, (now - t) / 1000);
}
