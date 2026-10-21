// 현황판 v4 시안의 화면 계산(도면 · 직군 색 · 상태 색 · 단계 표시).
// 상태를 바꾸는 계산(배정 · 시작 · 종료 · 귀가 …)과 고객 상태 문구는 back 이 한다 — 여기에는 읽기 계산만 둔다.
import type { Board, BoardCustomer, CustomerStatus, Role, StepKind, StepState } from './types';
import { fmtElapsed, pad, toMs } from './time';

export const ROLES: Role[] = ['의사', '상담사', '피부관리사', '간호사', '코디'];
// 직군 점 색 — 의사 · 상담사 · 코디는 v3 그대로, 피부관리사 · 간호사 추가(시안 v4)
export const ROLE_COLOR: Record<string, string> = {
  고객: '#3e3e3e',
  의사: '#ac47ff',
  상담사: '#fd9400',
  피부관리사: '#15803d',
  간호사: '#e0569b',
  코디: '#2498bd',
  데스크: '#3e3e3e',
};
export const RTITLE: Record<Role, string> = { 의사: '원장', 상담사: '상담사', 피부관리사: '피부관리사', 간호사: '간호사', 코디: '코디' };
export const KIND: Record<StepKind, string> = { consult: '상담', doctor_consult: '원장 상담', procedure: '시술' };
// 단계 종류별 배정 직군(§5.3)
export const KIND_ROLES: Record<StepKind, Role[]> = {
  consult: ['상담사'],
  doctor_consult: ['의사'],
  procedure: ['의사', '피부관리사'],
};

type Variant = 'neutral' | 'primary' | 'warning' | 'danger' | 'purple';
export const SSTATE: Record<StepState, { name: string; variant: Variant; dot: boolean }> = {
  planned: { name: '예정', variant: 'neutral', dot: false },
  assigned: { name: '대기', variant: 'warning', dot: true },
  in_progress: { name: '진행 중', variant: 'primary', dot: true },
  done: { name: '완료', variant: 'neutral', dot: false },
  skipped: { name: '진행 안 함', variant: 'neutral', dot: false },
};

// 방 상태 4종(시안 BOX · STATUS) — 확인 필요 = 빨강(0.3.0 §0-b 10)
export type BoxKey = 'wait' | 'consult' | 'treat' | 'need';
export const BOX: Record<BoxKey, string> = {
  wait: 'bg-yellow-100 border-ms-gray-400 text-ms-gray-800',
  consult: 'bg-purple-100 border-purple text-ms-gray-800',
  treat: 'bg-primary-100 border-primary text-ms-gray-800',
  need: 'bg-red-100 border-red text-ms-gray-800',
};
export const STATUS: Record<BoxKey, { name: string; variant: Variant }> = {
  wait: { name: '대기', variant: 'warning' },
  consult: { name: '상담', variant: 'purple' },
  treat: { name: '시술', variant: 'primary' },
  need: { name: '확인 필요', variant: 'danger' },
};
export const KEYS: BoxKey[] = ['wait', 'consult', 'treat', 'need'];
export const EMPTY = 'bg-ms-white border-ms-gray-300 text-ms-gray-500';

// back 상태 → 화면 칸 색. 확인 필요(need)가 먼저, 접수 후 대기는 대기
export const boxKey = (s: CustomerStatus | null): BoxKey =>
  !s ? 'wait' : s.need ? 'need' : s.key === 'consult' || s.key === 'treat' ? s.key : 'wait';

// 도면 — back rooms(시안 LAYOUT) 의 격자 위치를 그대로 쓴다
export const capOf = (id: string) => (/^t\d/.test(id) ? 2 : /^(c\d|s\d)/.test(id) ? 1 : 0);
export const isSleep = (id: string | null | undefined) => /^s\d/.test(id || '');
// 방 이름 — 현황판은 back rooms, 직원 화면(rooms 없음)은 칸 id 규칙으로(시안 v4 ROOMNAME)
export function roomName(id: string | null | undefined, rooms?: { id: string; name: string }[]): string {
  if (!id) return '';
  const fromApi = rooms?.find((r) => r.id === id)?.name;
  if (fromApi) return fromApi;
  if (id === 'reception') return '접수대기실';
  const m = /^([cst])(\d+)$/.exec(id);
  if (!m) return id;
  const n = m[2].padStart(2, '0');
  return m[1] === 'c' ? '관리실 ' + n : m[1] === 's' ? '수면시술실 ' + n : '2인관리실 ' + n;
}

type D = Pick<Board, 'customers'>;
export const hereCustomers = (d: D) => d.customers.filter((c) => c.location);
export const custIn = (d: D, id: string) => d.customers.filter((c) => c.location === id);
export const canPlace = (d: D, id: string) =>
  capOf(id) > custIn(d, id).length && !d.customers.some((c) => c.location && c.prevRoom === id);

export const staffRole = (board: Pick<Board, 'staff'>, staffId: string | null) =>
  board.staff.find((s) => s.staffId === staffId)?.role;

export const hhmm = (ms: number | null | undefined) => {
  if (ms === null || ms === undefined) return '';
  const d = new Date(ms);
  return pad(d.getHours()) + ':' + pad(d.getMinutes());
};

export const won = (n: number) => '₩ ' + Number(n).toLocaleString('ko-KR');

export const pickCls = (on: boolean) =>
  on ? 'bg-primary-100 border-primary text-ms-gray-800' : 'bg-ms-white border-ms-gray-300 text-ms-gray-800';
export const checkBox = (on: boolean) =>
  on ? 'bg-primary border-primary text-ms-white' : 'bg-ms-white border-ms-gray-400 text-ms-white';

// 고객 탭 · 방 패널 번호 원
export function stepNum(state: StepState) {
  const now = state === 'in_progress';
  const past = state === 'done' || state === 'skipped';
  return {
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

export const customerById = (board: Board, id: string | null): BoardCustomer | undefined =>
  board.customers.find((c) => c.scheduleId === id);

// 현황 두 줄(SPEC-002 §5.5) — 1줄 현재 상태 · 2줄 경과 시간. 현황에 보이는 곳은 전부 이 함수를 쓴다.
// 1줄: 대기 계열(reception · wait — 진행 중인 단계 없음) = back 상태 라벨 + 「 중」, 진행 계열 = 진행 중인 단계 이름(back 라벨)
// 2줄: `<종류> N분 경과` — 종류 = back 상태 key(wait · reception → 대기 · consult → 상담 · treat → 시술).
//      시간 = 지금 상태가 시작된 뒤(back `since` — 상태가 바뀌면 since = now), 형식 D-28
// long: 대기 계열이고 30분 이상 → 2줄 빨강
export const LONG_WAIT_MIN = 30;
export function stateLines(
  status: CustomerStatus | null,
  since: number | null | undefined,
  now: number,
): { state: string; elapsed: string; long: boolean } | null {
  if (!status) return null;
  const waiting = status.key === 'wait' || status.key === 'reception';
  const kind = status.key === 'consult' ? '상담' : status.key === 'treat' ? '시술' : '대기';
  const t = fmtElapsed(since, now);
  const at = toMs(since);
  return {
    state: waiting ? status.label + ' 중' : status.label,
    // 1분 미만(fmtElapsed 「방금」)은 「<종류> 1분 미만」
    elapsed: !t ? '' : t === '방금' ? kind + ' 1분 미만' : kind + ' ' + t + ' 경과',
    long: waiting && at !== null && now - at >= LONG_WAIT_MIN * 60000,
  };
}
// 2줄 글자 — 오래 기다림은 빨강
export const elapsedCls = (long: boolean, base = 'text-typo-caption-md-500 text-ms-gray-700') =>
  long ? 'text-typo-caption-md-600 text-red' : base;
