// 로그인 상태 — 토큰 없이 localStorage 에 staffId(§7)
import type { Frame } from './types';

export interface Session {
  staffId: string;
  name: string;
  role: string;
  frame: Frame;
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
    if (!s.staffId) return null;
    const role = s.role ?? '';
    // 0.1.0 세션(frame 없음)은 역할로 틀을 짐작하지 않고 다시 로그인하게 한다
    if (s.frame !== 'assigned' && s.frame !== 'rounds' && s.frame !== 'desk') return null;
    return { staffId: s.staffId, name: s.name ?? '', role, frame: s.frame };
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

// 틀별 첫 화면 — back 이 경로를 주면 그 값(데스크 /desk · 직원 /staff)
export function homePath(frame: Frame, home?: string): string {
  if (home && home.startsWith('/')) return home;
  return frame === 'desk' ? '/desk' : '/staff';
}
