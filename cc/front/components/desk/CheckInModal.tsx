'use client';

import { useState } from 'react';
import { Button, Modal } from '@medisolve-ai/medikit';
import { RLABEL, buildOrder } from '@/lib/board';
import type { Ticket } from '@/lib/types';
import type { PatientInfo } from './usePatientInfo';

export interface CheckInTarget {
  scheduleId: string | null; // 현장 접수면 null
  name: string;
  time: string;
  procedure: string;
  doctor: string;
}

const box = (on: boolean) =>
  on ? 'bg-primary border-primary text-ms-white' : 'bg-ms-white border-ms-gray-400 text-ms-white';
const checkBox = {
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
} as const;
const rowStyle = {
  borderWidth: 1,
  borderStyle: 'solid',
  borderRadius: 8,
  padding: '10px 12px',
  display: 'grid',
  gridTemplateColumns: '18px minmax(0,1fr)',
  gap: 10,
  alignItems: 'center',
} as const;

// 접수 모달 — 시안 ciVals. 고른 오더를 check-in 으로 보낸다(결과 상태는 back)
export function CheckInModal({
  target,
  info,
  onClose,
  onConfirm,
}: {
  target: CheckInTarget;
  info: PatientInfo | undefined;
  onClose: () => void;
  onConfirm: (order: ReturnType<typeof buildOrder>) => void;
}) {
  const tickets: Ticket[] = info?.tickets ?? [];
  const has = tickets.length > 0;
  // 시안: 시술권이 있으면 첫 시술권을 미리 고르고, 없으면 상담 필요를 켠다
  const [sel, setSel] = useState<number[] | null>(null);
  const [consult, setConsult] = useState<boolean | null>(null);
  const firstOk = tickets.findIndex((t) => t.left > 0);
  const curSel = sel ?? (has && firstOk >= 0 ? [firstOk] : []);
  const curConsult = consult ?? !has;
  const order = buildOrder(tickets, curSel, curConsult);
  const walk = target.scheduleId === null;
  const cautions = info?.cautions ?? [];

  return (
    <Modal isOpen onBackdropClick={onClose}>
      <div
        style={{
          width: 'min(560px, calc(100vw - 64px))',
          maxHeight: 'min(760px, calc(100vh - 96px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
          overflow: 'auto',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="text-typo-title-sm-600 text-ms-gray-800">접수</span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-body-600 text-ms-gray-800">{target.name}</span>
            <span className="text-typo-body-400 text-ms-gray-600">{info?.meta || (walk ? '현장 접수 · 신규' : '')}</span>
          </div>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {walk ? '예약 없음' : target.time + ' 예약 · ' + target.procedure + ' · 담당 ' + target.doctor}
          </span>
        </div>
        {cautions.length > 0 && (
          <div className="bg-red-100" style={{ borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="text-typo-caption-md-600 text-red">주의사항</span>
            <span className="text-typo-body-500 text-ms-gray-800">{cautions.join(' · ')}</span>
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">보유 시술권 · 오늘 받을 시술 선택</span>
          {tickets.map((t, i) => {
            const on = curSel.includes(i);
            const out = t.left <= 0;
            return (
              <div
                key={i}
                onClick={out ? undefined : () => setSel(on ? curSel.filter((x) => x !== i) : [...curSel, i])}
                className={
                  out
                    ? 'bg-ms-gray-100 border-ms-gray-200 text-ms-gray-500'
                    : on
                      ? 'bg-primary-100 border-primary text-ms-gray-800'
                      : 'bg-ms-white border-ms-gray-300 text-ms-gray-800'
                }
                style={{ ...rowStyle, cursor: out ? 'not-allowed' : 'pointer' }}
              >
                <span className={out ? 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-100' : box(on)} style={checkBox}>
                  ✓
                </span>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <span className="text-typo-body-500">{t.name}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {out ? '소진 · 0/' + t.total + '회' : '잔여 ' + t.left + '/' + t.total + '회' + (t.expires ? ' · ~' + t.expires : '')}
                  </span>
                </div>
              </div>
            );
          })}
          {!has && <span className="text-typo-body-400 text-ms-gray-500">보유 시술권이 없어요</span>}
          <div
            onClick={() => setConsult(!curConsult)}
            className={
              curConsult ? 'bg-primary-100 border-primary text-ms-gray-800' : 'bg-ms-white border-ms-gray-300 text-ms-gray-800'
            }
            style={{ ...rowStyle, cursor: 'pointer' }}
          >
            <span className={box(curConsult)} style={checkBox}>
              ✓
            </span>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <span className="text-typo-body-500">상담 필요</span>
              <span className="text-typo-caption-md-400 text-ms-gray-600">신규 · 시술권 외 시술 · 추가 상담</span>
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 진행 순서</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
            {order.map((s, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  className="bg-ms-gray-100 text-ms-gray-800"
                  style={{ borderRadius: 999, padding: '4px 10px', display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}
                >
                  <span className="text-typo-caption-md-500">{s.label}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">{RLABEL[s.role]}</span>
                </span>
                <span className="text-ms-gray-500" style={{ fontSize: 12 }}>
                  {i < order.length - 1 ? '→' : ''}
                </span>
              </span>
            ))}
          </div>
          {!order.length && (
            <span className="text-typo-caption-md-400 text-red">시술을 고르거나 상담 필요를 체크하세요</span>
          )}
          <span className="text-typo-caption-md-400 text-ms-gray-500">
            원장 진료 · 진정 관리는 시술 선택 시 자동으로 들어가요. 직원은 현황판에서 방을 눌러 배정해요.
          </span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
          <Button variant="outlined" color="gray" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="solid"
            color="blue"
            disabled={!order.length}
            onClick={() => {
              if (order.length) onConfirm(order);
            }}
          >
            접수 · 라운지 대기
          </Button>
        </div>
      </div>
    </Modal>
  );
}
