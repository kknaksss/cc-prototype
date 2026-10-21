// 예약관리 화면 값 — 시안 「Ceramique 예약관리 v1」 rowVals · previewVals · shotVals 를 back 줄(SPEC-002 §3.1)로 옮긴 것
import { pad } from '@/lib/time';
import type { ResvRequest, ResvStatus } from '@/lib/types';

const WD = ['일', '월', '화', '수', '목', '금', '토'];

// 「2026-10-16」 → 「10-16(금)」
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return pad(m) + '-' + pad(d) + '(' + WD[new Date(y, m - 1, d).getDay()] + ')';
}
// epoch ms → 「10-14 11:05」
export function stamp(ms: number | null): string {
  if (ms === null) return '';
  const d = new Date(ms);
  return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}
export function plus30(t: string): string {
  const [h, m] = t.split(':').map(Number);
  const x = h * 60 + m + 30;
  return pad(Math.floor(x / 60) % 24) + ':' + pad(x % 60);
}

// 상태 알약(시안 ST)
export const ST: Record<ResvStatus, { name: string; fg: string; bg: string; bd: string }> = {
  requested: { name: '예약 확인중', fg: '#c26a00', bg: '#fff4e0', bd: '#ffd9a0' },
  confirmed: { name: '예약 확정', fg: '#15803d', bg: '#e9f7ee', bd: '#b7e4c7' },
  change_requested: { name: '변경 요청', fg: '#e5484d', bg: '#fff0f0', bd: '#ffd0d2' },
  modify_requested: { name: '수정 확인중', fg: '#c26a00', bg: '#fff4e0', bd: '#ffd9a0' },
  modified: { name: '수정 확정', fg: '#15803d', bg: '#e9f7ee', bd: '#b7e4c7' },
  superseded: { name: '변경됨', fg: '#7a7a7a', bg: '#f3f3f3', bd: '#e0e0e0' },
};
export const OPEN: ResvStatus[] = ['requested', 'modify_requested'];
export const DONE: ResvStatus[] = ['confirmed', 'modified'];

// 바뀐 값은 취소선 → 새 값(D-14)
export interface Seg {
  t: string;
  k?: 'old' | 'new';
}
const diff = (prev: string | undefined, cur: string, pre = ''): Seg[] =>
  prev != null && prev !== cur ? [...(pre ? [{ t: pre }] : []), { t: prev, k: 'old' }, { t: ' → ' }, { t: cur, k: 'new' }] : [{ t: pre + cur }];

// 이전 값 — back 의 before 는 바뀐 칸만 담는다
const prevOf = (r: ResvRequest) => (r.before ? { date: r.before.date ?? r.date, time: r.before.time ?? r.time } : null);

export function dtSegs(r: ResvRequest): Seg[] {
  const p = prevOf(r);
  if (p && p.date !== r.date)
    return [{ t: dayLabel(p.date) + ' ' + p.time, k: 'old' }, { t: ' → ' }, { t: dayLabel(r.date) + ' ' + r.time, k: 'new' }];
  return diff(p?.time, r.time, dayLabel(r.date) + ' ');
}

export interface Chain {
  groupId: number;
  name: string;
  rows: ResvRequest[];
}
// rows 는 이미 묶음 순(최신 묶음 위 · 묶음 안 오래된 줄 위) — 순서를 지키며 묶기만 한다
export function chainsOf(rows: ResvRequest[]): Chain[] {
  const out: Chain[] = [];
  for (const r of rows) {
    const last = out[out.length - 1];
    if (last && last.groupId === r.groupId) last.rows.push(r);
    else out.push({ groupId: r.groupId, name: r.customer.name, rows: [r] });
  }
  return out;
}

// [링키 수정 요청 생성] 대상 — 묶음 마지막 줄 기준: 변경 요청이 먼저, 없으면 가장 최근 확정(시안 modTarget · back 같은 규칙)
export function modTarget(chains: Chain[]): Chain | null {
  const lasts = chains.map((c) => ({ c, r: c.rows[c.rows.length - 1] }));
  const changed = lasts.filter((x) => x.r.status === 'change_requested');
  if (changed.length) return changed.reduce((a, b) => ((b.r.changeAt ?? 0) > (a.r.changeAt ?? 0) ? b : a)).c;
  const done = lasts.filter((x) => DONE.includes(x.r.status));
  return done.length ? done.reduce((a, b) => ((b.r.registeredAt ?? 0) > (a.r.registeredAt ?? 0) ? b : a)).c : null;
}

export const kindLabel = (r: ResvRequest) =>
  r.kind === 'request' ? '예약 요청 · 본사' : r.modifyReason === 'change_request' ? '수정 요청 · 변경 요청 반영' : '수정 요청 · 고객 시간 변경';

// 상태 알약 아래 한 줄 · 비고의 안내 한 줄
export function notes(c: Chain, r: ResvRequest): { stNote: string; plain: string } {
  const i = c.rows.indexOf(r);
  const later = c.rows.slice(i + 1);
  const modReq = later.length > 0;
  switch (r.status) {
    case 'requested':
      return { stNote: 'KOS 등록 전', plain: '' };
    case 'modify_requested':
      return { stNote: 'KOS 수정 전', plain: '' };
    case 'confirmed':
    case 'modified':
      return { stNote: modReq ? '수정 요청 받음 ↓' : stamp(r.registeredAt) + ' 등록', plain: '' };
    case 'change_requested':
      return { stNote: modReq ? '수정 요청 받음 ↓' : '본사 회신 대기', plain: '' };
    case 'superseded': {
      // 바뀐 시각 필드는 없다 — 같은 묶음 다음 수정 확정 줄의 registeredAt(같은 순간)
      const by = later.find((x) => x.kind === 'modify' && x.registeredAt !== null);
      return {
        stNote: (by ? stamp(by.registeredAt) + ' ' : '') + '아래 예약으로 바뀜',
        plain: r.snapshot ? '' : 'KOS 등록 전에 바뀌어 스크린샷이 없어요',
      };
    }
  }
}

// 예약 메모(자동 작성) — back snapshot.memo 와 같은 형식(미리보기는 등록 전이라 front 가 지금 날짜로 만든다)
export function memoOf(r: ResvRequest, at: number): string {
  const d = new Date(at);
  const head = String(d.getFullYear()).slice(2) + '.' + pad(d.getMonth() + 1) + '.' + pad(d.getDate());
  let text = head + '/링키 본사/' + r.proc + '/' + r.lang + ' 통역 필요';
  if (r.before) text += r.before.time !== undefined ? '\n*예약 시간 변경 ' + r.before.time + ' → ' + r.time : '\n*예약 수정';
  return text;
}

// KOS 등록 · 수정 미리보기 표(시안 previewVals)
export function previewRows(r: ResvRequest, now: number): { label: string; segs: Seg[] }[] {
  const c = r.customer;
  const p = prevOf(r);
  return [
    { label: '고객', segs: [{ t: c.name }] },
    { label: '고객 구분', segs: [{ t: c.isNew ? '신규 환자' : '재내원' }] },
    { label: '국적 · 성별', segs: [{ t: c.nat + ' · ' + c.sex }] },
    {
      label: '예약 일정',
      segs:
        p && (p.date !== r.date || p.time !== r.time)
          ? [
              { t: dayLabel(p.date) + ' ' + p.time + ' ~ ' + plus30(p.time), k: 'old' },
              { t: '  →  ' },
              { t: dayLabel(r.date) + ' ' + r.time + ' ~ ' + plus30(r.time), k: 'new' },
            ]
          : [{ t: dayLabel(r.date) + ' ' + r.time + ' ~ ' + plus30(r.time) }],
    },
    { label: '층 / 권역', segs: [{ t: c.zone }] },
    { label: '희망 시술', segs: [{ t: r.proc }] },
    { label: '통역', segs: [{ t: r.lang + ' 통역 필요' }] },
    { label: '예약 메모', segs: [{ t: memoOf(r, now) }] },
  ];
}
export const changedCount = (r: ResvRequest) => {
  const p = prevOf(r);
  return p ? (p.date !== r.date ? 1 : 0) + (p.time !== r.time ? 1 : 0) : 0;
};
