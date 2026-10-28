// 고객 공개 API(SPEC-006 §6.1) — 고객 문진 페이지 /q 만 쓴다. 직원 세션과 분리: lib/session.ts · lib/api.ts 를 쓰지 않고
// Authorization 없이 토큰 헤더 X-Questionnaire-Token 만 싣는다(직원 폰에서 열려도 직원 토큰이 실리지 않는다). 쿠키 · Referer 도 보내지 않는다
// back 주소는 env 로만(lib/api.ts 와 같은 값 · 같은 읽기)
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || '').trim().replace(/\/$/, '');

export type QJson = Record<string, unknown>;

// GET 응답 — 허용 키만(§6.1 · §7.1). form · agreements 는 KOS 그대로
export interface PublicQuestionnaire {
  customerName: string;
  language: { code: string; source: 'kos_language' | 'nationality' | 'default'; options: string[] };
  form: { pages: QJson[] };
  agreements: QJson[];
  prefill: {
    name: string | null;
    phone: { countryCode: string; phoneNumber: string } | null;
    address: string | null;
    addressDetail: string | null;
    dateOfBirth: string | null; // yyyyMMdd(F#2)
    gender: string | null;
  };
  fillUntil: string | null;
}

// POST 본문 — deviceId · displayRequestId 없음(요청 행은 토큰이 정한다)
export interface PublicSubmit {
  language: string;
  name: string;
  dateOfBirth: string;
  gender: string | null;
  phone: { countryCode: string; phoneNumber: string };
  address: string;
  addressDetail: string;
  agreements: QJson[];
  answers: QJson[];
}

// 오류 — 코드만 들고 다닌다(화면은 코드로 문구를 고른다 · 영어 원문 메시지를 보이지 않는다 — §5)
export class PublicError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}

// 토큰 꼴 — base64url 43자(§3.1). 틀리면 back 을 부르지 않는다(§2)
export const isQToken = (t: string) => /^[A-Za-z0-9_-]{43}$/.test(t);

async function call<T>(token: string, method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  if (!API_BASE) throw new PublicError(0, 'config');
  const headers: Record<string, string> = { 'X-Questionnaire-Token': token };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
    });
  } catch {
    throw new PublicError(0, 'network');
  }
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new PublicError(res.status, (data as { error?: { code?: string } } | null)?.error?.code ?? 'error');
  return data as T;
}

export const loadQuestionnaire = (token: string, lang?: string) =>
  call<PublicQuestionnaire>(token, 'GET', '/api/public/questionnaire' + (lang ? '?lang=' + encodeURIComponent(lang) : ''));
export const submitQuestionnaire = (token: string, body: PublicSubmit) => call<{ ok: true }>(token, 'POST', '/api/public/questionnaire', body);
