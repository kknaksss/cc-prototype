'use client';

// 예약 현황(SPEC-005 §6 · 전체현황판 시안 「현황 › 예약 현황」 M:93-715) — 제목 줄 · 스케줄 표 · 오른쪽 패널 · 등록 모달 · 상세 모달 · 토스트
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Button } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { useNow, useResvBoard, useSession, useWide } from '@/lib/hooks';
import { clearSession } from '@/lib/session';
import { hms } from '@/lib/time';
import type { ResvBoard, ResvCard, ResvColumn } from '@/lib/types';
import { HEADER_H } from '@/components/common/AppHeader';
import { ScheduleTable, cardKey } from '@/components/reservations/ScheduleTable';
import { ResvAside, type ResvTab } from '@/components/reservations/ResvAside';
import { NewReservationModal, type NewDraft } from '@/components/reservations/NewReservationModal';
import { DetailModal } from '@/components/reservations/DetailModal';
import { LEGEND, MAIN_NAME, dateTitle, isoAt, shiftDate } from '@/components/reservations/view';

const TOAST_MS = 2600; // 가운데 아래 · 2.6초(§6.7)
const SETTLE_MS = 2500; // 이동 성공 뒤 이만큼 낙관 표시를 두고 사본을 따른다(조작 직후 + 2초 뒤 다시 부름 — §4.3)

// 놓은 직후 카드를 새 자리로 미리 옮겨 보인다(낙관 표시 — §5.4). 실패면 지우고 원위치 + 토스트
interface Moved {
  groupId: number;
  start: string;
  end: string;
}

function withMoves(board: ResvBoard, moves: Record<string, Moved>): ResvBoard {
  if (!Object.keys(moves).length) return board;
  return { ...board, cards: board.cards.map((c) => (moves[cardKey(c)] ? { ...c, ...moves[cardKey(c)] } : c)) };
}

export default function ReservationsLivePage() {
  const session = useSession();
  const [date, setDate] = useState<string | null>(null); // null = 오늘(back 이 정함)
  const live = useResvBoard(session?.token ?? null, date);
  const now = useNow(30_000) + live.skew;
  const wide = useWide();

  const [moves, setMoves] = useState<Record<string, Moved>>({});
  const [tab, setTab] = useState<ResvTab>('requests');
  const [focus, setFocus] = useState<number | null>(null);
  const [draft, setDraft] = useState<NewDraft | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  const [toast, setToast] = useState<{ text: string; n: number } | null>(null);
  const flash = useCallback((text: string) => setToast((t) => ({ text, n: (t?.n ?? 0) + 1 })), []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(t);
  }, [toast]);

  const raw = live.board;
  const board = useMemo(() => (raw ? withMoves(raw, moves) : null), [raw, moves]);
  const shownDate = date ?? raw?.date ?? null;

  if (!session) return null;

  const fail = (e: unknown) => {
    if (e instanceof api.ApiError && e.status === 401) {
      clearSession();
      return;
    }
    flash(e instanceof Error ? e.message : '요청을 처리하지 못했어요');
  };

  const go = (n: number) => {
    if (!shownDate) return;
    setFocus(null);
    setDate(shiftDate(shownDate, n));
  };
  const goToday = () => {
    setFocus(null);
    setDate(null);
  };

  // 드래그 놓기 → 낙관 표시 → move(길이 = 원래 길이 · 같은 날짜 · 구역 그대로 — §5.4)
  const move = async (card: ResvCard, groupId: number, startMin: number) => {
    if (!board) return;
    const key = cardKey(card);
    const len = Date.parse(card.end) - Date.parse(card.start);
    const start = isoAt(board.date, startMin);
    const end = new Date(Date.parse(start) + (Number.isFinite(len) ? len : 30 * 60000)).toISOString();
    setMoves((m) => ({ ...m, [key]: { groupId, start, end } }));
    const drop = () =>
      setMoves((m) => {
        const next = { ...m };
        delete next[key];
        return next;
      });
    try {
      await api.moveReservation(card.reservationId, card.resourceIndex, groupId, start);
      flash(card.customer.name + ' 예약 이동');
      live.refreshSoon();
      setTimeout(drop, SETTLE_MS);
    } catch (e) {
      drop();
      fail(e);
    }
  };

  const add = (col: ResvColumn, startMin: number) => {
    if (!board || col.groupId === null) return;
    setDraft({ date: board.date, groupId: col.groupId, groupTitle: col.title, start: isoAt(board.date, startMin), startMin, endMin: startMin + col.intervalMinutes, zoneIds: col.capacities.map((z) => z.zoneId) });
  };

  // 원내 현황 카드 → 그 예약 상세 + 스케줄 표에서 그 카드로(시안 M:1960)
  const openFromClinic = (reservationId: number) => {
    setFocus(reservationId);
    setDetailId(reservationId);
  };

  const legend = board?.counts;

  return (
    <div data-screen-label="예약 현황" style={{ display: 'flex', flexDirection: 'column', height: `calc(100vh - ${HEADER_H}px)` }} className="bg-ms-gray-100">
      <main style={{ flex: 1, minHeight: 0, padding: wide ? '20px 28px' : 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* 제목 줄(§6.2 · 시안 M:96-110) */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px 24px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px 16px', flexWrap: 'wrap' }}>
            <h1 className="text-typo-title-md-600 text-ms-gray-800" style={{ margin: 0, whiteSpace: 'nowrap' }}>
              예약 현황
            </h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <NavBtn label="전날" text="‹" onClick={() => go(-1)} disabled={!shownDate} />
              <span className="text-typo-heading-md-500 text-ms-gray-800" style={{ minWidth: 140, textAlign: 'center', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                {shownDate ? dateTitle(shownDate) : ''}
              </span>
              <NavBtn label="다음날" text="›" onClick={() => go(1)} disabled={!shownDate} />
              <Button variant="outlined" color={board?.isToday ? 'gray' : 'blue'} size="sm" disabled={!board || board.isToday} onClick={goToday}>
                오늘
              </Button>
            </div>
            <span className="text-typo-body-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
              총 예약 {legend?.total ?? 0}건
            </span>
            {/* 동기화 글자 — 시술 현황 제목 줄과 같은 꼴(§6.2) */}
            <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
              마지막 KOS 조회 {board?.sync.lastOkAt ? hms(board.sync.lastOkAt) : '—'}
            </span>
            {(board?.sync.lastError || live.error) && (
              <span className="text-typo-caption-md-600 text-red" title={board?.sync.lastError ?? live.error ?? ''} style={{ whiteSpace: 'nowrap' }}>
                조회 실패
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            {LEGEND.map((k) => (
              <Badge key={k.main} variant={k.variant} size="sm" dot className={k.cls} style={k.style}>
                {MAIN_NAME[k.main]} {legend ? legend[k.main] : 0}
              </Badge>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, display: 'flex', gap: 12 }}>
          {board ? (
            <ScheduleTable board={board} nowMs={now} focusId={focus} onOpen={setDetailId} onAdd={add} onMove={(c, g, m) => void move(c, g, m)} />
          ) : (
            <div className="bg-ms-white" style={{ flex: 1, borderRadius: 12, padding: 24, boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)' }}>
              <span className="text-typo-body-400 text-ms-gray-500">{live.loading ? '불러오는 중…' : (live.error ?? '불러오는 중…')}</span>
            </div>
          )}
          {board && wide && <ResvAside board={board} tab={tab} onTab={setTab} onOpen={openFromClinic} />}
        </div>

        {toast && (
          <div
            key={toast.n}
            role="status"
            className="bg-ms-gray-800 text-ms-white text-typo-body-500"
            style={{
              position: 'fixed',
              left: '50%',
              bottom: 28,
              transform: 'translateX(-50%)',
              zIndex: 9999,
              borderRadius: 10,
              padding: '10px 16px',
              whiteSpace: 'nowrap',
              boxShadow: '0 6px 20px rgba(0,0,0,0.18)',
            }}
          >
            {toast.text}
          </div>
        )}
      </main>

      {draft && (
        <NewReservationModal
          draft={draft}
          onClose={() => setDraft(null)}
          onDone={(text) => {
            setDraft(null);
            flash(text);
            live.refreshSoon();
          }}
        />
      )}
      {detailId !== null && (
        <DetailModal
          reservationId={detailId}
          board={board}
          onClose={() => {
            setDetailId(null);
            setFocus(null);
          }}
          onChanged={(text) => {
            if (text) flash(text);
            live.refreshSoon();
          }}
          onError={fail}
        />
      )}
    </div>
  );
}

function NavBtn({ label, text, onClick, disabled }: { label: string; text: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="cc-btn bg-ms-white border-ms-gray-300 text-ms-gray-700"
      style={{ width: 32, height: 32, borderWidth: 1, borderStyle: 'solid', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}
    >
      {text}
    </button>
  );
}

