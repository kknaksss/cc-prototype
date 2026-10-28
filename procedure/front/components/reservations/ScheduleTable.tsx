'use client';

// 스케줄 표(SPEC-005 §5.2 ~ §5.4 · §6.3) — 시안 칸(M:113-162) · bookVals(M:1693-1727) 그대로
// 칸 = 예약 그룹(order 순 · 「그룹 없음」 맨 끝) · 줄 = 30분(축 06:00 ~ 22:00 고정 · 밖 예약이면 늘림 — E2E #4) ·
// 줄마다 그 시각에 시작하는 카드를 왼쪽부터 가로로 흘려 놓고(폭 196 · 간격 6) 칸 폭을 넘으면 다음 줄로 접는다 · 줄 높이 = 내용만큼(최소 72) ·
// [+] 는 그 줄 카드 뒤에 같은 흐름으로 · 칸 폭 = 13 + mx·196 + (mx−1)·6(mx = 한 줄에 놓인 카드 최대 수 · 화면 폭 상한 5/3/1) ·
// 카드는 시간 길이로 늘리지 않는다(2줄 · E2E #10) · 운영 밖 칸 = 회색 · 지금 줄 = 연한 primary(시안 rowCls)
// 15 · 60분 그룹도 일단 30분 줄(코디 지시 — 사용자 확인 중): 시작이 30분 경계가 아니면 그 30분 줄에 넣는다
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Badge } from '@medisolve-ai/medikit';
import type { ResvBoard, ResvCard, ResvColumn } from '@/lib/types';
import { Flag, SUB_NAME, barStyle, capacityText, genderIcon, hmToMin, isClosed, kstMin, minToHm, phaseOfSub, phaseStyle, visitChip } from './view';

const STEP = 30; // 줄 = 30분(시안)
const LABEL_W = 64;
const CARD_W = 196;
const GAP = 6;
const ROW_MIN = 72;
const AXIS_FROM = 6 * 60; // 축 06:00 ~ 22:00(E2E #4)
const AXIS_TO = 22 * 60;

// 칸당 한 줄에 놓는 카드 상한 — 화면 폭 1600 이상 5 · 1100 이상 3 · 그 밖 1(시안 M:1721)
const subscribeResize = (cb: () => void) => {
  window.addEventListener('resize', cb);
  return () => window.removeEventListener('resize', cb);
};
function usePerRow(): number {
  const vw = useSyncExternalStore(subscribeResize, () => window.innerWidth, () => 1920);
  return vw >= 1600 ? 5 : vw >= 1100 ? 3 : 1;
}

export const cardKey = (c: { reservationId: number; resourceIndex: number }) => c.reservationId + ':' + c.resourceIndex;

// 카드 시작 · 끝(분). 끝이 시작보다 이르면(자정 넘김) 하루 끝으로 본다
function spanOf(c: ResvCard): { s: number; e: number } | null {
  const s = kstMin(c.start);
  let e = kstMin(c.end);
  if (s === null) return null;
  if (e === null || e <= s) e = e === 0 ? 1440 : s + STEP;
  return { s, e };
}
// 카드가 놓이는 줄(시작을 30분 경계로 내림)
const slotOf = (c: ResvCard) => {
  const s = kstMin(c.start);
  return s === null ? null : Math.floor(s / STEP) * STEP;
};

// 축 — 06:00 ~ 22:00 고정 + 축 밖 묶음이면 30분 단위로 늘림
function axisOf(board: ResvBoard): { a0: number; a1: number } {
  let a0 = AXIS_FROM;
  let a1 = AXIS_TO;
  for (const c of board.cards) {
    const sp = spanOf(c);
    if (!sp) continue;
    a0 = Math.min(a0, Math.floor(sp.s / STEP) * STEP);
    a1 = Math.max(a1, Math.ceil(sp.e / STEP) * STEP);
  }
  return { a0, a1 };
}

// 운영 중인 줄인가(칸의 open 조각 안에 [m, m+30) 이 걸치면 운영)
const openAt = (col: ResvColumn, m: number) => col.open.some((o) => hmToMin(o.start) < m + STEP && m < hmToMin(o.end));

export function ScheduleTable({
  board,
  nowMs,
  focusId,
  onOpen,
  onAdd,
  onMove,
}: {
  board: ResvBoard;
  nowMs: number;
  focusId: number | null;
  onOpen: (reservationId: number) => void;
  onAdd: (col: ResvColumn, startMin: number) => void;
  onMove: (card: ResvCard, groupId: number, startMin: number) => void;
}) {
  const perRow = usePerRow();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<string | null>(null); // 칸|줄
  const [drag, setDrag] = useState<ResvCard | null>(null);
  const [over, setOver] = useState<{ ci: number; m: number; allowed: boolean } | null>(null);

  const { a0, a1 } = useMemo(() => axisOf(board), [board]);
  const nowMin = board.isToday ? kstMin(new Date(nowMs).toISOString()) : null;
  const nowRow = nowMin === null ? null : Math.floor(nowMin / STEP) * STEP;

  const times = useMemo(() => {
    const out: number[] = [];
    for (let m = a0; m < a1; m += STEP) out.push(m);
    return out;
  }, [a0, a1]);

  // 칸 · 줄별 카드(시작 순)
  // 끄는 카드(원본)는 끄는 동안 제자리에 그대로 둔다 — 원본 DOM 을 다른 칸으로 옮기거나 순서를 바꾸면 브라우저가 끌기를 바로 끝낸다
  // (b4 #1 「카드가 안 잡혀」 원인). 놓을 칸 미리보기는 따로 그리는 복제 카드(시안 bkOverCell → preview)
  const dragKey = drag ? cardKey(drag) : null;
  const cells = useMemo(() => {
    const m = new Map<string, ResvCard[]>();
    const sorted = [...board.cards].sort((a, b) => (kstMin(a.start) ?? 0) - (kstMin(b.start) ?? 0) || a.reservationId - b.reservationId);
    for (const c of sorted) {
      const slot = slotOf(c);
      if (slot === null) continue;
      const k = c.groupId + '|' + slot;
      m.set(k, [...(m.get(k) ?? []), c]);
    }
    return m;
  }, [board.cards]);
  // 미리보기 자리 = 놓을 수 있는 칸 · 제자리가 아닌 곳
  const previewAt =
    drag && over?.allowed && !(board.columns[over.ci]?.groupId === drag.groupId && over.m === slotOf(drag)) ? (board.columns[over.ci]?.groupId ?? null) + '|' + over.m : null;
  const cellCards = (gid: number | null, m: number) => cells.get(gid + '|' + m) ?? [];

  // 칸 폭 — mx = 그 칸 한 줄에 놓인 카드 최대 수(최소 1) · perRow 상한(시안 M:1722-1726)
  const widths = useMemo(
    () =>
      board.columns.map((col) => {
        let mx = 1;
        for (const m of times) {
          const k = col.groupId + '|' + m;
          mx = Math.max(mx, (cells.get(k) ?? []).length + (k === previewAt ? 1 : 0));
        }
        mx = Math.min(mx, perRow);
        return 13 + mx * CARD_W + (mx - 1) * GAP;
      }),
    [board.columns, times, cells, perRow, previewAt],
  );
  const grid = LABEL_W + 'px ' + widths.map((w) => w + 'px').join(' ');

  // [+] 줄 — rows[] 에 있으면 그 plusAllowed · 없는 줄(운영 밖 · 간격이 다른 줄)은 보인다(§5.4)
  const plusOf = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const r of board.rows) {
      const k = kstMin(r.start);
      if (k !== null) m.set(r.groupId + '|' + k, r.plusAllowed);
    }
    return (groupId: number, min: number) => m.get(groupId + '|' + min) ?? true;
  }, [board.rows]);
  // 슬롯 꽉 참(§5.4 — 그룹 · 구역 · 시작)
  const fullOf = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const s of board.slots) {
      const k = kstMin(s.start);
      if (k !== null) m.set(s.groupId + '|' + s.zoneId + '|' + k, s.full);
    }
    return (groupId: number, zoneId: number | null, min: number) => (zoneId === null ? false : (m.get(groupId + '|' + zoneId + '|' + min) ?? false));
  }, [board.slots]);

  // 들어오면 지금 줄(오늘) · 첫 운영 줄(다른 날)이 보이게 — 위 64px 여유(시안 focusNowOnEnter M:1313-1323). 날짜마다 한 번
  // 줄 높이가 내용만큼이라 위치는 DOM 에서 잰다. 옮긴 뒤에만 「했음」(다시 그려져 프레임이 취소되면 다음 효과에서 다시)
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || scrolledFor.current === board.date) return;
    const date = board.date;
    const raf = requestAnimationFrame(() => {
      const row = box.querySelector('[data-now="1"]') ?? box.querySelector('[data-open="1"]');
      const top = row ? box.scrollTop + row.getBoundingClientRect().top - box.getBoundingClientRect().top - 64 : 0;
      box.scrollTo({ top: Math.max(0, top) });
      scrolledFor.current = date;
    });
    return () => cancelAnimationFrame(raf);
  }, [board.date, times]);

  // 원내 현황에서 고른 카드로 스크롤(§6.4 · 시안 M:1960)
  useEffect(() => {
    if (focusId == null) return;
    const el = scrollRef.current?.querySelector(`[data-resv="${focusId}"]`);
    el?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
  }, [focusId, board.date]);

  const endDrag = () => {
    setDrag(null);
    setOver(null);
  };

  return (
    <div
      ref={scrollRef}
      data-cal-scroll="1"
      className="bg-ms-white"
      style={{ flex: 1, minWidth: 0, minHeight: 0, borderRadius: 12, overflow: 'auto', boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)' }}
    >
      <div style={{ minWidth: 'max-content' }}>
        {/* 칸 머리 — sticky top · 「{그룹}」 「{N}건」 / 정원 · 간격 */}
        <div
          className="bg-ms-white border-ms-gray-300"
          style={{ position: 'sticky', top: 0, zIndex: 4, display: 'grid', gridTemplateColumns: grid, borderBottomWidth: 2, borderBottomStyle: 'solid' }}
        >
          <div className="bg-ms-white" style={{ position: 'sticky', left: 0, zIndex: 1 }} />
          {board.columns.map((col) => (
            <div
              key={String(col.groupId)}
              className="border-ms-gray-300"
              style={{ padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 2, borderLeftWidth: 1, borderLeftStyle: 'solid', minWidth: 0 }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
                <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {col.title}
                </span>
                <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                  {col.count}건
                </span>
              </div>
              <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {col.groupId === null ? '' : capacityText(col, board.zones) + ' / ' + col.intervalMinutes + '분'}
              </span>
            </div>
          ))}
        </div>

        {/* 30분 줄 — 시안 M:122-160 */}
        {times.map((m) => {
          const now = m === nowRow;
          const anyOpen = board.columns.some((c) => c.groupId !== null && openAt(c, m));
          return (
            <div
              key={m}
              data-now={now ? '1' : '0'}
              data-open={anyOpen ? '1' : '0'}
              className="border-ms-gray-300"
              style={{ display: 'grid', gridTemplateColumns: grid, minHeight: ROW_MIN, borderBottomWidth: 1, borderBottomStyle: 'solid' }}
            >
              <span
                className={'text-typo-caption-md-500 ' + (now ? 'text-primary bg-primary-100' : 'text-ms-gray-600 bg-ms-white')}
                style={{ position: 'sticky', left: 0, zIndex: 1, padding: '8px 12px 0 0', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
              >
                {minToHm(m)}
              </span>
              {board.columns.map((col, ci) => {
                const gid = col.groupId;
                const list = cellCards(gid, m);
                const key = ci + '|' + m;
                const closed = gid !== null && !openAt(col, m);
                const ov = over && over.ci === ci && over.m === m ? over : null;
                const showAdd = !drag && hover === key && gid !== null && plusOf(gid, m);
                const bg = ov?.allowed ? 'bg-primary-100' : now && !closed ? 'bg-primary-100' : closed ? 'bg-ms-gray-100' : 'bg-ms-white';
                return (
                  <div
                    key={String(gid)}
                    className={bg + ' border-ms-gray-300'}
                    style={{
                      outline: ov ? '2px dashed ' + (ov.allowed ? 'var(--ms-primary, #2498bd)' : 'var(--ms-red, #f04452)') : 'none',
                      outlineOffset: -3,
                      borderLeftWidth: 1,
                      borderLeftStyle: 'solid',
                      padding: 6,
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 6,
                      alignContent: 'flex-start',
                      minWidth: 0,
                    }}
                    // [+] = 카드 없는 빈 공간에 호버할 때만(카드 위 = 카드 자체 동작만 — E2E b5 #3)
                    onMouseOver={(e) => {
                      const onCard = !!(e.target as HTMLElement).closest('[data-resv]');
                      setHover((h) => (onCard ? (h === key ? null : h) : key));
                    }}
                    onMouseLeave={() => setHover((h) => (h === key ? null : h))}
                    onDragOver={(e) => {
                      if (!drag) return;
                      const origin = gid === drag.groupId && m === slotOf(drag);
                      // 놓기 금지 = 「그룹 없음」 칸 · 그 칸에 끄는 카드 구역이 안 켜짐 · 그 줄 슬롯 full — 제자리는 허용(§5.4)
                      const zoneOn = col.capacities.some((z) => z.zoneId === drag.zoneId);
                      const allowed = gid !== null && (origin || (zoneOn && !fullOf(gid, drag.zoneId, m)));
                      if (allowed) e.preventDefault();
                      e.dataTransfer.dropEffect = allowed ? 'move' : 'none';
                      if (over?.ci !== ci || over.m !== m || over.allowed !== allowed) setOver({ ci, m, allowed });
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      const d = drag;
                      const o = over;
                      endDrag();
                      if (!d || !o || o.ci !== ci || o.m !== m || !o.allowed || gid === null) return;
                      if (gid === d.groupId && m === slotOf(d)) return; // 제자리
                      onMove(d, gid, m);
                    }}
                  >
                    {list.map((c) => {
                      const k = cardKey(c);
                      return (
                        <CardView
                          key={k}
                          card={c}
                          dragging={k === dragKey}
                          focused={focusId === c.reservationId}
                          onOpen={() => onOpen(c.reservationId)}
                          onDragStart={(e) => {
                            e.dataTransfer.effectAllowed = 'move';
                            e.dataTransfer.setData('text/plain', k);
                            // 상태 바꿈(다시 그림)은 끌기가 시작된 다음 틱에 — dragstart 안에서 DOM 을 바꾸면 끌기가 취소되는 브라우저가 있다
                            setTimeout(() => {
                              setHover(null);
                              setDrag(c);
                            }, 0);
                          }}
                          onDragEnd={endDrag}
                        />
                      );
                    })}
                    {drag && previewAt === gid + '|' + m && <CardView key="preview" card={drag} preview />}
                    {/* 빈 자리 호버 [+] — 카드 뒤 같은 흐름 · 폭 196 · 최소 높이 50 · 시각은 상자 안에(떠 있는 툴팁이 카드를 가려 뺌 — E2E b5 #3) */}
                    {showAdd && (
                      <button
                        type="button"
                        aria-label={'예약 추가 · ' + col.title + ' ' + minToHm(m) + ' ~ ' + minToHm(m + STEP)}
                        onClick={(e) => {
                          e.stopPropagation();
                          onAdd(col, m);
                        }}
                        className="bg-ms-gray-100 border-ms-gray-400 text-ms-gray-700"
                        style={{ flex: '0 0 196px', minHeight: 50, boxSizing: 'border-box', borderWidth: 1, borderStyle: 'dashed', borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
                      >
                        <span style={{ fontSize: 20, lineHeight: 1 }}>+</span>
                        <span className="text-typo-body-500" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                          {minToHm(m)} ~ {minToHm(m + STEP)}
                        </span>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 예약 카드(§6.3 · 시안 M:130-149) — 폭 196 · 반경 6 · 왼쪽 막대 4px = 주 상태 색 · 내용 2줄(시간 길이로 늘리지 않는다)
// preview = 놓을 칸에 그리는 복제(점선 · 누를 수 없음) · dragging = 끄는 중인 원본(제자리에 흐리게)
function CardView({
  card,
  preview = false,
  dragging = false,
  focused = false,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  card: ResvCard;
  preview?: boolean;
  dragging?: boolean;
  focused?: boolean;
  onOpen?: () => void;
  onDragStart?: (e: React.DragEvent) => void;
  onDragEnd?: () => void;
}) {
  const canDrag = card.draggable && !preview;
  const c = card.customer;
  const bar = barStyle(card.state);
  const g = genderIcon(c.gender);
  const v = visitChip(c.isNew);
  const closed = isClosed(card.state);
  return (
    <div
      data-resv={preview ? undefined : card.reservationId}
      role={preview ? undefined : 'button'}
      tabIndex={preview ? undefined : 0}
      aria-hidden={preview || undefined}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen?.();
      }}
      draggable={canDrag}
      onDragStart={canDrag ? onDragStart : undefined}
      onDragEnd={onDragEnd}
      className={preview ? 'bg-primary-100 border-primary' : 'bg-ms-white border-ms-gray-300'}
      style={{
        flex: '0 0 196px',
        minWidth: 0,
        boxSizing: 'border-box',
        display: 'flex',
        borderWidth: 1,
        borderStyle: preview ? 'dashed' : 'solid',
        borderRadius: 6,
        overflow: 'hidden',
        cursor: canDrag ? 'grab' : 'pointer',
        opacity: dragging ? 0.4 : closed ? 0.5 : 1,
        pointerEvents: preview ? 'none' : undefined,
        outline: focused ? '2px solid var(--ms-primary, #2498bd)' : 'none',
      }}
    >
      <span className={bar.cls} style={{ width: 4, flexShrink: 0, ...bar.style }} />
      <div style={{ flex: 1, minWidth: 0, padding: '5px 6px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
          {g && (
            <span className={g.cls} aria-label={g.label} style={{ flexShrink: 0, fontSize: 13, lineHeight: '16px', fontWeight: 700 }}>
              {g.icon}
            </span>
          )}
          <span
            className="text-typo-caption-md-600 text-ms-gray-800"
            style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', textDecoration: closed ? 'line-through' : 'none' }}
          >
            {c.name}
          </span>
          <span className={v.cls} style={{ flexShrink: 0, fontSize: 11, lineHeight: '16px', fontWeight: 600, padding: '0 5px', borderRadius: 4, whiteSpace: 'nowrap' }}>
            {v.text}
          </span>
          {card.state.sub && (
            // 부상태 칩 — 대기 연한 색 · 진행 채움 · 완료 회색(phaseStyle · E2E b3 #3)
            <span
              className={phaseStyle(card.state.main, phaseOfSub(card.state.sub) ?? 'none').chip}
              style={{ flexShrink: 0, fontSize: 11, lineHeight: '16px', fontWeight: 600, padding: '0 5px', borderRadius: 4, whiteSpace: 'nowrap' }}
            >
              {SUB_NAME[card.state.sub]}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
          <Flag code={c.nationality} />
          <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {c.phoneticName ?? ''}
          </span>
          {card.paymentRequiredCount >= 1 && (
            <span style={{ flexShrink: 0, display: 'inline-flex' }}>
              <Badge variant="warning" size="sm">
                수납 필요
              </Badge>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
