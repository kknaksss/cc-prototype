'use client';

import { useCallback, useRef, useState } from 'react';
import * as api from '@/lib/api';
import type { MutationResult } from '@/lib/types';

export interface Toast {
  text: string;
  version: number | null; // null = 되돌리기 없음(오류 알림)
}

// 조작 → back 응답(새 version)을 받아 토스트 「되돌리기」를 띄운다. 결과 상태는 다시 읽어서 본다
export function useDeskActions(reload: () => Promise<void>) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback((t: Toast | null) => {
    if (timer.current) clearTimeout(timer.current);
    setToast(t);
    if (t) timer.current = setTimeout(() => setToast(null), 6000);
  }, []);

  const run = useCallback(
    async (fn: () => Promise<MutationResult>, text: string | null) => {
      try {
        const r = await fn();
        show(text ? { text, version: r.version } : null);
      } catch (e) {
        show({ text: e instanceof Error ? e.message : '처리하지 못했어요', version: null });
      }
      await reload();
    },
    [reload, show],
  );

  const undo = useCallback(async () => {
    const t = toast;
    if (!t || t.version === null) return;
    show(null);
    try {
      await api.undo(t.version);
    } catch (e) {
      show({ text: e instanceof Error ? e.message : '되돌리지 못했어요', version: null });
    }
    await reload();
  }, [toast, reload, show]);

  return { toast, run, undo };
}
