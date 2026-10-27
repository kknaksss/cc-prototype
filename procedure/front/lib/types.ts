// back 계약 그대로(SPEC-003 §7.2 · procedure/back/app/schemas/board.py). 시각은 ISO 8601 · KST 오프셋 문자열
export type VisitState = 'waiting' | 'doing' | 'home';
export type ProcState = 'wait' | 'doing' | 'done';
export type CallKind = 'all' | 'one';
export type NeedWhy = 'home' | 'anes' | 'call';
export type KosStatus = 'ok' | 'pending' | 'failed';

export interface SyncInfo {
  lastOkAt: string | null;
  lastError: string | null;
  inWindow: boolean;
}

export interface Doctor {
  id: number;
  name: string;
  busy: boolean;
  busyRoom: string | null;
}

export interface Counts {
  all: number;
  need: number;
  waiting: number;
  anes: number;
  call: number;
  doing: number;
}

export interface Room {
  id: number;
  title: string;
  order: number;
}

export interface Customer {
  name: string;
  phoneticName: string | null;
  nationality: string | null;
  isNew: boolean;
  chartNumber: string | null;
}

export interface Anesthesia {
  runningSince: string | null;
  lastMinutes: number | null;
  canStart: boolean;
  canEnd: boolean;
  long: boolean; // 진행 중 마취가 기준(limits.anesMin) 이상 — back 계산
}

export interface DoctorRef {
  id: number;
  name: string;
}

export interface ProcCall {
  id: number;
  kind: CallKind;
  targetDoctorId: number | null;
  createdAt: string;
  acceptedBy: number | null;
  acceptedAt: string | null;
}

// procedure = KOS PROCEDURE 작업 · etc = ETCETERA 작업. 화면은 둘을 가르지 않는다(전부 같은 시술 줄 — 2026-10-25) · 스냅샷 모양 유지용
export type ProcKind = 'procedure' | 'etc';

export interface Procedure {
  id: number;
  kind?: ProcKind; // 없으면 procedure(back 반영 전 스냅샷 호환)
  isRoomTask: boolean; // 「방 배정」(방이 붙은 ETCETERA) — 화면에 그리지 않는다(2026-10-25 · 판정도 back 이 뺀다)
  kosStatus?: string | null; // KOS 작업 status 원문(NOT_STARTED · READY · WAITING · IN_PROGRESS · DONE · CANCELED) (화면에서 쓰지 않음)
  sequence: number;
  title: string;
  state: ProcState;
  startedAt: string | null;
  completedAt: string | null;
  doctor: DoctorRef | null;
  call: ProcCall | null;
  pickable: boolean;
  canStart: boolean;
  canFinish: boolean;
  // 되돌리기 아이콘(SPEC-003 §5.13) — back 이 계산 · front 는 이 값으로만 그린다. 없으면 false(back 반영 전 스냅샷 호환)
  canUndoStart?: boolean;
  canUndoFinish?: boolean;
}

export interface Need {
  why: NeedWhy;
  since: string;
  limitMin: number;
}

export interface KosState {
  status: KosStatus;
  failed: { op: string; error: string | null }[];
}

export interface Card {
  visitId: number;
  room: Room;
  inAt: string | null;
  homeAt: string | null;
  customer: Customer;
  state: VisitState;
  paymentRequired: boolean;
  orderMemo: string | null;
  anesthesia: Anesthesia;
  procedures: Procedure[];
  canCall: boolean;
  canHome: boolean;
  need: Need | null;
  kos: KosState;
}

export interface OpenCall {
  callId: number;
  visitId: number;
  room: Room;
  customer: { name: string; nationality: string | null };
  kind: CallKind;
  targetDoctorId: number | null;
  createdAt: string;
  procedures: { id: number; title: string }[];
}

export interface RecentAccept {
  at: string;
  room: string;
  doctorName: string;
  count: number;
}

// 「확인이 필요」 기준 분 — back 한 곳에서 정해 싣는다(호출 미수락 · 마취)
export interface Limits {
  callMin: number;
  anesMin: number;
}

export interface Board {
  now: string;
  limits: Limits;
  sync: SyncInfo;
  doctors: Doctor[];
  counts: Counts;
  cards: Card[];
  calls: OpenCall[];
  recentAccepts: RecentAccept[];
}

// SSE `board` 이벤트 본문(§7.5)
export interface BoardEvent extends Board {
  version: number;
}

// 계정 역할(SPEC-004 §3.1 · SPEC-005 §3.4 코디 더함)
export type Role = 'admin' | 'doctor' | 'nurse' | 'coordinator';

// POST /api/auth/login(SPEC-004 §3.3)
export interface LoginResult {
  token: string;
  expiresAt: string;
  id: string;
  role: Role;
  name: string;
  staffId: number | null;
}

// GET /api/auth/me
export interface Me {
  id: string;
  role: Role;
  name: string;
  staffId: number | null;
}

export type CallTarget = { kind: 'all' } | { kind: 'one'; doctorId: number };

// PUT /api/board/order(SPEC-003 §7.3) — 요청 {visitIds} · 응답 = 거르기 뒤 저장된 목록
export interface BoardOrderResult {
  ok: true;
  visitIds: number[];
}

// ─── 예약 현황(SPEC-005 §7) — back 계약 그대로. 규칙 값(full · plusAllowed · draggable · can.* …)은 back 이 계산(§5 머리)
// 시각 = ISO(KST +09:00) · 날짜 = YYYY-MM-DD · 「HH:MM」 = KST 그날 시각 · id = ccc 정수 id

// §5.1 2계층 상태
export type ResvMain = 'reserved' | 'reception' | 'consultation' | 'procedure' | 'home' | 'canceled' | 'noshow';
export type ResvSub = 'waiting' | 'doing' | 'done' | null;
export interface ResvState {
  main: ResvMain;
  sub: ResvSub;
}
// back 은 KOS 값 그대로 문자열(MALE · FEMALE · GENDER_UNSPECIFIED)
export type Gender = string | null;

export interface ResvZone {
  zoneId: number;
  title: string;
  order: number;
  isDefault: boolean;
}

export interface HmRange {
  start: string; // HH:MM
  end: string;
}

// §7.2 칸 — groupId null = 「그룹 없음」 칸(§5.2)
export interface ResvColumn {
  groupId: number | null;
  title: string;
  order: number;
  intervalMinutes: number;
  count: number;
  capacities: { zoneId: number; capacity: number }[];
  open: HmRange[];
}

export interface ResvCardCustomer {
  customerId: number | null;
  name: string;
  phoneticName: string | null;
  gender: Gender;
  nationality: string | null;
  isNew: boolean;
}

// 묶음(occupiedResources) 하나당 한 장(§5.2)
export interface ResvCard {
  reservationId: number;
  resourceIndex: number;
  groupId: number | null;
  zoneId: number | null;
  start: string; // ISO
  end: string;
  customer: ResvCardCustomer;
  state: ResvState;
  paymentRequiredCount: number;
  draggable: boolean;
}

export interface ResvSlot {
  groupId: number;
  zoneId: number;
  start: string; // ISO
  end: string;
  capacity: number | null;
  count: number | null;
  full: boolean;
}

export interface ResvRow {
  groupId: number;
  start: string; // ISO
  plusAllowed: boolean;
}

export interface ResvCounts {
  total: number;
  reserved: number;
  reception: number;
  consultation: number;
  procedure: number;
  home: number;
  canceled: number;
  noshow: number;
}

export interface ResvNotice {
  id: number;
  content: string;
  releasedAt: string | null;
}

export interface Money {
  total: number | null;
  paid: number | null;
  currency: string | null;
}

export interface ClinicItem {
  reservationId: number;
  zoneId: number | null;
  customer: { name: string; phoneticName: string | null; nationality: string | null };
  state: ResvState;
  receptionAt: string | null;
  paymentRequiredCount: number;
  amount: Money | null;
}

export interface Clinic {
  counts: { all: number; reception: number; consultation: number; procedure: number; home: number };
  items: ClinicItem[];
}

// GET /api/reservations/board?date=
export interface ResvBoard {
  date: string;
  isToday: boolean;
  now: string;
  sync: { lastOkAt: string | null; lastError: string | null };
  axis: HmRange | null;
  zones: ResvZone[];
  columns: ResvColumn[];
  cards: ResvCard[];
  slots: ResvSlot[];
  rows: ResvRow[];
  counts: ResvCounts;
  notices: ResvNotice[];
  requests: unknown[]; // D-07 자리만 — 늘 빈 배열
  clinic: Clinic | null; // 오늘만
}

// §7.3 예약 상세
export interface PhoneValue {
  countryCode: string | null;
  number: string | null;
}

export interface Personal {
  name: string | null;
  phoneticName: string | null;
  gender: Gender;
  dateOfBirth: string | null;
  registrationNumber: string | null;
  passportNumber: string | null;
  passportSurname: string | null;
  passportGivenNames: string | null;
  passportExpiryDate: string | null;
  foreignRegistrationNumber: string | null;
  nationality: string | null;
  language: string | null;
  phone: PhoneValue | null;
  additionalPhone: PhoneValue | null;
  email: string | null;
  sns: { type: string | null; accountId: string | null } | null;
  address: { address: string | null; detailed: string | null; zipCode: string | null } | null;
}

export interface IdentityField {
  key: string;
  label: string;
  filled: boolean;
}

export interface Identity {
  status: 'confirmed' | 'unconfirmed';
  checkedAt: string | null;
  checkedBy: string | null;
  method: string | null;
  kind: 'foreign' | 'domestic';
  fields: IdentityField[];
  complete: boolean;
}

export interface StaffRef {
  staffId: number | null;
  name: string;
}

export interface HealthItem {
  title: string;
  answer: string | null;
  memo: string | null;
  needsCheck: boolean;
  empty: boolean;
}

export interface PreviousVisit {
  date: string;
  start: string | null;
  result: 'completed' | 'noshow' | 'canceled' | 'other';
  resultRaw: string | null;
  zoneTitle: string | null;
  groupTitle: string | null;
  reservationMemo: string | null;
  consultationMemo: string | null;
  procedures: { title: string; status: string | null; doctors: string[] }[];
}

export interface Flow {
  receptionAt: string | null;
  roomTitle: string | null;
  receptionBy: string | null;
  consultation: {
    state: 'none' | 'waiting' | 'doing' | 'done';
    counselor: StaffRef | null;
    since: string | null;
    calledAt: string | null;
    calledBy: string | null;
  } | null;
  stages: { procedure: 'none' | 'waiting' | 'doing' | 'done'; home: 'none' | 'waiting' | 'done' };
}

export interface Settlement {
  paymentRequiredCount: number;
  amount: Money | null;
  prescriptionCount: number;
  links: { purchase: string; prescription: string } | null;
}

export interface ResvCan {
  cancel: boolean;
  editRoute: boolean;
  receive: boolean;
  addConsultation?: boolean; // [+ 상담 추가](E2E #15)
  callCounselor: boolean;
  discharge: boolean;
  editMemo: boolean;
  editPersonal: boolean;
  editRemark: boolean;
  confirmIdentity: boolean;
  unconfirmIdentity: boolean;
}

export interface ResvDetail {
  reservationId: number;
  day: string;
  start: string | null;
  end: string | null;
  groupTitle: string | null;
  zoneId: number | null;
  zoneTitle: string | null;
  state: ResvState;
  customer: {
    customerId: number;
    name: string;
    phoneticName: string | null;
    gender: Gender;
    nationality: string | null;
    isNew: boolean;
    chartNumber: string | null;
    age: number | null;
    personal: Personal | null;
    personalError: string | null;
    remark: string | null;
    identity: Identity;
  };
  reservation: {
    sedationRequired: boolean;
    memo: string | null;
    funnel: { name: string | null; detail: string | null } | null;
    connectedChannel: string | null;
    counselor: StaffRef | null;
    assignee: { name: string } | null;
    doctors: { name: string }[];
    desiredDischargeAt: string | null;
  };
  health: { state: 'none' | 'ok' | 'error'; submittedAt: string | null; needCount: number; items: HealthItem[] };
  previousVisits: PreviousVisit[];
  flow: Flow | null;
  settlement: Settlement | null;
  rooms: { roomId: number; title: string; busy: boolean; selected: boolean }[];
  roomLocked: boolean;
  receiveMode: 'new' | 'resume' | null;
  counselors: { staffId: number; name: string; busyRoom: string | null }[];
  can: ResvCan;
}

// §7.4 등록 모달
export interface StaffItem {
  staffId: number;
  name: string;
}

export interface ResvForm {
  staff: StaffItem[];
  defaultAssigneeStaffId: number | null;
  counselors: StaffItem[];
  funnels: { funnelId: number; name: string }[];
  zones: { zoneId: number; title: string; available: boolean }[];
  defaultZoneId: number | null;
  snsTypes?: string[]; // KOS snsInfo.snsType enum(E2E #23)
}

export interface CustomerHit {
  customerId: number;
  chartNumber: string | null;
  name: string;
  phoneticName: string | null;
  dateOfBirth: string | null;
  nationality: string | null;
  isNew: boolean;
}

export interface CustomerSearch {
  items: CustomerHit[];
  total: number;
  page: number;
  pageSize: number;
}

// [접수 완료] 진행 경로(E2E #13) — 접수 때 고르는 ccc 값 · KOS consultationRequired 와 다르다
export type ReceiveRoute = 'consultation' | 'direct';

export interface CustomerSearchQuery {
  name?: string;
  phone?: string;
  birth?: string;
  chart?: string;
  page?: number;
}

// §7.5 POST /api/reservations
export interface NewCustomer {
  name: string;
  phoneticName?: string;
  gender?: 'MALE' | 'FEMALE';
  dateOfBirth?: string;
  nationality?: string;
  phone?: { countryCode: string; number: string };
  email?: string;
  sns?: { type: string; accountId: string };
  passportNumber?: string;
}

export interface CreateReservation {
  groupId: number;
  zoneId?: number;
  start: string;
  customer: { customerId: number } | { new: NewCustomer };
  assigneeStaffId?: number;
  counselorStaffId?: number;
  funnelId?: number;
  funnelDetail?: string;
  memo?: string;
  desiredDischargeTime?: string;
}

// 409 duplicated_visitor 의 error.candidate
export interface DuplicateCandidate {
  customerId: number;
  name: string;
  chartNumber: string | null;
  dateOfBirth: string | null;
}
