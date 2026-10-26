// 화면 문구 · 색 · 카드 순서 — 스냅샷 값을 보여 주는 방법만. 규칙(pickable · canStart · canCall · need …)은 back 이 준 값을 쓴다(SPEC-003 §7.2)
import type { BadgeVariant } from '@medisolve-ai/medikit';
import { hm, minutesSince, toMs } from '@/lib/time';
import type { Board, Card, Need, OpenCall, Procedure, VisitState } from '@/lib/types';

export const STATE_NAME: Record<VisitState, string> = { waiting: '시술 대기', doing: '시술 진행', home: '귀가 대기' };
export const STATE_BADGE: Record<VisitState, BadgeVariant> = { waiting: 'warning', doing: 'primary', home: 'neutral' };

export const LEGEND: { name: string; variant: BadgeVariant }[] = [
  { name: '시술 대기', variant: 'warning' },
  { name: '마취 중', variant: 'purple' },
  { name: '시술 진행', variant: 'primary' },
  { name: '확인 필요', variant: 'danger' },
  { name: '귀가 대기', variant: 'neutral' },
];

// 현황 탭 상태 수 6칸 = 3 × 2 · 점 · 칸 바탕 없음 = 카드 필터(SPEC-003 §6.4 · 시안 M:945-955). 수는 스냅샷 counts
export type FilterId = 'all' | 'need' | 'waiting' | 'anes' | 'call' | 'doing';
export const FILTERS: { id: FilterId; name: string; dot: string }[] = [
  { id: 'all', name: '전체', dot: 'bg-ms-gray-300' },
  { id: 'need', name: '확인', dot: 'bg-red' },
  { id: 'waiting', name: '대기', dot: 'bg-yellow' },
  { id: 'anes', name: '마취', dot: 'bg-purple' },
  { id: 'call', name: '호출', dot: 'bg-primary-500' },
  { id: 'doing', name: '진행', dot: 'bg-primary' },
];

// 칸 정의(§6.4) — 스냅샷 필드로 고른다: 확인 = need · 마취 = 진행 중 마취 · 호출 = calls 에 그 고객이 있음
export function filterFn(id: FilterId, board: Board): (c: Card) => boolean {
  if (id === 'need') return (c) => !!c.need;
  if (id === 'waiting') return (c) => c.state === 'waiting';
  if (id === 'anes') return (c) => c.state !== 'home' && !!c.anesthesia.runningSince;
  if (id === 'call') return (c) => c.state !== 'home' && board.calls.some((k) => k.visitId === c.visitId);
  if (id === 'doing') return (c) => c.state === 'doing';
  return () => true;
}

export const visitCls = (isNew: boolean) =>
  isNew ? 'bg-primary-100 text-primary text-typo-caption-md-600' : 'bg-ms-gray-200 text-ms-gray-700 text-typo-caption-md-600';
export const checkBox = (on: boolean) => (on ? 'bg-primary border-primary text-ms-white' : 'bg-ms-white border-ms-gray-400 text-ms-white');

export const docName = (board: Board, id: number | null | undefined) =>
  id == null ? '' : (board.doctors.find((d) => d.id === id)?.name ?? '');

// 카드 순서 = 스냅샷 cards[] 순서 그대로(back 이 정렬 · SPEC-003 §5.12 · §6.3). front 는 다시 정렬하지 않고,
// 놓은 뒤 응답을 기다리는 동안만 로컬 순서(귀가 대기 아닌 카드 id 목록)를 덧씌운다(§5.12 「놓은 뒤 화면」 ①)
//   · 로컬 목록 안의 카드 = 로컬 차례 → 로컬 목록에 없는 새 카드 = 스냅샷 차례로 그 뒤 → 귀가 대기 = 맨 뒤 스냅샷 차례
//   · 그사이 귀가 대기가 된 카드는 귀가 대기 묶음으로 · 사라진 카드는 빠진다
export function withLocalOrder(cards: Card[], local: number[] | null): Card[] {
  if (!local) return cards;
  const live = cards.filter((c) => c.state !== 'home');
  const byId = new Map(live.map((c) => [c.visitId, c]));
  const inLocal = local.map((id) => byId.get(id)).filter((c): c is Card => !!c);
  const rest = live.filter((c) => !local.includes(c.visitId));
  return [...inLocal, ...rest, ...cards.filter((c) => c.state === 'home')];
}

// 귀가 대기 아닌 카드 id 차례 — 드래그 · 저장 목록(필터로 숨긴 카드 포함)
export const liveIds = (cards: Card[]) => cards.filter((c) => c.state !== 'home').map((c) => c.visitId);

// 방향 따라 끼우기(§5.12) — 앞 · 뒤 판정은 드래그 시작 때의 순서(ids) 기준. 앞이던 카드 → 대상 뒤 · 뒤이던 카드 → 대상 앞
export function moveCard(ids: number[], from: number, target: number): number[] {
  const fi = ids.indexOf(from);
  const ti = ids.indexOf(target);
  if (fi < 0 || ti < 0 || from === target) return ids;
  const rest = ids.filter((id) => id !== from);
  const at = rest.indexOf(target) + (fi < ti ? 1 : 0);
  return [...rest.slice(0, at), from, ...rest.slice(at)];
}

// 응답 뒤 「같음」(§5.12 ②) — 스냅샷 귀가 대기 아닌 카드 중 응답 visitIds 에 든 것의 차례 =
// 응답 visitIds 중 그 스냅샷에서 귀가 대기 아닌 카드로 남은 것의 차례(새 카드 · 귀가 대기 · 사라진 카드는 비교에서 뺀다)
export function sameOrder(cards: Card[], saved: number[]): boolean {
  const live = liveIds(cards);
  const a = live.filter((id) => saved.includes(id));
  const b = saved.filter((id) => live.includes(id));
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

// 카드의 보이는 작업 = 「방 배정」만 뺀 전부(type 무관 · 2026-10-25). 작업 목록은 늘 이것으로 읽는다
export const procsOf = (c: Card): Procedure[] => c.procedures.filter((p) => !p.isRoomTask);

// 시술 표시 순서 — 진행 → 대기(sequence 순) → 완료(완료 시각 순) — §5.9 · 시안 M:1500.
// KOS 작업 type(PROCEDURE · ETCETERA) 구분 없이 전부 같은 시술 줄 · 「방 배정」만 숨김(2026-10-25 사용자 결정)
export function orderedProcs(c: Card): Procedure[] {
  const procs = procsOf(c);
  const done = procs.filter((p) => p.state === 'done').sort((a, b) => (toMs(a.completedAt) ?? 0) - (toMs(b.completedAt) ?? 0));
  const doing = procs.filter((p) => p.state === 'doing');
  const wait = procs.filter((p) => p.state === 'wait').sort((a, b) => a.sequence - b.sequence);
  return [...doing, ...wait, ...done];
}

const callText = (board: Board, kind: 'all' | 'one', target: number | null) =>
  kind === 'all' ? '전체 호출' : docName(board, target) + ' 지정 호출';

// 시술 줄 둘째 줄(§5.9)
export function procLine(board: Board, p: Procedure): { text: string; cls: string } {
  const base = 'text-typo-caption-md-500 text-ms-gray-700';
  const who = p.doctor?.name ?? '';
  if (p.state === 'done') {
    const span = (p.startedAt ? hm(p.startedAt) : '') + '~' + hm(p.completedAt);
    return { text: (who ? who + ' · ' : '') + span, cls: 'text-typo-caption-md-400 text-ms-gray-500' };
  }
  if (p.state === 'doing') return { text: (who ? who + ' · ' : '') + hm(p.startedAt) + ' 시작', cls: base };
  if (p.call && p.call.acceptedBy != null)
    return { text: (docName(board, p.call.acceptedBy) || who) + ' 수락 · 시작 가능', cls: 'text-typo-caption-md-600 text-primary' };
  if (p.call) return { text: callText(board, p.call.kind, p.call.targetDoctorId) + ' · 수락 전', cls: base };
  if (p.doctor) return { text: p.doctor.name, cls: base };
  return { text: '담당의 미정', cls: 'text-typo-caption-md-400 text-ms-gray-500' };
}

// 그 고객의 받을 시술이 남은 호출 중 가장 이른 것
export const firstOpenCall = (board: Board, visitId: number): OpenCall | null =>
  board.calls
    .filter((k) => k.visitId === visitId)
    .sort((a, b) => (toMs(a.createdAt) ?? 0) - (toMs(b.createdAt) ?? 0))[0] ?? null;

// 「확인이 필요」 표시(§5.8) — 이유 · 시작점 · 기준은 스냅샷 need 그대로
export interface NeedView {
  state: string; // 상태 배지 자리 문구
  kind: string;
  min: number;
  hasLimit: boolean;
  limitText: string;
  overText: string;
  barPct: string;
}
export function needView(board: Board, c: Card, need: Need, now: number): NeedView {
  const min = minutesSince(need.since, now);
  let state = '시술 모두 완료 · 귀가 대기 전';
  if (need.why === 'anes') state = '마취 중';
  if (need.why === 'call') {
    const k = firstOpenCall(board, c.visitId);
    state = (k ? callText(board, k.kind, k.targetDoctorId) : '호출') + ' · 수락 전';
  }
  const hasLimit = need.why !== 'home';
  const limit = need.limitMin;
  const over = min - limit;
  return {
    state,
    kind: need.why === 'anes' ? '마취' : need.why === 'call' ? '호출' : '귀가 대기',
    min,
    hasLimit,
    limitText: hasLimit ? '기준 ' + limit + '분' : '',
    overText: hasLimit ? (over > 0 ? '+' + over + '분 초과' : '기준 도달') : '시술 완료 뒤 ' + min + '분',
    barPct: hasLimit ? Math.min(100, Math.round((limit / Math.max(min, limit, 1)) * 100)) + '%' : '0%',
  };
}

// 카드 강조 — 고른 카드 실선. 불투명도 우선순위: 끄는 중 0.35 → 귀가 대기 0.55 → 강조 밖 0.45(§6.3 · 시안 M:1475)
export function cardLook(c: Card, focus: number | null, dragging: boolean): { outline: string; opacity: number; shadow: string } {
  const on = focus != null && c.visitId === focus;
  return {
    outline: on ? '2px solid var(--ms-primary)' : 'none',
    opacity: dragging ? 0.35 : c.state === 'home' ? 0.55 : focus != null && !on ? 0.45 : 1,
    shadow: dragging ? '0 0 0 2px var(--ms-primary)' : 'none',
  };
}
