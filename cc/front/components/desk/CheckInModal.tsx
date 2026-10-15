'use client';

import { useEffect, useState } from 'react';
import { Button, Modal } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { checkBox, pickCls } from '@/lib/board';
import { MemoCard } from '@/lib/memo';
import type { MemoCategory, MemoInput, PatientDetail, Reservation, StepInput } from '@/lib/types';
import { READING_CLS, natName, readingOf } from '@/components/staff/common';
import { VipChip, VisitChip } from './Aside';
import { PickOpt } from './RoomPanel';

interface Row {
  key: string;
  label: string;
  sub: string;
  step: StepInput;
  bundle: boolean;
}

const MEMO_CATS: { id: MemoCategory; name: string }[] = [
  { id: 'reservation', name: '예약 메모' },
  { id: 'consultation', name: '상담 메모' },
];

// 접수 모달(§3.1 · SPEC-002 §5.2 D-31 · D-32 · D-33) — ① 고객 ② 지난 방문(재내원) ③ 오늘 동선 선택지(자동 체크 없음)
// ④ 추가 요청 메모(선택) ⑤ [취소] [접수]. 접수 → 접수대기실은 1차 그대로
export function CheckInModal({
  resv,
  onClose,
  onConfirm,
}: {
  resv: Reservation;
  onClose: () => void;
  onConfirm: (steps: StepInput[], memo?: MemoInput) => void;
}) {
  const [p, setP] = useState<PatientDetail | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [cat, setCat] = useState<MemoCategory>('reservation');
  const [memo, setMemo] = useState('');
  // 추가 요청 목록 — 스크롤 본문 · 고정 버튼 줄에 잘리지 않게 본문 밖(fixed)으로 띄운다(SPEC-002 §5.4). 본문을 스크롤하면 닫힌다
  const [catAt, setCatAt] = useState<{ left: number; top: number; width: number } | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getPatient(resv.scheduleId)
      .then((x) => alive && setP(x))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [resv.scheduleId]);

  // 시술권은 접수 모달에서 직접 고른다(D-31 · SPEC-002 §4) — 보유 시술권 묶음, 고르면 1회
  const rows: Row[] = [
    { key: 'consult', label: '상담', sub: '상담사', step: { kind: 'consult' }, bundle: false },
    { key: 'doctor_consult', label: '원장 상담', sub: '의사', step: { kind: 'doctor_consult' }, bundle: false },
    ...(p?.tickets ?? [])
      .filter((t) => t.left > 0)
      .map((t) => ({
        key: t.bundleId,
        label: t.name,
        sub: '보유 시술권 ' + t.left + '/' + t.total,
        step: { bundleId: t.bundleId },
        bundle: true,
      })),
  ];
  const isNew = p ? p.isNew : resv.isNew;
  const picked = rows.filter((r) => sel.includes(r.key));
  const reading = readingOf(resv.nationality, p?.phoneticName ?? resv.phoneticName);
  const meta = [p?.sex, p && p.age !== null ? p.age + '세' : '', natName(resv.nationality), resv.time + ' 예약']
    .filter(Boolean)
    .join(' · ');
  const past = p ? p.visits.filter((v) => !v.today) : [];

  return (
    <Modal isOpen onBackdropClick={onClose}>
      <div
        style={{
          width: 'min(560px, calc(100vw - 64px))',
          maxHeight: 'min(780px, calc(100vh - 96px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        {/* 본문만 스크롤 — [취소] [접수] 줄은 아래 고정(SPEC-002 §5.3) */}
        <div
          onScroll={() => catAt && setCatAt(null)}
          style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="text-typo-title-sm-600 text-ms-gray-800">접수</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="text-typo-body-600 text-ms-gray-800">{resv.name}</span>
              {reading && <span className={READING_CLS}>{reading}</span>}
              <VisitChip isNew={isNew} />
              {(p?.vip ?? resv.vip) && <VipChip />}
            </div>
            <span className="text-typo-body-400 text-ms-gray-600">{meta}</span>
          </div>
          {/* 예약 메모 · 고객 메모 — 원문 그대로(1차 MemoCard, SPEC-002 §5.3) */}
          {p && (p.reservationMemo || p.customerMemo) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {p.reservationMemo && <MemoCard title="예약 메모" sub="" text={p.reservationMemo} />}
              {p.customerMemo && <MemoCard title="고객 메모" sub="" text={p.customerMemo} />}
            </div>
          )}
          {!isNew && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span className="text-typo-caption-md-600 text-ms-gray-700">지난 방문</span>
              <div className="bg-ms-gray-100" style={{ borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {past.map((v) => (
                  <div key={v.date} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <span className="text-typo-body-500 text-ms-gray-800">
                      {[v.date.slice(5), ...v.procedures].join(' · ')}
                      {v.counselors.length ? ' (상담사 ' + v.counselors.join(' · ') + ')' : ''}
                    </span>
                    {/* 상담 원문 — 요약하지 않는다(접기/펼치기, SPEC-001 #25) */}
                    {v.consultation && <MemoCard title="상담" sub="" text={v.consultation} />}
                  </div>
                ))}
                {p && !past.length && <span className="text-typo-body-400 text-ms-gray-500">지난 방문 기록 없음</span>}
              </div>
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 동선</span>
            {rows.map((r) => {
              const on = sel.includes(r.key);
              return (
                <div
                  key={r.key}
                  onClick={() => setSel(on ? sel.filter((x) => x !== r.key) : [...sel, r.key])}
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
                  <span className="text-typo-body-500">{r.label}</span>
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, textAlign: 'right' }}>
                    <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {r.sub}
                    </span>
                    {/* 차감은 시술 완료 때(D-32) — 접수는 예정 표시만 */}
                    {on && r.bundle && <span className="text-typo-caption-md-500 text-primary">오늘 사용 예정 · 시술 완료 때 차감</span>}
                  </span>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">추가 요청</span>
            {/* 셀렉터 — 1차 담당 고르기와 같은 버튼 + 목록(PickOpt) 모양(SPEC-002 §5.3) */}
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={(e) => {
                  const b = e.currentTarget.getBoundingClientRect();
                  setCatAt(catAt ? null : { left: b.left, top: b.bottom + 4, width: b.width });
                }}
                className="border-primary text-ms-gray-800"
                style={{
                  height: 40,
                  width: '100%',
                  boxSizing: 'border-box',
                  borderRadius: 6,
                  borderWidth: 1,
                  borderStyle: 'solid',
                  padding: '0 12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  background: '#fff',
                  cursor: 'pointer',
                  font: 'inherit',
                }}
              >
                <span className="text-typo-body-500">{MEMO_CATS.find((x) => x.id === cat)?.name}</span>
                <span className="text-ms-gray-600" style={{ marginLeft: 'auto', fontSize: 10 }}>
                  ▾
                </span>
              </button>
              {catAt && (
                <div
                  className="bg-ms-white border-ms-gray-300"
                  style={{
                    position: 'fixed',
                    left: catAt.left,
                    top: catAt.top,
                    width: catAt.width,
                    zIndex: 60,
                    borderRadius: 10,
                    borderWidth: 1,
                    borderStyle: 'solid',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.14)',
                    padding: '4px 0',
                  }}
                >
                  {MEMO_CATS.map((x) => (
                    <PickOpt
                      key={x.id}
                      name={x.name}
                      on={cat === x.id}
                      onPick={() => {
                        setCat(x.id);
                        setCatAt(null);
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
            <span className="text-typo-caption-md-600 text-ms-gray-700">메모</span>
            {/* kos api 연동 필요 — 예약 메모 changeReservationMemo · 상담 메모 updateScheduleConsultationInfo(back 주석) */}
            <textarea
              className="cc-text"
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              placeholder="예: 눈밑 필러 가능한지 원장님께 여쭤봐 달라고 하심"
            />
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, flexShrink: 0 }}>
          <Button variant="outlined" color="gray" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="solid"
            color="blue"
            disabled={!picked.length}
            onClick={() => {
              if (picked.length) onConfirm(picked.map((r) => r.step), memo.trim() ? { category: cat, text: memo.trim() } : undefined);
            }}
          >
            접수
          </Button>
        </div>
      </div>
    </Modal>
  );
}
