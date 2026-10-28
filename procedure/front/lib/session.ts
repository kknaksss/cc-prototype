// 로그인 상태 — ccc 토큰 + 역할 · 이름을 localStorage 에(SPEC-004 §3.6). 웹도 다섯 역할 모두(SPEC-004 §3.4 · §6.17)
import type { Role } from './types';

export interface Session {
  token: string;
  id: string;
  expiresAt: string;
  role: Role;
  name: string;
}

const ROLES: Role[] = ['admin', 'doctor', 'nurse', 'coordinator', 'counselor'];

const KEY = 'procedure.session';

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
    if (!s.token || !s.id) return null;
    // 역할이 없는 옛 세션(SPEC-004 전)은 다시 로그인하게 한다
    if (!s.role || !ROLES.includes(s.role)) return null;
    const exp = Date.parse(s.expiresAt ?? '');
    if (Number.isFinite(exp) && exp <= Date.now()) return null;
    return { token: s.token, id: s.id, expiresAt: s.expiresAt ?? '', role: s.role, name: s.name ?? '' };
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
    // 같은 탭의 useSession 도 알게 한다(storage 이벤트는 다른 탭에만 온다)
    window.dispatchEvent(new StorageEvent('storage', { key: KEY }));
  } catch {
    // 무시
  }
}

export const HOME = '/procedures/live';
