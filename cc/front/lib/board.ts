// 현황판 v3 시안의 화면 계산(도면 · 정원 · 상태 · 대기 라벨 · 단계 표시).
// 상태를 바꾸는 계산(commit · assign · complete …)은 back 이 한다 — 여기에는 읽기 계산만 둔다.
import type { Board, BoardCustomer, BoardStaff, OrderStep, Role, Ticket } from './types';

export const ROLE_DOT: Record<string, string> = {
  고객: 'bg-ms-gray-800',
  의사: 'bg-purple',
  상담사: 'bg-yellow',
  코디: 'bg-primary',
};
export const RLABEL: Record<Role, string> = { 의사: '원장', 상담사: '상담사', 코디: '코디' };
export const ROLE_ORDER: Role[] = ['의사', '상담사', '코디'];

export type StatusKey = 'wait' | 'consult' | 'treat';
export const STATUS: Record<StatusKey, { name: string; variant: 'neutral' | 'purple' | 'primary'; cls: string }> = {
  wait: { name: '대기', variant: 'neutral', cls: 'bg-yellow-100 border-ms-gray-400 text-ms-gray-800' },
  consult: { name: '상담', variant: 'purple', cls: 'bg-purple-100 border-purple text-ms-gray-800' },
  treat: { name: '시술', variant: 'primary', cls: 'bg-primary-100 border-primary text-ms-gray-800' },
};
export const KEYS: StatusKey[] = ['wait', 'consult', 'treat'];
export const EMPTY = 'bg-ms-white border-ms-gray-300 text-ms-gray-500';
export const STAFFED = 'bg-ms-white border-ms-gray-300 text-ms-gray-800';

// 도면 — 시안 LAYOUT (방 id · 이름 · 격자 위치)
const TRACK: Record<number, number> = { 1: 1, 2: 2, 3: 4, 4: 5, 5: 6, 6: 8 };
export const CORRIDORS = [{ row: 3 }, { row: 7 }];
export interface LayoutRoom {
  id: string;
  name: string;
  col: number;
  row: number;
  cs: number;
}
const p2 = (n: number) => String(n).padStart(2, '0');
const RM = (id: string, name: string, col: number, row: number, cs = 1): LayoutRoom => ({
  id,
  name,
  col,
  row: TRACK[row],
  cs,
});
const care = (n: number, col: number, row: number) => RM('c' + p2(n), '관리실 ' + p2(n), col, row);
export const LAYOUT: LayoutRoom[] = [
  RM('t02', '2인관리실 02', 3, 1, 2),
  RM('t03', '2인관리실 03', 5, 1, 2),
  care(11, 3, 2),
  care(12, 4, 2),
  care(13, 5, 2),
  care(14, 6, 2),
  care(15, 7, 2),
  care(16, 8, 2),
  RM('desk', '데스크', 1, 3),
  RM('lounge', '라운지', 2, 3, 2),
  RM('info2', '인포 2', 7, 3),
  RM('s02', '수면실 02', 8, 3),
  RM('consult', '상담실', 2, 4),
  care(4, 6, 4),
  RM('s03', '수면실 03', 8, 4),
  care(1, 1, 5),
  care(2, 2, 5),
  care(3, 3, 5),
  RM('info1', '인포 1', 4, 5),
  RM('s01', '수면실 01', 8, 5),
  care(5, 1, 6),
  care(6, 2, 6),
  care(7, 3, 6),
  care(8, 4, 6),
  care(9, 5, 6),
  care(10, 6, 6),
  RM('t01', '2인관리실 01', 7, 6, 2),
];

export function roomName(id: string | null | undefined, rooms?: { id: string; name: string }[]): string {
  if (!id) return '';
  if (id === 'office') return '원장실';
  const fromApi = rooms?.find((r) => r.id === id);
  if (fromApi) return fromApi.name;
  return LAYOUT.find((r) => r.id === id)?.name ?? id;
}
export const capOf = (id: string) => (/^t\d/.test(id) ? 2 : /^(c\d|s\d)/.test(id) ? 1 : 0);
export const isSleep = (id: string | null | undefined) => /^s\d/.test(id || '');

type D = Pick<Board, 'customers' | 'staff'>;
export const custIn = (d: D, id: string) => d.customers.filter((c) => !c.done && c.room === id);
export const presentIn = (d: D, id: string) => d.staff.filter((s) => s.queue[0] === id);
export const queuedIn = (d: D, id: string) => d.staff.filter((s) => s.queue.indexOf(id) > 0);
export const canPlace = (d: D, id: string) =>
  capOf(id) > custIn(d, id).length && !d.customers.some((c) => !c.done && c.prev === id);

export function waitLabel(c: BoardCustomer, step: OrderStep | undefined): string {
  if (!step) return '마무리 대기';
  if (step.kind === 'sleep' && !isSleep(c.room)) return '수면실 이동 대기';
  if (step.kind === 'doctor') return '원장 대기';
  if (step.kind === 'consult') return '상담사 대기';
  return RLABEL[step.role] + ' 대기 · ' + step.label;
}

export function statusOf(d: D, id: string): { key: StatusKey; label: string } | null {
  const cs = custIn(d, id);
  if (!cs.length || id === 'lounge') return null;
  const c = cs[0];
  const step = c.order[c.step];
  if (presentIn(d, id).length)
    return {
      key: step && (step.kind === 'consult' || step.kind === 'doctor') ? 'consult' : 'treat',
      label: step ? step.label : '마무리',
    };
  return { key: 'wait', label: waitLabel(c, step) };
}

export interface StepView {
  n: number;
  label: string;
  role: string;
  numCls: string;
  textCls: string;
}
export function stepView(s: OrderStep, i: number, cur: number): StepView {
  const past = i < cur;
  const now = i === cur;
  return {
    n: i + 1,
    label: s.label,
    role: RLABEL[s.role],
    numCls: now
      ? 'bg-primary border-primary text-ms-white'
      : past
        ? 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-500'
        : 'bg-ms-white border-primary text-primary',
    textCls: now
      ? 'text-typo-caption-md-600 text-primary'
      : past
        ? 'text-typo-caption-md-400 text-ms-gray-500'
        : 'text-typo-caption-md-400 text-ms-gray-800',
  };
}

export const pickCls = (on: boolean) =>
  on ? 'bg-primary-100 border-primary text-primary' : 'bg-ms-white border-ms-gray-300 text-ms-gray-800';

// 접수 모달 — 고른 시술권으로 오더 만들기(시안 buildOrder). 결과는 check-in 요청의 입력값
const S = (kind: OrderStep['kind'], label: string, role: Role): OrderStep => ({ kind, label, role });
const CO = S('consult', '상담', '상담사');
const DR = S('doctor', '원장 진료', '의사');
const CA = S('calm', '진정 관리', '코디');
export function buildOrder(tickets: Ticket[], sel: number[], consult: boolean): OrderStep[] {
  const o: OrderStep[] = [];
  if (consult) o.push(CO);
  const ch = tickets.filter((t, i) => sel.includes(i) && t.left > 0);
  if (ch.length) {
    o.push(DR);
    ch.forEach((t) => o.push(t.sleep ? S('sleep', t.name, '의사') : S('treat', t.name, t.role || '의사')));
    o.push(CA);
  }
  return o;
}

export const staffById = (staff: BoardStaff[], id: string | null) => staff.find((s) => s.staffId === id);

// 「 · 고객 단계」 — 직원 현재/다음 줄
export function taskAt(d: D, id: string): string {
  const cs = custIn(d, id);
  if (!cs.length) return '';
  const c = cs[0];
  const st = c.order[c.step];
  return ' · ' + c.name + (st ? ' ' + st.label : '');
}
