import type { TimeValue } from './types';

export const pad = (n: number) => String(n).padStart(2, '0');

export function toMs(v: TimeValue | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

// 현황판 시안 fmt — 시간이 넘으면 h:mm:ss
export function fmtElapsed(since: TimeValue | null | undefined, now: number): string {
  const t = toMs(since);
  if (t === null) return '';
  const s = Math.max(0, Math.floor((now - t) / 1000));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return hh ? hh + ':' + pad(mm) + ':' + pad(ss) : pad(mm) + ':' + pad(ss);
}

// 직원 시안 fmt — 분:초(분이 60을 넘어도 그대로)
export function fmtMinSec(since: TimeValue | null | undefined, now: number): string {
  const t = toMs(since);
  if (t === null) return '';
  const s = Math.max(0, Math.floor((now - t) / 1000));
  return pad(Math.floor(s / 60)) + ':' + pad(s % 60);
}

export function elapsedSec(since: TimeValue | null | undefined, now: number): number {
  const t = toMs(since);
  return t === null ? 0 : Math.max(0, (now - t) / 1000);
}
