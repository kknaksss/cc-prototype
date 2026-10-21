export const pad = (n: number) => String(n).padStart(2, '0');

// ISO → ms. 없거나 못 읽으면 null
export function toMs(v: string | null | undefined): number | null {
  if (!v) return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : null;
}

// 화면 시각은 KST(SPEC-003 §2.3) — 브라우저 시간대와 상관없이
const KST = 9 * 3600 * 1000;
export function hm(v: string | number | null | undefined): string {
  const t = typeof v === 'number' ? v : toMs(v);
  if (t === null) return '';
  const d = new Date(t + KST);
  return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
}
export function hms(v: string | number | null | undefined): string {
  const t = typeof v === 'number' ? v : toMs(v);
  if (t === null) return '';
  return hm(t) + ':' + pad(new Date(t + KST).getUTCSeconds());
}

// 지난 분(내림)
export function minutesSince(since: string | null | undefined, now: number): number {
  const t = toMs(since);
  return t === null ? 0 : Math.max(0, Math.floor((now - t) / 60000));
}
