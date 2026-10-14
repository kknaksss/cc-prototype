// back 호출은 이 모듈에서만 한다(rules: 컴포넌트에서 직접 fetch 금지).
import type {
  Board,
  LoginResult,
  MutationResult,
  PatientDetail,
  ProcedureCandidate,
  StaffAccount,
  StaffHome,
  StepInput,
} from './types';

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8600').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: { method?: 'GET' | 'POST'; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method: init?.method ?? 'GET',
      headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: 'no-store',
    });
  } catch {
    throw new ApiError(0, 'network', '서버에 연결할 수 없어요');
  }
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(res.status, err?.code ?? 'error', err?.message ?? '요청을 처리하지 못했어요');
  }
  return data as T;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body });

// §5.2 읽기
export const getBoard = () => request<Board>('/api/board');
export const getStaffList = () => request<StaffAccount[]>('/api/staff');
export const getStaffHome = (staffId: string) => request<StaffHome>(`/api/staff/${encodeURIComponent(staffId)}/home`);
// staffId 를 주면 그 직원의 버튼(myActions)이 온다
export const getPatient = (scheduleId: string, staffId?: string) =>
  request<PatientDetail>(
    `/api/patients/${encodeURIComponent(scheduleId)}` + (staffId ? `?staffId=${encodeURIComponent(staffId)}` : ''),
  );
export const getProcedureCandidates = (scheduleId: string) =>
  request<ProcedureCandidate[]>(`/api/patients/${encodeURIComponent(scheduleId)}/procedure-candidates`);

// §7 로그인 — 비밀번호는 받기만 한다
export const login = (staffId: string, password: string) => post<LoginResult>('/api/login', { staffId, password });

// §5.3 데스크 조작 — 응답 {version}
export const checkIn = (scheduleId: string, steps: StepInput[]) =>
  post<MutationResult>('/api/desk/check-in', { scheduleId, steps });
export const place = (scheduleId: string, room: string) => post<MutationResult>('/api/desk/place', { scheduleId, room });
export const moveSleep = (scheduleId: string, room: string) =>
  post<MutationResult>('/api/desk/move-sleep', { scheduleId, room });
export const returnRoom = (scheduleId: string) => post<MutationResult>('/api/desk/return-room', { scheduleId });
export const assign = (stepId: string, staffId: string) => post<MutationResult>('/api/desk/assign', { stepId, staffId });
export const unassign = (stepId: string) => post<MutationResult>('/api/desk/unassign', { stepId });
// 묶음마다 다음 1장(같은 id 두 번 = 2장)
export const addProcedures = (scheduleId: string, bundleIds: string[]) =>
  post<MutationResult>('/api/desk/add-procedures', { scheduleId, bundleIds });
export const reorder = (scheduleId: string, stepIds: string[]) =>
  post<MutationResult>('/api/desk/reorder', { scheduleId, stepIds });
// [결제 완료] — 수납필요 해제 · 미결제 0 · 시술권 연결(결제 자체는 KOS 에서 한다)
// ============kos api 연동 필요 ========================
// 공식 getPurchaseSummariesByVisitor · getTicketBundlesQuery (KOS 결제 조회)
// ======================================================
export const paymentComplete = (scheduleId: string) =>
  post<MutationResult>('/api/desk/payment-complete', { scheduleId });
// 노쇼 — 예약 st → noshow
// ============kos api 연동 필요 ========================
// 공개 없음 — KOS 요청(예약 상태 노쇼)
// ======================================================
export const noShow = (scheduleId: string) => post<MutationResult>('/api/desk/no-show', { scheduleId });
export const discharge = (scheduleId: string) => post<MutationResult>('/api/desk/discharge', { scheduleId });
export const undo = (version: number) => post<MutationResult>('/api/desk/undo', { version });
export const resetBoard = () => post<MutationResult>('/api/admin/reset', {});

// 직원 본인 — 시작 · 종료
export const startStep = (staffId: string, stepId: string) =>
  post<MutationResult>(`/api/staff/${encodeURIComponent(staffId)}/start`, { stepId });
export const finishStep = (staffId: string, stepId: string) =>
  post<MutationResult>(`/api/staff/${encodeURIComponent(staffId)}/finish`, { stepId });

// §5.2 SSE — `event: state` `data: {"version": n}`. 화면 안 구독자는 연결 하나를 같이 쓴다.
// 끊기면 EventSource 가 알아서 다시 붙고, 붙을 때마다(open) 한 번 다시 읽는다(끊긴 사이 변경을 놓치지 않게)
type StateListener = (version: number | null) => void;
const listeners = new Set<StateListener>();
let source: EventSource | null = null;

export function subscribeState(onState: StateListener): () => void {
  listeners.add(onState);
  if (!source) {
    source = new EventSource(API_BASE + '/api/events');
    source.addEventListener('state', (e) => {
      let v: number | null = null;
      try {
        v = (JSON.parse((e as MessageEvent<string>).data) as { version?: number }).version ?? null;
      } catch {
        v = null;
      }
      listeners.forEach((l) => l(v));
    });
    source.addEventListener('open', () => listeners.forEach((l) => l(null)));
  }
  return () => {
    listeners.delete(onState);
    if (!listeners.size && source) {
      source.close();
      source = null;
    }
  };
}

// §7 통역 WS — `ws://<back>/api/interpret` (계약: interpret-ws-contract.md). 주소는 API_BASE 의 http→ws
export function openInterpretSocket(): WebSocket {
  const ws = new WebSocket(API_BASE.replace(/^http/, 'ws') + '/api/interpret');
  ws.binaryType = 'arraybuffer';
  return ws;
}
