// SPEC-001 0.2.1 계약 — `cc/back/README.md` 의 요청 · 응답 예시 그대로(JSON camelCase).
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

export type ResvState = 'booked' | 'checked' | 'canceled';

export interface Reservation {
  scheduleId: string;
  time: string;
  name: string;
  isNew: boolean;
  nationality: string;
  procedure: string; // KOS 예약 칸 그대로 — 비면 「-」
  doctor: string;
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

// GET /api/patients/{scheduleId}?staffId=
export interface Caution {
  text: string;
  source: string;
}

export interface MemoSection {
  lines: string[];
  source: string;
}

export interface RouteStep extends Omit<Step, 'assigneeName'> {
  assigneeName: string | null;
  memo: string; // 그 시술 단계 done 일 때만 — 담당자 메모
}

export interface PastSchedule {
  date: string;
  consult: MemoSection | null;
  order: MemoSection | null;
  procedures: string[];
  synthetic: boolean;
}

export interface MyAction {
  stepId: string;
  kind: StepKind;
  action: 'start' | 'finish';
  label: string; // 상담 시작 · 상담 종료 · 시술 시작 · 시술 종료
}

export interface PatientDetail {
  scheduleId: string;
  name: string;
  nationality: string;
  sex: string;
  age: number | null;
  isNew: boolean;
  reservationTime: string;
  flowStep: FlowStep;
  location: string | null;
  prevRoom: string | null;
  status: CustomerStatus | null;
  since: TimeValue | null;
  leaveTime: string | number | null;
  outTime: string | null;
  counselor: string | null;
  doctors: string[];
  memoRevealed: boolean;
  unpaidAmount: number;
  paid: boolean;
  cautions: Caution[];
  order: (MemoSection & { anesthesia: string | null }) | null;
  consult: MemoSection | null;
  reception: MemoSection | null;
  chart: { label: string; value: string }[];
  history: { label: string; value: string; source: string }[];
  pastSchedules: PastSchedule[];
  route: RouteStep[];
  tickets: { name: string; left: number; total: number }[];
  myActions: MyAction[];
}

// GET /api/patients/{id}/procedure-candidates — 시술 후보(§5.4)
export interface ProcedureCandidate {
  kind: StepKind;
  label: string;
  ticketId: string | null;
  kosSequence: number | null;
  source: 'ticket' | 'task';
}

// 접수 · 시술 추가 요청의 단계 한 줄
export interface StepInput {
  kind: StepKind;
  label?: string;
  ticketId?: string | null;
  kosSequence?: number | null;
}
