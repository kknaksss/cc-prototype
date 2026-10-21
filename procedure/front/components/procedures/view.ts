// 화면 문구 · 색 · 정렬 — 스냅샷 값을 보여 주는 방법만. 규칙(pickable · canStart · canCall · need …)은 back 이 준 값을 쓴다(SPEC-003 §7.2)
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

// 현황 탭 상태 수 6칸 = 카드 필터(SPEC-003 §6.4). 수는 스냅샷 counts
export type FilterId = 'all' | 'need' | 'waiting' | 'anes' | 'call' | 'doing';
export const FILTERS: { id: FilterId; name: string; cls: string }[] = [
  { id: 'all', name: '전체', cls: 'bg-ms-white border-ms-gray-300 text-ms-gray-800' },
  { id: 'need', name: '확인', cls: 'bg-red-100 border-red text-red' },
  { id: 'waiting', name: '대기', cls: 'bg-yellow-100 border-ms-gray-400 text-ms-gray-800' },
  { id: 'anes', name: '마취', cls: 'bg-purple-100 border-purple text-ms-gray-800' },
  { id: 'call', name: '호출', cls: 'bg-ms-white border-primary text-primary' },
  { id: 'doing', name: '진행', cls: 'bg-primary-100 border-primary text-ms-gray-800' },
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

// 정렬 — 입실순 = 입실 시각 · 배치순 = 방 순서. 귀가 대기는 뒤에(귀가 대기 시각 순) — §6.3
export type SortKey = 'in' | 'room';
export function orderedCards(cards: Card[], sort: SortKey): Card[] {
  const key = sort === 'room' ? (c: Card) => c.room.order : (c: Card) => toMs(c.inAt) ?? Infinity;
  const live = cards.filter((c) => c.state !== 'home').sort((a, b) => key(a) - key(b));
  const home = cards
    .filter((c) => c.state === 'home')
    .sort((a, b) => (toMs(a.homeAt) ?? Infinity) - (toMs(b.homeAt) ?? Infinity));
  return [...live, ...home];
}

export const isEtc = (p: Procedure) => p.kind === 'etc';

// etc 줄 상태 글자 — KOS 화면 말(대기중 · 준비중 · 호출함 · 진행중 · 완료 · 취소). kosStatus 가 없으면 state 로
const KOS_STATUS: Record<string, string> = {
  NOT_STARTED: '대기중',
  READY: '준비중',
  WAITING: '호출함',
  IN_PROGRESS: '진행중',
  PROGRESS: '진행중',
  DONE: '완료',
  COMPLETED: '완료',
  CANCELED: '취소',
  CANCELLED: '취소',
};
export function etcStatus(p: Procedure): string {
  if (p.kosStatus && KOS_STATUS[p.kosStatus]) return KOS_STATUS[p.kosStatus];
  return p.state === 'done' ? '완료' : p.state === 'doing' ? '진행중' : '대기중';
}

// 시술 표시 순서 — ETCETERA 작업(sequence 순)을 맨 위에 따로, 그 아래 시술: 완료(완료 시각 순) → 진행 → 대기(sequence 순) — §5.9
export function orderedProcs(c: Card): Procedure[] {
  const etc = c.procedures.filter(isEtc).sort((a, b) => a.sequence - b.sequence);
  const procs = c.procedures.filter((p) => !isEtc(p));
  const done = procs.filter((p) => p.state === 'done').sort((a, b) => (toMs(a.completedAt) ?? 0) - (toMs(b.completedAt) ?? 0));
  const doing = procs.filter((p) => p.state === 'doing');
  const wait = procs.filter((p) => p.state === 'wait').sort((a, b) => a.sequence - b.sequence);
  return [...etc, ...done, ...doing, ...wait];
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
  label: string; // 카드 머리 오른쪽 경과 글자
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
    label: (need.why === 'anes' ? '마취 ' : need.why === 'call' ? '호출 ' : '완료 뒤 ') + (min < 1 ? '1분 미만' : min + '분 경과'),
    hasLimit,
    limitText: hasLimit ? '기준 ' + limit + '분' : '',
    overText: hasLimit ? (over > 0 ? '+' + over + '분 초과' : '기준 도달') : '시술 완료 뒤 ' + min + '분',
    barPct: hasLimit ? Math.min(100, Math.round((limit / Math.max(min, limit, 1)) * 100)) + '%' : '0%',
  };
}

// 카드 강조 — 고른 카드 실선 · 나머지 흐림 0.45 · 귀가 대기 0.55
export function cardLook(c: Card, focus: number | null): { outline: string; opacity: number } {
  const on = focus != null && c.visitId === focus;
  return {
    outline: on ? '2px solid var(--ms-primary)' : 'none',
    opacity: c.state === 'home' ? 0.55 : focus != null && !on ? 0.45 : 1,
  };
}
