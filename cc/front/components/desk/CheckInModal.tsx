'use client';

import { useEffect, useState } from 'react';
import { Button, Modal } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { checkBox, pickCls } from '@/lib/board';
import type { PatientDetail, ProcedureCandidate, Reservation, StepInput } from '@/lib/types';
import { natName } from '@/components/staff/common';
import { VisitChip } from './Aside';

interface Row {
  key: string;
  label: string;
  sub: string;
  step: StepInput;
  bundle: boolean;
}

// 접수 모달(§3.1 · §0-b 12) — 오늘 동선 단계를 데스크가 고른다. 시술 후보 = 묶음 n/m, 고르면 1회
export function CheckInModal({
  resv,
  onClose,
  onConfirm,
}: {
  resv: Reservation;
  onClose: () => void;
  onConfirm: (steps: StepInput[]) => void;
}) {
  const [p, setP] = useState<PatientDetail | null>(null);
  const [cands, setCands] = useState<ProcedureCandidate[]>([]);
  const [sel, setSel] = useState<string[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getPatient(resv.scheduleId)
      .then((x) => alive && setP(x))
      .catch(() => undefined);
    api
      .getProcedureCandidates(resv.scheduleId)
      .then((x) => alive && setCands(x))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [resv.scheduleId]);

  const rows: Row[] = [
    { key: 'consult', label: '상담', sub: '상담사', step: { kind: 'consult' }, bundle: false },
    { key: 'doctor_consult', label: '원장 상담', sub: '의사', step: { kind: 'doctor_consult' }, bundle: false },
    ...cands
      .filter((c) => c.kind === 'procedure')
      .map((c) => ({
        key: c.bundleId,
        label: c.name,
        sub: (c.source === 'ticket' ? '보유 시술권' : '오늘 결제') + ' · ' + c.left + '/' + c.total,
        step: { bundleId: c.bundleId },
        bundle: true,
      })),
  ];
  // 첫 방문 기본 = 「상담」 · 재내원 기본 = 보유 시술권 묶음마다 1회
  const isNew = p ? p.isNew : resv.isNew;
  const curSel = sel ?? (isNew ? ['consult'] : rows.filter((r) => r.bundle).map((r) => r.key));
  const picked = rows.filter((r) => curSel.includes(r.key));
  const meta = [p?.sex, p && p.age !== null ? p.age + '세' : '', natName(resv.nationality)].filter(Boolean).join(' · ');

  return (
    <Modal isOpen onBackdropClick={onClose}>
      <div
        style={{
          width: 'min(560px, calc(100vw - 64px))',
          maxHeight: 'min(780px, calc(100vh - 96px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          overflow: 'auto',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="text-typo-title-sm-600 text-ms-gray-800">접수</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-body-600 text-ms-gray-800">{resv.name}</span>
            <VisitChip isNew={isNew} />
            <span className="text-typo-body-400 text-ms-gray-600">{meta}</span>
          </div>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {resv.time} 예약{p && p.requestedProcedures.length ? ' · ' + p.requestedProcedures.join(' · ') : ''}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 동선 단계</span>
          {rows.map((r) => {
            const on = curSel.includes(r.key);
            return (
              <div
                key={r.key}
                onClick={() => setSel(on ? curSel.filter((x) => x !== r.key) : [...curSel, r.key])}
                className={pickCls(on)}
                style={{
                  borderWidth: 1,
                  borderStyle: 'solid',
                  borderRadius: 8,
                  padding: '10px 12px',
                  display: 'grid',
                  gridTemplateColumns: '18px minmax(0,1fr) auto',
                  gap: 10,
                  alignItems: 'center',
                  cursor: 'pointer',
                }}
              >
                <span
                  className={checkBox(on)}
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 4,
                    borderWidth: 1,
                    borderStyle: 'solid',
                    boxSizing: 'border-box',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  ✓
                </span>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <span className="text-typo-body-500">{r.label}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {r.sub}
                  </span>
                </div>
                <span className="text-typo-caption-md-600 text-primary" style={{ whiteSpace: 'nowrap' }}>
                  {on && r.bundle ? '1회' : ''}
                </span>
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 동선</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
            {picked.map((r, i) => (
              <span key={r.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  className="bg-ms-gray-100 text-ms-gray-800"
                  style={{ borderRadius: 999, padding: '4px 10px', display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}
                >
                  <span className="text-typo-caption-md-500">{r.label}</span>
                </span>
                <span className="text-ms-gray-500" style={{ fontSize: 12 }}>
                  {i < picked.length - 1 ? '→' : ''}
                </span>
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
          <Button variant="outlined" color="gray" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="solid"
            color="blue"
            disabled={!picked.length}
            onClick={() => {
              if (picked.length) onConfirm(picked.map((r) => r.step));
            }}
          >
            접수 · 접수대기실
          </Button>
        </div>
      </div>
    </Modal>
  );
}
