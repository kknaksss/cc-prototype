'use client';

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { subscribeState } from './api';
import { parseSession, readSessionRaw, type Session } from './session';

// 1초마다 지금 시각 — 경과 타이머용
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

// 로그인 안 했으면 /login 으로(§6). 확인 전에는 null
const subscribeStorage = (cb: () => void) => {
  window.addEventListener('storage', cb);
  return () => window.removeEventListener('storage', cb);
};

export function useSession(): Session | null {
  const router = useRouter();
  // 서버 렌더에서는 undefined(아직 모름), 브라우저에서는 저장된 값 또는 null
  const raw = useSyncExternalStore<string | null | undefined>(subscribeStorage, readSessionRaw, () => undefined);
  const session = useMemo(() => (raw === undefined ? null : parseSession(raw)), [raw]);
  useEffect(() => {
    if (raw !== undefined && !session) router.replace('/login');
  }, [raw, session, router]);
  return session;
}

// 그 화면의 GET 을 부르고, SSE state 이벤트마다 다시 부른다(§5.2 D-29)
export function useLive<T>(load: (() => Promise<T>) | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  const seq = useRef(0);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  const reload = useCallback(async () => {
    const fn = loadRef.current;
    if (!fn) return;
    const my = ++seq.current;
    try {
      const d = await fn();
      if (my === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (my === seq.current) setError(e instanceof Error ? e.message : '불러오지 못했어요');
    }
  }, []);

  useEffect(() => {
    if (!load) return;
    void reload();
    return subscribeState(() => void reload());
  }, [load, reload]);

  return { data, error, reload };
}
