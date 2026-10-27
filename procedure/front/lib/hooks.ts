'use client';

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import * as api from './api';
import { clearSession, parseSession, readSessionRaw, type Session } from './session';
import type { Board, BoardEvent, ResvBoard } from './types';

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

// ─── 예약 현황 스케줄 표(SPEC-005 §6.7) — 열려 있는 동안 10초마다 GET board?date= · SSE 안 씀
// date = null 이면 오늘(back 이 KST 로 정함) — 첫 응답의 date 로 화면 날짜가 정해진다
// refresh() = 조작 성공 직후 1번 + 2초 뒤 1번(반영 지연 · §4.3) — 부른 쪽이 refreshSoon() 을 쓴다
const RESV_POLL_MS = 10_000;
const RESV_SETTLE_MS = 2_000;

export interface ResvLive {
  board: ResvBoard | null;
  prev: ResvBoard | null; // 날짜를 바꾼 뒤 새 응답 전까지 — 앞 날짜 표(흐리게 보인다 · E2E b2 #1)
  skew: number; // 서버 now - 브라우저 시각(ms)
  loading: boolean;
  error: string | null; // 마지막 GET 실패 문구(사본은 그대로 보인다)
  refresh: () => void;
  refreshSoon: () => void;
}

export function useResvBoard(token: string | null, date: string | null): ResvLive {
  const [state, setState] = useState<{ board: ResvBoard | null; skew: number; error: string | null; forDate: string | null | undefined }>({
    board: null,
    skew: 0,
    error: api.CONFIG_ERROR,
    forDate: undefined,
  });
  // 요청 번호 — 날짜가 바뀐 뒤 늦게 온 앞 날짜 응답은 버린다
  const seq = useRef(0);

  const load = useCallback(
    (d: string | null) => {
      if (!token || api.CONFIG_ERROR) return;
      const n = ++seq.current;
      api
        .reservationBoard(d ?? undefined)
        .then((b) => {
          if (n !== seq.current) return;
          const server = Date.parse(b.now);
          setState({ board: b, skew: Number.isFinite(server) ? server - Date.now() : 0, error: null, forDate: d });
        })
        .catch((e: unknown) => {
          if (n !== seq.current) return;
          if (e instanceof api.ApiError && e.status === 401) {
            clearSession();
            return;
          }
          setState((s) => ({ ...s, forDate: d, error: e instanceof Error ? e.message : '불러오지 못했어요' }));
        });
    },
    [token],
  );

  // 날짜가 바뀌면 바로 부르고 그 뒤 10초마다
  useEffect(() => {
    if (!token || api.CONFIG_ERROR) return;
    load(date);
    const t = setInterval(() => load(date), RESV_POLL_MS);
    return () => clearInterval(t);
  }, [token, date, load]);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const refresh = useCallback(() => load(date), [load, date]);
  const refreshSoon = useCallback(() => {
    load(date);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => load(date), RESV_SETTLE_MS);
  }, [load, date]);

  // 그 날짜 응답만 보인다(다른 날짜 사본은 숨김) — 받기 전 = 불러오는 중
  const b = state.board;
  const board = b && (date === null ? state.forDate === null || b.isToday : b.date === date) ? b : null;
  const settled = state.forDate === date;
  return { board, prev: board ? null : b, skew: state.skew, loading: !board && !(settled && state.error), error: settled ? state.error : api.CONFIG_ERROR, refresh, refreshSoon };
}
