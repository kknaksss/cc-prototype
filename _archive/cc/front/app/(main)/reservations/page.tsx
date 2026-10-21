'use client';

import { useMemo, useRef, useState } from 'react';
import { Button } from '@medisolve-ai/medikit';
import { HEADER_H } from '@/components/common/AppHeader';
import { VisitChip } from '@/components/desk/Aside';
import { ChangeModal, PreviewModal, Segs, ShotModal } from '@/components/reservations/ResvModals';
import { type Chain, DONE, OPEN, ST, chainsOf, dtSegs, kindLabel, modTarget, notes, stamp } from '@/components/reservations/resv';
import * as api from '@/lib/api';
import { useLive, useNow, useSession, useWide } from '@/lib/hooks';
import type { MutationResult, ResvList, ResvRequest } from '@/lib/types';

type ModalState = { type: 'preview' | 'shot' | 'change'; id: number } | null;
const COLS = 'minmax(0,1.25fr) 200px minmax(0,1fr)';
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// 예약관리 — 시안 「Ceramique 예약관리 v1」(SPEC-002 §3). 데모: 링키 요청은 데모 버튼이 대신 만든다(D-10 · D-15)
export default function ReservationsPage() {
  const session = useSession();
  const wide = useWide();
  const now = useNow(60000);
  const live = useLive<ResvList>(session ? api.getReservations : null);
  const [modal, setModal] = useState<ModalState>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);
  const toastT = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 데모 버튼으로 새로 붙은 줄 — 이 id 보다 큰 줄에 1.6초 강조(rv-new)
  const [freshGt, setFreshGt] = useState<number | null>(null);

  const data = live.data;
  const chains = useMemo(() => chainsOf(data?.rows ?? []), [data]);

  if (!session) return null;

  const flash = (text: string, ok = true) => {
    if (toastT.current) clearTimeout(toastT.current);
    setToast({ text, ok });
    toastT.current = setTimeout(() => setToast(null), 2600);
  };
  // 조작 하나 — 중복 클릭 막기 · 오류는 토스트 · 결과는 다시 읽어서 본다
  const act = async (fn: () => Promise<unknown>, ok: string): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    let done = true;
    try {
      await fn();
      flash(ok);
    } catch (e) {
      done = false;
      flash(e instanceof Error ? e.message : '처리하지 못했어요', false);
    }
    await live.reload();
    setBusy(false);
    return done;
  };
  const maxId = () => Math.max(0, ...(data?.rows ?? []).map((r) => r.id));
  const demo = (fn: () => Promise<MutationResult>, ok: string) => {
    const gt = maxId();
    void act(fn, ok).then((d) => d && setFreshGt(gt));
  };

  const target = modTarget(chains);
  const find = (id: number): { c: Chain; r: ResvRequest } | null => {
    for (const c of chains) {
      const r = c.rows.find((x) => x.id === id);
      if (r) return { c, r };
    }
    return null;
  };
  const cur = modal ? find(modal.id) : null;
  const counts = data?.counts;
  const summary = [
    { name: '확인 필요', n: counts?.needCheck ?? 0, dot: '#fd9400' },
    { name: '변경 요청', n: counts?.changeRequested ?? 0, dot: '#e5484d' },
    { name: '확정', n: counts?.confirmed ?? 0, dot: '#15803d' },
    { name: '전체 예약', n: counts?.total ?? 0, dot: '#9f9f9f' },
  ];

  return (
    <div style={{ minHeight: `calc(100vh - ${HEADER_H}px)`, display: 'flex', flexDirection: 'column', background: 'var(--ms-gray-100, #f5f6f8)' }}>
      <main
        style={{
          flex: 1,
          width: '100%',
          maxWidth: 1280,
          margin: '0 auto',
          boxSizing: 'border-box',
          padding: wide ? '24px 28px 48px' : '16px 16px 40px',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <span className="text-typo-title-md-600 text-ms-gray-800">예약관리</span>
          {/* 데모 전용(D-10 · D-15) — 링키 연동이 붙으면 이 상자는 없어진다 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 12px',
              borderRadius: 12,
              border: '1px dashed #fd9400',
              background: '#fffaf2',
              flexWrap: 'wrap',
            }}
          >
            <span className="text-typo-caption-md-600" style={{ color: '#b35c00', paddingRight: 4 }}>
              데모 전용
            </span>
            <button type="button" className="rv-demo-btn" disabled={busy} onClick={() => demo(api.demoResvRequest, '링키에서 예약 요청이 왔어요')}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M12 5v14M5 12h14" />
              </svg>
              링키 예약 요청 생성
            </button>
            <button
              type="button"
              className="rv-demo-btn"
              disabled={!target || busy}
              onClick={() => target && demo(api.demoResvModify, '링키에서 수정 요청이 왔어요')}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 20h4L19 9l-4-4L4 16v4z" />
              </svg>
              링키 수정 요청 생성
            </button>
          </div>
        </div>

        {/* 요약 */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {summary.map((s) => (
            <div
              key={s.name}
              className="bg-ms-white"
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px', borderRadius: 999, boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)' }}
            >
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.dot }} />
              <span className="text-typo-body-500 text-ms-gray-700">{s.name}</span>
              <span className="text-typo-body-600 text-ms-gray-800" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {s.n}
              </span>
            </div>
          ))}
        </div>

        {/* 예약 테이블 — 한 줄 = 예약 하나 · 수정 요청은 기존 예약 아래에 이어 붙는다(D-14) */}
        <div className="bg-ms-white" style={{ borderRadius: 12, boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
          {wide && (
            <div
              className="bg-ms-gray-100 text-typo-caption-md-600 text-ms-gray-600"
              style={{ display: 'grid', gridTemplateColumns: COLS, gap: 20, padding: '12px 20px' }}
            >
              <span>본사 요청</span>
              <span>병원 상태</span>
              <span>비고</span>
            </div>
          )}

          {!data && (
            <div className="text-typo-body-400 text-ms-gray-500" style={{ padding: '72px 20px 80px', textAlign: 'center' }}>
              {live.error ?? '불러오는 중…'}
            </div>
          )}

          {data && !chains.length && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '72px 20px 80px', textAlign: 'center' }}>
              <div className="bg-ms-gray-100" style={{ width: 56, height: 56, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#9f9f9f" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="5" width="18" height="16" rx="2" />
                  <path d="M3 10h18M8 3v4M16 3v4" />
                </svg>
              </div>
              <span className="text-typo-heading-md-500 text-ms-gray-800">아직 받은 예약 요청이 없어요</span>
            </div>
          )}

          {chains.map((c) => (
            <div key={c.groupId} className="border-ms-gray-200" style={{ borderTopWidth: 1, borderTopStyle: 'solid', padding: '6px 0 8px' }}>
              {c.rows.length > 1 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 20px 2px' }}>
                  <span className="text-typo-caption-md-600 text-ms-gray-700">{c.name}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-500">예약 이력 {c.rows.length}건</span>
                </div>
              )}
              {c.rows.map((r) => (
                <Row
                  key={r.id}
                  c={c}
                  r={r}
                  wide={wide}
                  fresh={freshGt !== null && r.id > freshGt}
                  onPreview={() => setModal({ type: 'preview', id: r.id })}
                  onChange={() => setModal({ type: 'change', id: r.id })}
                  onShot={() => setModal({ type: 'shot', id: r.id })}
                />
              ))}
            </div>
          ))}
        </div>
      </main>

      {/* 토스트 — 1차 현황판 토스트와 같은 모양(bg-ms-gray-800 · 아래 28 · 그림자) */}
      {toast && (
        <div
          className="bg-ms-gray-800 text-ms-white"
          style={{
            position: 'fixed',
            left: '50%',
            bottom: 28,
            transform: 'translateX(-50%)',
            zIndex: 9999,
            borderRadius: 10,
            padding: '10px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            maxWidth: 'calc(100vw - 32px)',
            boxShadow: '0 6px 20px rgba(0,0,0,0.18)',
          }}
        >
          {toast.ok && (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5fd08a" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12l5 5L20 7" />
            </svg>
          )}
          <span className="text-typo-body-500" style={{ whiteSpace: 'nowrap' }}>
            {toast.text}
          </span>
        </div>
      )}

      {modal?.type === 'preview' && cur && OPEN.includes(cur.r.status) && (
        <PreviewModal
          r={cur.r}
          now={now}
          busy={busy}
          onClose={() => setModal(null)}
          onSubmit={() => {
            const mod = cur.r.status === 'modify_requested';
            // 시안 — 0.9초 로딩 뒤 등록(KOS 호출 자리)
            void act(
              () => Promise.all([api.registerResv(cur.r.id), sleep(900)]),
              mod ? 'KOS 예약을 수정하고 스크린샷을 붙였어요' : 'KOS 에 등록하고 스크린샷을 붙였어요',
            ).then(() => setModal(null));
          }}
        />
      )}
      {modal?.type === 'shot' && cur && <ShotModal c={cur.c} r={cur.r} onClose={() => setModal(null)} />}
      {modal?.type === 'change' && cur && OPEN.includes(cur.r.status) && (
        <ChangeModal
          r={cur.r}
          busy={busy}
          onClose={() => setModal(null)}
          onSubmit={(reason) => {
            void act(() => api.changeRequestResv(cur.r.id, reason), '본사에 변경 요청을 보냈어요').then((d) => d && setModal(null));
          }}
        />
      )}
    </div>
  );
}

// 예약 줄 — 본사 요청 카드 | 병원 상태 | 비고(버튼 · 스크린샷 · 사유). 폰(< 760px)은 세 칸을 위아래로
function Row({
  c,
  r,
  wide,
  fresh,
  onPreview,
  onChange,
  onShot,
}: {
  c: Chain;
  r: ResvRequest;
  wide: boolean;
  fresh: boolean;
  onPreview: () => void;
  onChange: () => void;
  onShot: () => void;
}) {
  const st = r.status;
  const sup = st === 'superseded';
  const live = OPEN.includes(st);
  const { stNote, plain } = notes(c, r);
  const cardCls = (live ? 'bg-primary-100 border-primary' : sup ? 'bg-ms-gray-100 border-ms-gray-300' : 'bg-ms-white border-ms-gray-300') + (fresh ? ' rv-new' : '');
  const s = ST[st];
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: wide ? COLS : 'minmax(0,1fr)',
        gap: wide ? 20 : 10,
        padding: wide ? '10px 20px' : '10px 16px',
        alignItems: 'start',
      }}
    >
      {/* 본사 요청 카드 */}
      <div style={{ display: 'flex', gap: 8, minWidth: 0 }}>
        {r.kind === 'modify' && (
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#b4b4b4"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ flex: 'none', marginTop: 12 }}
          >
            <path d="M6 3v10a4 4 0 0 0 4 4h9M15 13l4 4-4 4" />
          </svg>
        )}
        <div
          className={cardCls}
          style={{
            flex: 1,
            minWidth: 0,
            borderRadius: 10,
            borderWidth: 1,
            borderStyle: 'solid',
            padding: '12px 14px',
            display: 'flex',
            flexDirection: 'column',
            gap: 5,
            opacity: sup ? 0.75 : 1,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span className={sup ? 'text-typo-caption-md-600 text-ms-gray-500' : 'text-typo-caption-md-600 text-primary'}>{kindLabel(r)}</span>
            <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
              {stamp(r.receivedAt)} 받음
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span className="text-typo-body-600 text-ms-gray-800">{r.customer.name}</span>
            <span className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700" style={{ padding: '1px 6px', borderRadius: 4 }}>
              {r.customer.nat}
            </span>
            <VisitChip isNew={r.customer.isNew} />
          </div>
          <div className="text-typo-heading-md-500 text-ms-gray-800" style={{ fontVariantNumeric: 'tabular-nums' }}>
            <Segs segs={dtSegs(r)} />
          </div>
          <span className="text-typo-body-400 text-ms-gray-700">
            {r.proc}
            <span className="text-ms-gray-400"> · </span>통역 {r.lang}
          </span>
        </div>
      </div>

      {/* 병원 상태 */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6, paddingTop: wide ? 10 : 0 }}>
        <span
          className="text-typo-caption-md-600"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 10px',
            borderRadius: 999,
            background: s.bg,
            color: s.fg,
            border: '1px solid ' + s.bd,
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.fg }} />
          {s.name}
        </span>
        <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {stNote}
        </span>
      </div>

      {/* 비고 — 버튼 · 사유 · 스크린샷 */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8, paddingTop: wide ? 6 : 0, minWidth: 0 }}>
        {live && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button variant="solid" color="blue" size="md" onClick={onPreview}>
              {st === 'modify_requested' ? 'KOS 수정하기' : 'KOS 등록하기'}
            </Button>
            <Button variant="outlined" color="gray" size="md" onClick={onChange}>
              변경 요청하기
            </Button>
          </div>
        )}
        {r.snapshot && (DONE.includes(st) || sup) && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <Button variant="outlined" color={sup ? 'gray' : 'blue'} size="md" onClick={onShot}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="16" rx="2" />
                  <circle cx="9" cy="10" r="2" />
                  <path d="M21 16l-5-5-9 9" />
                </svg>
                {sup ? '이전 스크린샷' : '스크린샷 보기'}
              </span>
            </Button>
          </div>
        )}
        {r.changeReason && (
          <div
            style={{
              width: '100%',
              boxSizing: 'border-box',
              borderRadius: 8,
              padding: '10px 12px',
              background: '#fff5f5',
              border: '1px solid #ffd6d7',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
          >
            <span className="text-typo-caption-md-600" style={{ color: '#e5484d' }}>
              변경 요청 사유
            </span>
            <span className="text-typo-body-400 text-ms-gray-800" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {r.changeReason}
            </span>
            <span className="text-typo-caption-md-400 text-ms-gray-500">{stamp(r.changeAt)}</span>
          </div>
        )}
        {plain && <span className="text-typo-caption-md-400 text-ms-gray-500">{plain}</span>}
      </div>
    </div>
  );
}
