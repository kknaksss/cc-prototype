'use client';

import { useCallback } from 'react';
import { Button, Modal } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { useLive, useWide } from '@/lib/hooks';
import { Bundles, MemoList, historyBlocks, todayBlocks } from '@/lib/memo';
import type { Board, PatientDetail, Reservation } from '@/lib/types';
import { natName } from '@/components/staff/common';
import { VisitChip } from './Aside';

// 예약 상세(§0-b 9) — 예약 정보 · 예약 메모 · 고객 메모 · 지난 방문 카드 · 보유 시술권 · [노쇼] · [접수]. 오늘 상담 · 오더 칸 없음
export function ResvDetail({
  board,
  resv,
  onClose,
  onCheckIn,
  onNoShow,
}: {
  board: Board;
  resv: Reservation;
  onClose: () => void;
  onCheckIn: () => void;
  onNoShow: () => void;
}) {
  const load = useCallback(() => api.getPatient(resv.scheduleId), [resv.scheduleId]);
  const p = useLive<PatientDetail>(load).data;
  const cust = board.customers.find((c) => c.scheduleId === resv.scheduleId);
  const booked = resv.st === 'booked';
  const stateText = resv.st === 'noshow' ? '노쇼' : cust?.flowStep === 'COMPLETED' ? '귀가' : '내원 중';
  const info = p
    ? (
        [
          ['예약', p.reservationTime],
          ['예약 시술', p.requestedProcedures.join(' · ')],
          ['국적', natName(p.nationality)],
          ['성별 · 나이', [p.sex, p.age !== null ? p.age + '세' : ''].filter(Boolean).join(' · ')],
          ['유입', p.chart.find((r) => r.label === '유입' || r.label === '유입처')?.value ?? ''],
        ] as [string, string][]
      ).filter(([, v]) => v)
    : [];
  // 폰(< 760px) 폭 맞춤 — 예약 · 히스토리 두 열을 위아래로(SPEC-002 §2)
  const phone = !useWide();
  const memo = p ? todayBlocks({ ...p, visits: [] }, { resvTitle: '예약 메모' }) : [];

  return (
    <Modal isOpen onBackdropClick={onClose}>
      <div
        style={{
          width: 'min(900px, calc(100vw - 64px))',
          maxHeight: 'min(820px, calc(100vh - 96px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          overflow: 'auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-title-sm-600 text-ms-gray-800">{resv.name}</span>
            <VisitChip isNew={resv.isNew} />
            {!booked && (
              <span className="bg-ms-gray-200 text-ms-gray-700 text-typo-caption-md-600" style={{ padding: '1px 6px', borderRadius: 4 }}>
                {stateText}
              </span>
            )}
          </div>
          <Button variant="text" color="gray" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>
        <div
          className="bg-ms-gray-100"
          style={{ borderRadius: 10, padding: '10px 14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '8px 16px' }}
        >
          {info.map(([k, v]) => (
            <span key={k} style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
              <span className="text-typo-caption-md-400 text-ms-gray-600">{k}</span>
              <span className="text-typo-body-500 text-ms-gray-800" style={{ overflowWrap: 'anywhere' }}>
                {v}
              </span>
            </span>
          ))}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: phone ? 'minmax(0,1fr)' : 'minmax(0,1fr) minmax(0,1fr)', gap: 16, alignItems: 'start' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">예약</span>
            <MemoList blocks={memo} />
            {p && !memo.length && <span className="text-typo-body-400 text-ms-gray-500">예약 메모 없음</span>}
          </div>
          <div className="bg-ms-gray-100" style={{ borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">히스토리</span>
            {p && <MemoList blocks={historyBlocks(p)} />}
            {p && <Bundles tickets={p.tickets} />}
          </div>
        </div>
        {booked && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button variant="outlined" color="red" onClick={onNoShow}>
              노쇼
            </Button>
            <Button variant="solid" color="blue" onClick={onCheckIn}>
              접수
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
