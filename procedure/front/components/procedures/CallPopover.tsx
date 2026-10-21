'use client';

// 의사 호출 팝오버(SPEC-003 §6.5 · 시안 call-modal) — 카드 아래 [의사 호출] 기준 아래로(모자라면 위로) · 바깥 누르면 닫힘 · [취소] 없음
import { useState } from 'react';
import { Button } from '@medisolve-ai/medikit';
import type { Board, Card, CallTarget } from '@/lib/types';

export interface CallDraft {
  visitId: number;
  procedureIds: number[];
  top: number;
  left: number;
}

// 버튼 위치에서 팝오버 자리 — 560 × 440, 화면 밑이 모자라면 버튼 위로
export function placePopover(rect: DOMRect | null): { top: number; left: number } {
  if (!rect) return { top: 120, left: 120 };
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const w = Math.min(560, vw - 24);
  const h = Math.min(440, vh - 80);
  const top = rect.bottom + 6 + h > vh - 12 ? Math.max(12, rect.top - 6 - h) : rect.bottom + 6;
  const left = Math.min(Math.max(12, rect.left), vw - w - 12);
  return { top, left };
}

type Pick = { kind: 'all' } | { kind: 'one'; doctorId: number } | null;

export function CallPopover({
  board,
  card,
  draft,
  onClose,
  onSubmit,
}: {
  board: Board;
  card: Card;
  draft: CallDraft;
  onClose: () => void;
  onSubmit: (target: CallTarget, label: string) => void;
}) {
  const [q, setQ] = useState('');
  const [pick, setPick] = useState<Pick>(null);

  // 추천 = 모든 의사 + 원장 목록(비어 있는 원장 먼저). 하나만 고름 · 다시 누르면 해제
  const docs = board.doctors.slice().sort((a, b) => Number(a.busy) - Number(b.busy));
  const rows = [
    {
      key: 'all',
      name: '모든 의사',
      av: 'ALL',
      avCls: 'bg-ms-gray-700 text-ms-white',
      sub: '콜 잡은 원장이 집도',
      subCls: 'text-typo-caption-md-400 text-ms-gray-500',
      on: pick?.kind === 'all',
      toggle: () => setPick(pick?.kind === 'all' ? null : { kind: 'all' }),
    },
    ...docs.map((d) => {
      const on = pick?.kind === 'one' && pick.doctorId === d.id;
      return {
        key: 'd' + d.id,
        name: d.name,
        av: d.name.slice(0, 1),
        avCls: 'bg-purple-100 text-purple',
        sub: d.busy ? '시술 중' : '대기',
        subCls: d.busy ? 'text-typo-caption-md-400 text-ms-gray-500' : 'text-typo-caption-md-500 text-primary',
        on,
        toggle: () => setPick(on ? null : { kind: 'one', doctorId: d.id }),
      };
    }),
  ];
  const text = q.replace(/\s+/g, '');
  const recs = rows.filter((r) => !text || r.name.replace(/\s+/g, '').includes(text));
  const picked = rows.filter((r) => r.on);
  const procs = card.procedures.slice().sort((a, b) => a.sequence - b.sequence).filter((p) => draft.procedureIds.includes(p.id));
  const doctorName = pick?.kind === 'one' ? (board.doctors.find((d) => d.id === pick.doctorId)?.name ?? '') : '';
  const cta = !pick ? '의사를 선택하세요' : pick.kind === 'one' ? doctorName + ' 호출' : '모든 의사 호출';
  const off = !pick || !procs.length;

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 50 }} />
      <div
        className="bg-ms-white border-ms-gray-200"
        style={{
          position: 'fixed',
          top: draft.top,
          left: draft.left,
          zIndex: 51,
          width: 'min(560px, calc(100vw - 24px))',
          height: 'min(440px, calc(100vh - 80px))',
          borderWidth: 1,
          borderStyle: 'solid',
          borderRadius: 10,
          boxShadow: '0 8px 28px rgba(0,0,0,0.14)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <div
          className="border-ms-gray-200"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '12px 12px 12px 16px',
            borderBottomWidth: 1,
            borderBottomStyle: 'solid',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
            <span className="text-typo-heading-md-500 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
              의사 호출
            </span>
            <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {card.room.title} · {card.customer.name}
            </span>
          </div>
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="cc-btn text-ms-gray-700 hover:bg-ms-gray-100"
            style={{ width: 32, height: 32, fontSize: 20, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6 }}
          >
            ✕
          </button>
        </div>
        <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)' }}>
          <div className="border-ms-gray-200" style={{ display: 'flex', flexDirection: 'column', minHeight: 0, borderRightWidth: 1, borderRightStyle: 'solid' }}>
            <div style={{ padding: '12px 12px 8px' }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="검색" className="cc-input" style={{ height: 40 }} />
            </div>
            <span className="text-typo-caption-md-500 text-ms-gray-500" style={{ padding: '4px 16px 4px' }}>
              추천
            </span>
            <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', padding: '0 4px 8px' }}>
              {recs.map((r) => (
                <div
                  key={r.key}
                  onClick={r.toggle}
                  className={r.on ? 'bg-primary-100' : 'bg-ms-white hover:bg-ms-gray-100'}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', minHeight: 44, boxSizing: 'border-box', borderRadius: 8, cursor: 'pointer' }}
                >
                  <Avatar cls={r.avCls} text={r.av} />
                  <span className="text-typo-body-500 text-ms-gray-800" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.name}
                  </span>
                  <span className={r.subCls} style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
                    {r.sub}
                  </span>
                </div>
              ))}
              {!recs.length && (
                <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '8px 12px' }}>
                  검색 결과가 없어요
                </span>
              )}
            </div>
          </div>
          <div className="bg-ms-gray-100" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <span className="text-typo-caption-md-500 text-ms-gray-600" style={{ padding: '16px 16px 8px' }}>
              선택됨
            </span>
            <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6, padding: '0 12px' }}>
              {picked.map((r) => (
                <div key={r.key} className="bg-ms-white" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 8px 8px 12px', borderRadius: 8 }}>
                  <Avatar cls={r.avCls} text={r.av} />
                  <span className="text-typo-body-500 text-ms-gray-800" style={{ minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.name}
                  </span>
                  <button
                    type="button"
                    aria-label="선택 해제"
                    onClick={r.toggle}
                    className="cc-btn text-ms-gray-500"
                    style={{ width: 28, height: 28, fontSize: 14, borderRadius: 6, textAlign: 'center' }}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <span className="text-typo-caption-md-500 text-ms-gray-600" style={{ padding: '10px 4px 2px' }}>
                호출할 시술 · {procs.length}개
              </span>
              {procs.map((p) => (
                <span key={p.id} className="text-typo-caption-md-500 text-ms-gray-800" style={{ padding: '2px 4px', wordBreak: 'keep-all' }}>
                  · {p.title}
                </span>
              ))}
            </div>
            <div data-fill-buttons="true" style={{ display: 'grid', padding: 12 }}>
              <Button
                variant="solid"
                color="blue"
                disabled={off}
                onClick={() => {
                  if (off || !pick) return;
                  onSubmit(pick, pick.kind === 'one' ? doctorName + ' 호출' : '전체 호출');
                }}
              >
                {cta}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function Avatar({ cls, text }: { cls: string; text: string }) {
  return (
    <span
      className={cls}
      style={{ width: 28, height: 28, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}
    >
      {text}
    </span>
  );
}
