// 로그인 상태 — 토큰 없이 localStorage 에 staffId(§6)
export interface Session {
  staffId: string;
  name: string;
  role: string;
}

const KEY = 'cc.session';

export function readSessionRaw(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function readSession(): Session | null {
  return parseSession(readSessionRaw());
}

export function parseSession(raw: string | null): Session | null {
  try {
    if (!raw) return null;
    const s = JSON.parse(raw) as Partial<Session>;
    return s.staffId ? { staffId: s.staffId, name: s.name ?? '', role: s.role ?? '' } : null;
  } catch {
    return null;
  }
}

export function writeSession(s: Session) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // 저장 못 해도 이번 탭에서는 이동한다
  }
}

export function clearSession() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // 무시
  }
}

export const isDeskRole = (role: string) => role === '데스크' || role.toLowerCase() === 'desk';
export const isDoctorRole = (role: string) => role === '의사' || role.toLowerCase() === 'doctor';

// 역할별 첫 화면(§6) — back 이 경로를 주면 그 값을 쓴다
export function homePath(role: string, home?: string): string {
  if (home && home.startsWith('/')) return home;
  return isDeskRole(role) ? '/desk' : '/staff';
}
