// back 호출은 이 모듈에서만 한다(rules: 컴포넌트에서 직접 fetch 금지). 주소는 env 로만(SPEC-003 §2.3)
import { readSession } from './session';
import type { CallTarget, LoginResult, Me } from './types';

// NEXT_PUBLIC_* 는 Next 가 빌드(또는 dev 시작) 때 번들에 박는다 — 값은 둘 중 하나로 들어온다
//   · compose / docker build: 빌드 인자 NEXT_PUBLIC_API_BASE_URL(Dockerfile ARG → ENV)
//   · front 만 따로(npm run dev): procedure/front/.env.local(gitignore · 이름은 .env.example)
// 비어 있으면 같은 출처(:3700/api)로 가 404 가 나므로, 부르지 않고 설정 오류를 알린다
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || '').trim().replace(/\/$/, '');
export const CONFIG_ERROR = API_BASE
  ? null
  : 'back 주소(NEXT_PUBLIC_API_BASE_URL)가 비어 있어요 — procedure/front/.env.local 또는 빌드 인자로 넣고 front 를 다시 띄우세요';

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
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(res.status, err?.code ?? 'error', err?.message ?? '요청을 처리하지 못했어요');
  }
  return data as T;
}

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body });

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
export const goHome = (visitId: number) => post<{ ok: true }>(`/api/visits/${visitId}/home`);
