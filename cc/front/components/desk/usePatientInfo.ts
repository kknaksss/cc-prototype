'use client';

import { useEffect, useState } from 'react';
import { getPatient } from '@/lib/api';
import type { PatientDetail } from '@/lib/types';

// 방 패널 · 접수 모달의 고객 한 줄 정보(나이 · 주의 · 시술권) — 환자 상세(§5.5)에서 가져온다
export interface PatientInfo {
  meta: string;
  cautions: string[];
  tickets: NonNullable<PatientDetail['tickets']>;
}

export const patientMeta = (p: PatientDetail) =>
  [p.sex, p.age !== null ? p.age + '세' : '', p.firstVisit ? '첫 방문' : '재방문'].filter(Boolean).join(' · ');

const cache = new Map<string, PatientInfo>();

export function usePatientInfo(ids: string[]): Record<string, PatientInfo> {
  const [, setTick] = useState(0);
  const key = ids.join(',');
  useEffect(() => {
    let alive = true;
    key
      .split(',')
      .filter((id) => id && !cache.has(id))
      .forEach((id) => {
        getPatient(id)
          .then((p) => {
            cache.set(id, {
              meta: patientMeta(p),
              cautions: p.cautions.map((c) => c.text),
              tickets: p.tickets ?? [],
            });
            if (alive) setTick((t) => t + 1);
          })
          .catch(() => {
            // 상세가 없으면(현장 접수 등) 줄 정보 없이 보인다
          });
      });
    return () => {
      alive = false;
    };
  }, [key]);
  const out: Record<string, PatientInfo> = {};
  ids.forEach((id) => {
    const v = cache.get(id);
    if (v) out[id] = v;
  });
  return out;
}

// 초기화 · 되돌리기 뒤 시술권 잔여가 바뀔 수 있어 비운다
export const clearPatientInfo = () => cache.clear();
