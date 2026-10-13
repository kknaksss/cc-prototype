// SPEC-001 0.3.0 계약 — `cc/back/README.md` 의 요청 · 응답 예시 그대로(JSON camelCase).
// 시각은 전부 epoch ms(숫자). 화면용 시각 문자열(예약 시각 등)은 HH:MM.

export type Role = '의사' | '상담사' | '피부관리사' | '간호사' | '코디';
export type Frame = 'assigned' | 'rounds' | 'desk';
export type TimeValue = number;

export type StepKind = 'consult' | 'doctor_consult' | 'procedure';
export type StepState = 'planned' | 'assigned' | 'in_progress' | 'done' | 'skipped';
export type FlowStep =
  | 'RESERVED'
  | 'RECEPTION'
  | 'CONSULTATION_WAITING'
  | 'CONSULTATION'
  | 'PROCEDURE_WAITING'
  | 'PROCEDURE'
  | 'PROCEDURE_DONE'
  | 'COMPLETED';

export type StatusKey = 'reception' | 'wait' | 'consult' | 'treat';
export type Need = 'next' | 'discharge' | null;

// 고객 지금 상태(§5.1 방 상태) — 귀가 · 접수 전이면 null
export interface CustomerStatus {
  key: StatusKey;
  label: string;
  need: Need;
}

// 동선 단계 — 시술은 시술권 1장 = 한 줄
export interface Step {
  stepId: string;
  order: number;
  kind: StepKind;
  label: string;
  kosSequence: number | null;
  ticketId: string | null;
  assigneeId: string | null;
  assigneeName: string | null;
  state: StepState;
  assignedAt: TimeValue | null;
  startedAt: TimeValue | null;
  endedAt: TimeValue | null;
  paymentRequired: boolean;
}

// GET /api/board customers[] — 귀가한 고객도 남는다(location null · COMPLETED · status null)
export interface BoardCustomer {
  scheduleId: string;
  name: string;
  isNew: boolean;
  nationality: string;
  location: string | null; // null · "reception"(접수대기실) · 방 id
  prevRoom: string | null;
  flowStep: FlowStep;
  receptionAt: TimeValue | null;
  completedAt: TimeValue | null;
  since: TimeValue | null;
  unpaidAmount: number;
  paid: boolean;
  status: CustomerStatus | null;
  mentionedStaffIds: string[]; // 지금 보이는 메모 원문에 이름이 나오는 오늘 근무 직원(배정 셀렉터 맨 위)
  steps: Step[];
}

// 직원의 지금 일(배정 · 진행 중 단계)
export interface StaffWork {
  stepId: string;
  scheduleId: string;
  customerName: string;
  location: string | null;
  kind: StepKind;
  label: string;
  state: StepState;
}

export interface BoardStaff {
  staffId: string;
  name: string;
  role: Role;
  frame: Frame;
  work: StaffWork[];
}

export type ResvState = 'booked' | 'checked' | 'canceled' | 'noshow';

export interface Reservation {
  scheduleId: string;
  time: string;
  name: string;
  isNew: boolean;
  nationality: string;
  st: ResvState;
}

export interface BoardRoom {
  id: string;
  name: string;
  col: number;
  row: number;
  cs: number;
  cap: number;
  unpaidAmount: number;
}

// GET /api/board
export interface Board {
  rooms: BoardRoom[];
  corridors: { row: number }[];
  customers: BoardCustomer[];
  staff: BoardStaff[];
  resv: Reservation[];
  riskWords: string[]; // 강조할 위험 단어(설정 CC_RISK_WORDS)
  version: number;
  now: TimeValue;
}

// 조작 응답
export interface MutationResult {
  version: number;
}

// GET /api/staff
export interface StaffAccount {
  staffId: string;
  name: string;
  role: Role | '데스크';
  frame: Frame;
}

// POST /api/login
export interface LoginResult {
  staffId: string;
  name: string;
  role: Role | '데스크';
  frame: Frame;
  home: string;
}

// GET /api/staff/{id}/home — 배정형 한 줄(내 단계 + 그 고객)
export interface AssignedItem {
  stepId: string;
  scheduleId: string;
  kind: StepKind;
  label: string;
  state: StepState;
  assignedAt: TimeValue | null;
  startedAt: TimeValue | null;
  endedAt: TimeValue | null;
  name: string;
  nationality: string;
  isNew: boolean;
  location: string | null;
  time: string;
  status: CustomerStatus | null;
  unpaidAmount: number;
}

export interface AssignedHome {
  frame: 'assigned';
  current: AssignedItem | null;
  next: AssignedItem[];
  done: AssignedItem[];
}

// 순회형 한 줄 — 지금 내원 고객
export interface RoundsPatient {
  scheduleId: string;
  name: string;
  nationality: string;
  isNew: boolean;
  location: string | null;
  prevRoom: string | null;
  time: string;
  status: CustomerStatus | null;
  need: Need;
  since: TimeValue | null;
  unpaidAmount: number;
  procedures: { stepId: string; label: string; state: StepState; assigneeName: string | null }[];
}

export interface RoundsHome {
  frame: 'rounds';
  patients: RoundsPatient[];
  summary: { wait: number; consult: number; treat: number; needNext: number; needDischarge: number };
}

export type StaffHome = AssignedHome | RoundsHome;

// GET /api/patients/{scheduleId}?staffId= — 환자 상세 · 예약 상세 공통. 메모는 원문 그대로
// 0.3.0 — 담당자 메모는 방문 카드에만(동선에는 없다)
export type RouteStep = Step;

// 방문 카드 — 방문(일정) 하나당. 오늘 카드는 접수 뒤에만, 상담 · 오더는 오늘 상담 종료 뒤(locked false)
export interface Visit {
  date: string; // YYYY-MM-DD
  today: boolean;
  locked: boolean;
  counselors: string[];
  consultation: string | null;
  orderMemo: string | null;
  procedures: string[];
  assigneeMemos: { label: string; memo: string }[];
  synthetic?: boolean;
}

export interface MyAction {
  stepId: string;
  kind: StepKind;
  action: 'start' | 'finish';
  label: string; // 상담 시작 · 상담 종료 · 시술 시작 · 시술 종료
}

export interface TicketBundle {
  bundleId: string;
  name: string;
  left: number;
  total: number;
}

export interface PatientDetail {
  scheduleId: string;
  name: string;
  nationality: string;
  sex: string;
  age: number | null;
  isNew: boolean;
  reservationTime: string;
  reservationStatus: ResvState;
  requestedProcedures: string[];
  flowStep: FlowStep;
  location: string | null;
  prevRoom: string | null;
  status: CustomerStatus | null;
  since: TimeValue | null;
  leaveTime: string | number | null;
  outTime: string | number | null; // KOS desiredDischargeDateTimeUtc 만
  counselor: string | null;
  doctors: string[];
  unpaidAmount: number;
  paid: boolean;
  memoRevealed: boolean;
  customerMemo: string | null;
  reservationMemo: string | null;
  visits: Visit[]; // 최근이 위
  riskWords: string[];
  riskHits: string[];
  mentionedStaffIds: string[];
  chart: { label: string; value: string }[];
  route: RouteStep[];
  tickets: TicketBundle[];
  myActions: MyAction[];
}

// GET /api/patients/{id}/procedure-candidates — 시술 후보 = 묶음 n/m, 고르면 1회
export interface ProcedureCandidate {
  bundleId: string;
  kind: StepKind;
  name: string;
  left: number;
  total: number;
  source: 'today' | 'ticket';
  paymentRequired?: boolean;
}

// 접수 단계 한 줄 — kind(상담 · 원장 상담 직접) 또는 bundleId(묶음의 다음 1장)
export type StepInput = { kind: 'consult' | 'doctor_consult' } | { bundleId: string };
