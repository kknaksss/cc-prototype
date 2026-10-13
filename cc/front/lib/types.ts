// SPEC-001 §5 · §6 계약 모양 — back 응답(JSON camelCase)을 그대로 받는 타입.
// 시각 값(since)은 epoch ms 숫자(계약 보충 2026-10-13). 화면용 시각 문자열은 HH:MM.

export type Role = '의사' | '상담사' | '코디';
export type StepKind = 'consult' | 'doctor' | 'treat' | 'sleep' | 'calm';
export type TimeValue = number;

export interface OrderStep {
  kind: StepKind;
  label: string;
  role: Role;
}

// §5.1 customers[]
export interface BoardCustomer {
  scheduleId: string;
  name: string;
  room: string | null;
  order: OrderStep[];
  step: number;
  since: TimeValue;
  prev: string | null;
  done: boolean;
}

// §5.1 staff[]
export interface BoardStaff {
  staffId: string;
  name: string;
  role: Role;
  queue: string[];
  home: string;
}

export type ResvState = 'booked' | 'checked' | 'noshow' | 'canceled';

// §5.1 resv[]
export interface Reservation {
  scheduleId: string | null;
  time: string;
  name: string;
  procedure: string;
  doctor: string;
  st: ResvState;
}

// 현황판 칸(시안 LAYOUT). back 이 주면 이름을 그쪽 값으로 쓴다
export interface BoardRoom {
  id: string;
  name: string;
}

// GET /api/board
export interface Board {
  customers: BoardCustomer[];
  staff: BoardStaff[];
  resv: Reservation[];
  rooms?: BoardRoom[];
  version: number;
}

// §5.3 조작 응답
export interface MutationResult {
  version: number;
}

// GET /api/staff
export interface StaffAccount {
  staffId: string;
  name: string;
  role: string; // 데스크 | 의사 | 코디 (상담사 등 다른 값도 올 수 있음)
}

// POST /api/login
export interface LoginResult {
  staffId: string;
  name: string;
  role: string;
  home: string;
}

// 현황판 상태 키 — 시안 STATUS (lounge = 라운지 대기)
export type BoardState = 'lounge' | 'wait' | 'consult' | 'treat';

// GET /api/staff/{staffId}/home 의 환자 한 줄
export interface HomePatient {
  scheduleId: string;
  name: string;
  nationality: string;
  time: string; // 예약 시각 HH:MM
  procedure: string; // 오더 요약(「첫 시술 외 n」)
  room: string | null; // 현황판 칸 id — 귀가/도착 전이면 null
  state: BoardState | null;
  label: string; // 현황판 라벨(원장 대기 · 마무리 대기 …)
  since: TimeValue | null;
}

export interface DoctorHome {
  current: HomePatient | null;
  next: HomePatient | null;
  done: HomePatient[];
}

export interface CodiHome {
  patients: HomePatient[]; // 경과 긴 순
  summary: { wait: number; consult: number; treat: number };
}

export type StaffHome = DoctorHome | CodiHome;

// GET /api/patients/{scheduleId} — §5.5
export interface Caution {
  text: string;
  source: string;
}

export interface MemoSection {
  lines: string[];
  source: string; // 「오더 메모 · 상담실장 ○○」 같은 출처 줄
}

export interface RouteStep {
  room: string; // 현황판 칸 이름(대응표 적용 뒤)
  task: string;
  staff: string; // 「원장 ○○ · 담당자」
  status: 'done' | 'now' | 'later' | 'canceled';
  readyAt: string | null; // HH:MM
  completedAt: string | null; // HH:MM
  memo: string; // 끝난 작업의 assigneeMemo
}

export interface HistoryItem {
  label: string; // 이 병원 · 타 병원
  value: string;
  source: string;
}

export interface Ticket {
  name: string;
  left: number;
  total: number;
  expires: string;
  role: Role;
  sleep: boolean;
}

export interface PatientDetail {
  scheduleId: string;
  name: string;
  nationality: string;
  sex: string;
  age: number | null;
  firstVisit: boolean;
  reservationTime: string;
  leaveTime: string | null; // 귀가 시각 HH:MM
  outTime: string | null; // 아웃 시각(메모 원문) — 없으면 숨김
  counselor: string | null;
  doctors: string[];
  board: { room: string; state: BoardState; label: string; since: TimeValue } | null;
  cautions: Caution[]; // ① — 고객 메모가 있으면 맨 앞
  order: (MemoSection & { anesthesia: string | null }) | null; // ②
  consult: MemoSection | null; // ③
  reception: MemoSection | null; // ④
  chart: { label: string; value: string }[];
  history: HistoryItem[];
  route: RouteStep[];
  tickets?: Ticket[]; // 접수 모달용(보유 시술권) — 없으면 「보유 시술권이 없어요」
}
