// back 호출은 이 모듈에서만 한다(rules: 컴포넌트에서 직접 fetch 금지). 주소는 env 로만(SPEC-003 §2.3)
import { readSession } from './session';
import type {
  BoardOrderResult,
  CallTarget,
  CreateReservation,
  CustomerSearch,
  CustomerSearchQuery,
  DuplicateCandidate,
  LoginResult,
  Me,
  Personal,
  ResvBoard,
  ResvDetail,
  ResvForm,
} from './types';

// NEXT_PUBLIC_* 는 Next 가 빌드(또는 dev 시작) 때 번들에 박는다 — 값은 둘 중 하나로 들어온다
//   · compose / docker build: 빌드 인자 NEXT_PUBLIC_API_BASE_URL(Dockerfile ARG → ENV)
//   · front 만 따로(npm run dev): procedure/front/.env.local(gitignore · 이름은 .env.example)
// 비어 있으면 같은 출처(:3700/api)로 가 404 가 나므로, 부르지 않고 설정 오류를 알린다
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || '').trim().replace(/\/$/, '');
export const CONFIG_ERROR = API_BASE
  ? null
  : 'back 주소(NEXT_PUBLIC_API_BASE_URL)가 비어 있어요 — procedure/front/.env.local 또는 빌드 인자로 넣고 front 를 다시 띄우세요';

// 오류 본문 {error:{code,message,step?,candidate?,fields?}} — 예약 조작은 셋을 더 싣는다(SPEC-005 §7.1 · §7.5)
export interface ApiErrorExtra {
  step?: string;
  candidate?: DuplicateCandidate;
  fields?: string[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public extra: ApiErrorExtra = {},
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: { method?: 'GET' | 'POST' | 'PUT'; body?: unknown }): Promise<T> {
  if (CONFIG_ERROR) throw new ApiError(0, 'config', CONFIG_ERROR);
  const headers: Record<string, string> = {};
  const token = readSession()?.token;
  if (token) headers.Authorization = 'Bearer ' + token;
  if (init?.body !== undefined) headers['Content-Type'] = 'application/json';
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method: init?.method ?? 'GET',
      headers,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: 'no-store',
    });
  } catch {
    throw new ApiError(0, 'network', '서버에 연결할 수 없어요');
  }
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } & ApiErrorExtra } | null)?.error;
    throw new ApiError(res.status, err?.code ?? 'error', err?.message ?? '요청을 처리하지 못했어요', {
      step: err?.step,
      candidate: err?.candidate,
      fields: err?.fields,
    });
  }
  return data as T;
}

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body });
const put = <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body });
const qs = (q: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== '') p.set(k, String(v));
  const t = p.toString();
  return t ? '?' + t : '';
};

// 로그인 — 아이디 + 비밀번호(필수). 틀리면 401 invalid_credentials · 여러 번 틀리면 429(잠금)
export const login = (id: string, password: string) => post<LoginResult>('/api/auth/login', { id, password });
export const me = () => request<Me>('/api/auth/me');

// §7.5 SSE — EventSource 는 헤더를 못 실어 ?token=
export const streamUrl = (token: string) => `${API_BASE}/api/board/stream?token=${encodeURIComponent(token)}`;

// §7.3 조작 — 응답은 {ok…} 만. 화면은 뒤따르는 board 이벤트로 바뀐다
export const anesStart = (visitId: number) => post<{ ok: true }>(`/api/visits/${visitId}/anesthesia/start`);
export const anesEnd = (visitId: number) => post<{ ok: true }>(`/api/visits/${visitId}/anesthesia/end`);
export const createCall = (visitId: number, procedureIds: number[], target: CallTarget) =>
  post<{ callId: number }>(`/api/visits/${visitId}/calls`, { procedureIds, target });
export const acceptCall = (callId: number, doctorId: number) =>
  post<{ acceptedProcedureIds: number[] }>(`/api/calls/${callId}/accept`, { doctorId });
export const reassignAll = (callId: number) => post<{ callId: number }>(`/api/calls/${callId}/reassign-all`);
export const startProcedure = (procedureId: number) =>
  post<{ ok: true; flowStepChanged: boolean }>(`/api/procedures/${procedureId}/start`);
export const finishProcedure = (procedureId: number) => post<{ ok: true }>(`/api/procedures/${procedureId}/finish`);
// §7.3 되돌리기(§5.13) — 본문 없음. undo-start 의 flowStepChanged = 고객을 시술 대기로 돌렸나
export const undoStart = (procedureId: number) =>
  post<{ ok: true; flowStepChanged: boolean }>(`/api/procedures/${procedureId}/undo-start`);
export const undoFinish = (procedureId: number) => post<{ ok: true }>(`/api/procedures/${procedureId}/undo-finish`);
export const goHome = (visitId: number) => post<{ ok: true }>(`/api/visits/${visitId}/home`);
// §7.3 카드 순서 — 귀가 대기 아닌 카드 전부의 새 순서(필터로 숨긴 카드 포함). 응답 visitIds = 거르기 뒤 저장된 목록
export const putBoardOrder = (visitIds: number[]) => request<BoardOrderResult>('/api/board/order', { method: 'PUT', body: { visitIds } });

// ─── 예약 현황(SPEC-005 §7) — 조작은 KOS 응답을 기다린다(동기 · §4.4). 실패 = 409 kos_rejected · 502 kos_unavailable · 가짜 보드 403 fake_board
type Ok = { ok: true };

// §7.2 스케줄 표 — date 생략 = 오늘(KST)
export const reservationBoard = (date?: string) => request<ResvBoard>('/api/reservations/board' + qs({ date }));
// §7.3 예약 상세
export const reservationDetail = (id: number) => request<ResvDetail>(`/api/reservations/${id}`);
// §7.4 등록 모달 칸 · 고객 검색
export const reservationForm = (q: { date: string; groupId: number; start: string }) => request<ResvForm>('/api/reservations/form' + qs(q));
export const searchCustomers = (q: CustomerSearchQuery) => request<CustomerSearch>('/api/customers/search' + qs({ ...q }));
// §7.5 조작
export const createReservation = (body: CreateReservation) => post<{ reservationId: number; customerId: number }>('/api/reservations', body);
export const moveReservation = (id: number, resourceIndex: number, groupId: number, start: string) =>
  post<Ok>(`/api/reservations/${id}/move`, { resourceIndex, groupId, start });
export const cancelReservation = (id: number, reason: 'CANCELED' | 'NO_SHOW') => post<Ok>(`/api/reservations/${id}/cancel`, { reason });
export const saveReservationMemo = (id: number, memo: string) => put<Ok>(`/api/reservations/${id}/memo`, { memo });
export const saveRoute = (id: number, consultationRequired: boolean) => put<Ok>(`/api/reservations/${id}/route`, { consultationRequired });
export const receive = (id: number, roomId: number) => post<{ ok: true; flowStep: string | null }>(`/api/reservations/${id}/reception`, { roomId });
export const callCounselor = (id: number, staffId: number) => post<Ok>(`/api/reservations/${id}/counselor-call`, { staffId });
export const discharge = (id: number) => post<Ok>(`/api/reservations/${id}/discharge`);
export const savePersonal = (customerId: number, personal: Partial<Personal>) => put<Ok>(`/api/customers/${customerId}/personal`, { personal });
export const saveRemark = (customerId: number, memo: string) => put<Ok>(`/api/customers/${customerId}/remark`, { memo });
export const setIdentity = (customerId: number, status: 'confirmed' | 'unconfirmed') => put<Ok>(`/api/customers/${customerId}/identity`, { status });
