'use client';

import { useEffect, useState } from 'react';
import { Button, Modal } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { checkBox, pickCls } from '@/lib/board';
import { Bold } from '@/lib/memo';
import type { PatientDetail, ProcedureCandidate, Reservation, StepInput } from '@/lib/types';
import { natName } from '@/components/staff/common';

interface Row {
  key: string;
  label: string;
  sub: string;
  step: StepInput;
  ticket: boolean;
}

const candSub = (c: ProcedureCandidate) =>
  (c.source === 'ticket' ? '보유 시술권' : '오늘 결제 시술권') + (c.kosSequence ? ' · 순번 ' + c.kosSequence : '');

// 접수 모달(§3.1) — 오늘 동선 단계를 데스크가 고른다. 자동으로 끼우는 단계 없음
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

  const dc = cands.find((c) => c.kind === 'doctor_consult');
  const rows: Row[] = [
    { key: 'consult', label: '상담', sub: '상담사', step: { kind: 'consult', label: '상담' }, ticket: false },
    {
      key: 'doctor_consult',
      label: '원장 상담',
      sub: '의사',
      step: { kind: 'doctor_consult', label: '원장 상담', kosSequence: dc?.kosSequence ?? null },
      ticket: false,
    },
    ...cands
      .filter((c) => c.kind === 'procedure')
      .map((c, i) => ({
        key: 'c' + i,
        label: c.label,
        sub: candSub(c),
        step: { kind: c.kind, label: c.label, ticketId: c.ticketId, kosSequence: c.kosSequence },
        ticket: c.source === 'ticket',
      })),
  ];
  // 첫 방문 기본 = 「상담」 · 재내원 기본 = 보유 시술권 전부
  const isNew = p ? p.isNew : resv.isNew;
  const curSel = sel ?? (isNew ? ['consult'] : rows.filter((r) => r.ticket).map((r) => r.key));
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
            {isNew ? (
              <span className="bg-primary-100 text-primary text-typo-caption-md-600" style={{ padding: '1px 6px', borderRadius: 4 }}>
                첫 방문
              </span>
            ) : (
              <span className="bg-ms-gray-200 text-ms-gray-700 text-typo-caption-md-600" style={{ padding: '1px 6px', borderRadius: 4 }}>
                재내원
              </span>
            )}
            <span className="text-typo-body-400 text-ms-gray-600">{meta}</span>
          </div>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {resv.time} 예약 · 시술 {resv.procedure || '-'} · 원장 {resv.doctor || '-'}
          </span>
        </div>
        {p && p.cautions.length > 0 && (
          <div className="bg-red-100" style={{ borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span className="text-typo-caption-md-600 text-red">⚠ 주의</span>
            {p.cautions.map((cu, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span className="text-typo-body-400 text-ms-gray-800" style={{ overflowWrap: 'anywhere' }}>
                  <Bold text={cu.text} />
                </span>
                <span className="text-typo-caption-md-400 text-ms-gray-600">{cu.source}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 동선 단계 고르기</span>
            <span className="text-typo-caption-md-400 text-ms-gray-600">
              {isNew ? '첫 방문 — 기본은 「상담」' : '재내원 — 기본은 보유 시술권'}
            </span>
          </div>
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
                  gridTemplateColumns: '18px minmax(0,1fr)',
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
                  <span className="text-typo-caption-md-400 text-ms-gray-600">{r.sub}</span>
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 동선 (고른 순서)</span>
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
          {!picked.length && <span className="text-typo-caption-md-400 text-red">단계를 하나 이상 고르세요</span>}
          <span className="text-typo-caption-md-400 text-ms-gray-500">
            시술은 방 패널의 [시술 추가]로 나중에 붙일 수 있어요. 직원은 방을 눌러 단계마다 배정해요.
          </span>
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
