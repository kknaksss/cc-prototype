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

// procedure = KOS PROCEDURE 작업 · etc = 「방 배정」 같은 ETCETERA 작업(보기만 — 버튼 · 체크 · 호출 없음)
export type ProcKind = 'procedure' | 'etc';

export interface Procedure {
  id: number;
  kind?: ProcKind; // 없으면 procedure(back 반영 전 스냅샷 호환)
  kosStatus?: string | null; // KOS 작업 status 원문(NOT_STARTED · READY · WAITING · IN_PROGRESS · DONE · CANCELED) — etc 줄 상태 글자
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

// 계정 역할(SPEC-004 §3.1)
export type Role = 'admin' | 'doctor' | 'nurse';

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
