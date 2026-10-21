'use client';

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import * as api from './api';
import { clearSession, parseSession, readSessionRaw, type Session } from './session';
import type { Board, BoardEvent } from './types';

// 폰 · 탭 경계 760px — cc 기능 front 의 hooks.ts 와 같은 기준. 서버 렌더는 넓은 쪽
const WIDE = '(min-width: 760px)';
const subscribeWide = (cb: () => void) => {
  const mq = window.matchMedia(WIDE);
  mq.addEventListener('change', cb);
  return () => mq.removeEventListener('change', cb);
};
export function useWide(): boolean {
  return useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => true);
}

// 1초마다 지금 시각 — 경과 타이머용
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

// 로그인 안 했으면 /login 으로. 확인 전에는 null
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

export interface Live {
  board: Board | null;
  // 서버 시각 - 브라우저 시각(ms). 경과 시간은 이만큼 보정한다(SPEC-003 §6.6)
  skew: number;
  connected: boolean;
  error: string | null; // 연결 전에 알 수 있는 문제(back 주소 미설정)
}

// SSE 하나로 첫 화면 · 갱신(SPEC-003 §7.5). 폴링 없음
// - 연결되면 back 이 전체 스냅샷 1개를 바로 보낸다 → 그것으로 그린다
// - 받으면 통째로 바꾼다. 지금 가진 version 보다 작거나 같으면 버린다(같은 연결 안에서)
// - 끊기면 EventSource 기본 재연결(retry 3000). 다시 붙으면 version 을 새로 받는다(back 재시작 시 0 부터)
// - 401 이면 EventSource 가 닫힌다 → /api/auth/me 로 확인해 로그인이 풀렸으면 /login
export function useBoardStream(token: string | null): Live {
  const [live, setLive] = useState<Live>({ board: null, skew: 0, connected: false, error: api.CONFIG_ERROR });

  useEffect(() => {
    if (!token || api.CONFIG_ERROR) return;
    let es: EventSource | null = null;
    let version = -1;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const open = () => {
      if (stopped) return;
      es = new EventSource(api.streamUrl(token));
      es.onopen = () => {
        version = -1;
        setLive((l) => ({ ...l, connected: true }));
      };
      es.addEventListener('board', (e) => {
        let ev: BoardEvent;
        try {
          ev = JSON.parse((e as MessageEvent<string>).data) as BoardEvent;
        } catch {
          return;
        }
        if (typeof ev.version === 'number' && ev.version <= version) return;
        version = ev.version;
        const server = Date.parse(ev.now);
        setLive({ board: ev, skew: Number.isFinite(server) ? server - Date.now() : 0, connected: true, error: null });
      });
      es.onerror = () => {
        setLive((l) => ({ ...l, connected: false }));
        if (!es || es.readyState !== EventSource.CLOSED) return; // 기본 재연결 중
        es = null;
        // 닫혔다 = 200 이 아닌 응답(401 등) — 로그인부터 확인
        api
          .me()
          .then(() => {
            timer = setTimeout(open, 3000);
          })
          .catch((err: unknown) => {
            if (err instanceof api.ApiError && err.status === 401) clearSession();
            else timer = setTimeout(open, 3000);
          });
      };
    };
    open();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [token]);

  return live;
}
