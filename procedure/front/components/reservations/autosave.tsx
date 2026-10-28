'use client';

// 예약 상세 자동 저장 한 규칙(E2E batch 3 #3 · #4 · #5) — [저장] · [수정] 버튼 없음.
// 저장 때 = 입력 멈춤 1초 · 칸을 벗어날 때 · 모달을 닫을 때(남은 것) / 고르는 칸(날짜 · 드롭다운)은 바로.
// 칸 옆 작은 상태: 저장 중 · 저장됨 · 저장 못 함 [다시] — 실패해도 쓴 글자는 그대로 둔다. 같은 값이면 부르지 않는다
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

export const IDLE_MS = 1000;

type Status = 'idle' | 'saving' | 'saved' | 'error';

// 모달이 닫힐 때 남은 저장을 모두 내보내려고 칸마다 flush 를 등록한다
type Register = (flush: () => void) => () => void;
export const AutoSaveContext = createContext<Register>(() => () => {});

export function useFlushRegistry() {
  const set = useRef(new Set<() => void>());
  const register = useCallback<Register>((f) => {
    set.current.add(f);
    return () => {
      set.current.delete(f);
    };
  }, []);
  const flushAll = useCallback(() => set.current.forEach((f) => f()), []);
  return { register, flushAll };
}

export function useAutoSave({
  value,
  save,
  onError,
  after,
}: {
  value: string; // 서버 값(상세 응답)
  save: (v: string) => Promise<unknown>;
  onError?: (e: unknown) => void;
  after?: () => void; // 저장 뒤 상세 다시 부르기
}) {
  const register = useContext(AutoSaveContext);
  const [draft, setDraft] = useState<string | null>(null); // 화면에서 고친 값(서버 값이 따라오면 버림)
  const [status, setStatus] = useState<Status>('idle');
  const [base, setBase] = useState<string | null>(null); // 저장 성공 때의 서버 값 — 서버 값이 바뀌면 draft 를 버린다(KOS 가 값을 다듬는 칸)

  const draftRef = useRef<string | null>(null);
  const valueRef = useRef(value);
  const saveRef = useRef(save);
  const onErrorRef = useRef(onError);
  const afterRef = useRef(after);
  const inflight = useRef(false);
  const again = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    valueRef.current = value;
    saveRef.current = save;
    onErrorRef.current = onError;
    afterRef.current = after;
  });

  // 서버 값이 고친 값과 같아졌거나(반영) · 저장 뒤 서버 값이 바뀌었으면 고친 값을 버린다(이전 렌더 값 저장 꼴)
  if (draft !== null && status === 'saved' && (value === draft || (base !== null && value !== base))) {
    setDraft(null);
    setBase(null);
  }

  // 저장 몸통 — 자기 자신을 다시 부르므로 ref 에 두고 바깥에는 고정 함수(flush)만 준다
  const run = useRef<() => Promise<void>>(async () => {});
  const flush = useCallback(() => run.current(), []);
  useEffect(() => {
    run.current = async () => {
      if (timer.current) {
        clearTimeout(timer.current);
        timer.current = null;
      }
      const v = draftRef.current;
      if (v === null) return;
      if (inflight.current) {
        again.current = true;
        return;
      }
      if (v === valueRef.current) {
        draftRef.current = null;
        setDraft(null);
        setStatus('idle');
        return;
      }
      inflight.current = true;
      setStatus('saving');
      try {
        await saveRef.current(v);
        if (draftRef.current === v) draftRef.current = null; // 그 사이 더 고치지 않았으면 다 보낸 것
        setBase(valueRef.current);
        setStatus('saved');
        afterRef.current?.();
      } catch (e) {
        setStatus('error'); // 쓴 글자는 draft 로 남는다
        onErrorRef.current?.(e);
      } finally {
        inflight.current = false;
        if (again.current) {
          again.current = false;
          if (draftRef.current !== null) void run.current();
        }
      }
    };
  });

  useEffect(() => register(() => void flush()), [register, flush]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  // 글자 칸 — 멈춘 뒤 1초에 저장
  const change = useCallback(
    (v: string) => {
      draftRef.current = v;
      setDraft(v);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), IDLE_MS);
    },
    [flush],
  );
  // 고르는 칸 — 바로 저장
  const pick = useCallback(
    (v: string) => {
      draftRef.current = v;
      setDraft(v);
      void flush();
    },
    [flush],
  );

  return { value: draft ?? value, change, pick, flush: () => void flush(), status, dirty: draft !== null && draft !== value };
}

// 칸 옆 작은 상태
export function SaveState({ status, onRetry }: { status: Status; onRetry: () => void }) {
  if (status === 'idle') return null;
  if (status === 'error')
    return (
      <span className="text-typo-caption-md-400 text-red" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
        저장 못 함
        <button type="button" onClick={onRetry} className="text-typo-caption-md-400 text-red" style={{ border: 'none', background: 'transparent', padding: 0, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
          다시
        </button>
      </span>
    );
  return (
    <span className={'text-typo-caption-md-400 ' + (status === 'saving' ? 'text-ms-gray-500' : 'text-primary')} style={{ whiteSpace: 'nowrap' }} aria-live="polite">
      {status === 'saving' ? '저장 중…' : '저장됨'}
    </span>
  );
}
