'use client';

// 스케줄 표(SPEC-005 §5.2 ~ §5.4 · §6.3 · 시안 M:113-162)
// 칸 = 예약 그룹(order 순 · 「그룹 없음」 맨 끝) · 세로축 = 그날 운영 시간의 합(운영 밖 예약이면 늘림) · 1시간 높이는 모든 칸이 같다 ·
// 칸마다 자기 간격으로 줄 · 운영 밖 = 회색 · 카드 = 묶음당 한 장(시각 위치 · 높이 = 길이) · 겹치면 왼쪽부터 나란히
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Badge } from '@medisolve-ai/medikit';
import type { ResvBoard, ResvCard, ResvColumn } from '@/lib/types';
import { Flag, SUB_NAME, barStyle, capacityText, genderIcon, hmToMin, isClosed, kstMin, minToHm, visitChip } from './view';

const HOUR = 144; // 1시간 높이(px) — 시안 30분 줄 최소 72 와 같다(§5.2 · OQ-757)
const PPM = HOUR / 60;
const LABEL_W = 64;
const CARD_W = 196;
const GAP = 6;
const HEAD_H = 62;
const TWO_LINES = 44; // 이보다 낮은 카드는 둘째 줄을 숨긴다(§6.3)

// 칸당 나란히 놓는 카드 상한 — 화면 폭 1600 이상 5 · 1100 이상 3 · 그 밖 1(시안 M:1721-1727). 넘치면 칸 안 가로 스크롤
const subscribeResize = (cb: () => void) => {
  window.addEventListener('resize', cb);
  return () => window.removeEventListener('resize', cb);
};
function usePerRow(): number {
  const vw = useSyncExternalStore(subscribeResize, () => window.innerWidth, () => 1920);
  return vw >= 1600 ? 5 : vw >= 1100 ? 3 : 1;
}

export const cardKey = (c: { reservationId: number; resourceIndex: number }) => c.reservationId + ':' + c.resourceIndex;

interface Placed {
  card: ResvCard;
  s: number; // 그날 KST 분
  e: number;
  lane: number;
}

// 카드 시작 · 끝(분). 끝이 시작보다 이르면(자정 넘김) 하루 끝으로 본다
function spanOf(c: ResvCard): { s: number; e: number } | null {
  const s = kstMin(c.start);
  let e = kstMin(c.end);
  if (s === null) return null;
  if (e === null || e <= s) e = e === 0 ? 1440 : s + 30;
  return { s, e };
}

// 겹치는 카드는 왼쪽부터 빈 자리에(시작 순)
function layout(cards: ResvCard[], minLen: number): { placed: Placed[]; lanes: number } {
  const items = cards
    .map((card) => {
      const sp = spanOf(card);
      return sp ? { card, s: sp.s, e: Math.max(sp.e, sp.s + minLen) } : null;
    })
    .filter((x): x is { card: ResvCard; s: number; e: number } => !!x)
    .sort((a, b) => a.s - b.s || a.card.reservationId - b.card.reservationId);
  const ends: number[] = [];
  const placed = items.map((it) => {
    let lane = ends.findIndex((end) => end <= it.s);
    if (lane < 0) {
      lane = ends.length;
      ends.push(it.e);
    } else ends[lane] = it.e;
    return { ...it, lane };
  });
  return { placed, lanes: Math.max(1, ends.length) };
}

// [s, e) 에서 비어 있는 첫 자리(없으면 0 — 위에 겹쳐 그린다)
function freeLane(placed: Placed[], s: number, e: number, lanes: number, skip?: string): number {
  for (let l = 0; l < lanes + 1; l++) {
    if (!placed.some((p) => p.lane === l && p.s < e && s < p.e && cardKey(p.card) !== skip)) return l;
  }
  return 0;
}

// 축(§5.2) — 운영 시간의 합 + 축 밖 묶음이면 30분 단위로 늘림. 운영 안 하는 날(axis null)이고 카드도 없으면 null
function axisOf(board: ResvBoard): { a0: number; a1: number } | null {
  let a0 = board.axis ? hmToMin(board.axis.start) : null;
  let a1 = board.axis ? hmToMin(board.axis.end) : null;
  for (const c of board.cards) {
    const sp = spanOf(c);
    if (!sp) continue;
    const lo = Math.floor(sp.s / 30) * 30;
    const hi = Math.ceil(sp.e / 30) * 30;
    a0 = a0 === null ? lo : Math.min(a0, lo);
    a1 = a1 === null ? hi : Math.max(a1, hi);
  }
  return a0 === null || a1 === null || a1 <= a0 ? null : { a0, a1 };
}

export interface DragState {
  key: string;
  card: ResvCard;
}

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
  const [hover, setHover] = useState<{ col: number; m: number } | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [over, setOver] = useState<{ col: number; m: number; allowed: boolean } | null>(null);

  const axis = useMemo(() => axisOf(board), [board]);
  const nowMin = board.isToday ? kstMin(new Date(nowMs).toISOString()) : null;

  // 칸별 카드 배치
  const cols = useMemo(
    () =>
      board.columns.map((col) => {
        const cards = board.cards.filter((c) => c.groupId === col.groupId);
        const { placed, lanes } = layout(cards, col.intervalMinutes);
        const shown = Math.min(lanes, perRow);
        return { col, placed, lanes, width: 13 + shown * CARD_W + (shown - 1) * GAP, inner: 13 + lanes * CARD_W + (lanes - 1) * GAP };
      }),
    [board, perRow],
  );

  // [+] 줄 — rows[] 에 있으면 그 plusAllowed · 운영 밖 줄(rows[] 에 없음)은 보인다(§5.4 「운영 시간 안팎 상관없이」)
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

  // 들어오면(오늘) 지금 줄이 보이게 — 위 64px 여유(시안 M:1313-1323). 날짜마다 한 번
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || !axis || scrolledFor.current === board.date) return;
    scrolledFor.current = board.date;
    if (nowMin === null) {
      box.scrollTo({ top: 0 });
      return;
    }
    const y = Math.floor((nowMin - axis.a0) / 30) * 30 * PPM;
    box.scrollTo({ top: Math.max(0, y - 64) });
  }, [board.date, axis, nowMin]);

  // 원내 현황에서 고른 카드로 스크롤(§6.4 · 시안 M:1960)
  useEffect(() => {
    if (focusId == null) return;
    const el = scrollRef.current?.querySelector(`[data-resv="${focusId}"]`);
    el?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
  }, [focusId, board.date]);

  if (!axis)
    return (
      <div className="bg-ms-white" style={{ flex: 1, borderRadius: 12, padding: 24, boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)' }}>
        <span className="text-typo-body-400 text-ms-gray-500">운영하지 않는 날이에요</span>
      </div>
    );

  const { a0, a1 } = axis;
  const height = (a1 - a0) * PPM;
  const grid = LABEL_W + 'px ' + cols.map((c) => c.width + 'px').join(' ');
  const labels: number[] = [];
  for (let m = a0; m < a1; m += 30) labels.push(m);
  // 줄 경계 = 축 시작을 그 칸 간격으로 내린 점부터 간격마다(= 자정 기준 경계 · back lines 와 같은 기준 — r1 W2)
  const rowBase = (iv: number) => a0 - (a0 % iv);
  const rowAt = (col: ResvColumn, y: number) => {
    const iv = col.intervalMinutes || 30;
    const base = rowBase(iv);
    const at = a0 + Math.max(0, y) / PPM;
    const m = base + Math.floor((at - base) / iv) * iv;
    return Math.min(m, base + Math.floor((a1 - 1 - base) / iv) * iv);
  };
  // 줄 [m, m + iv) 중 축 안 부분의 위 · 높이(px) — 첫 줄은 축 시작보다 앞에서 시작할 수 있다
  const band = (m: number, iv: number) => {
    const s = Math.max(m, a0);
    const e = Math.min(m + iv, a1);
    return { top: (s - a0) * PPM, height: Math.max(0, e - s) * PPM };
  };

  return (
    <div
      ref={scrollRef}
      className="bg-ms-white"
      style={{ flex: 1, minWidth: 0, minHeight: 0, borderRadius: 12, overflow: 'auto', boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)' }}
    >
      <div style={{ minWidth: 'max-content' }}>
        {/* 칸 머리 — sticky top · 「{그룹}」 「{N}건」 / 「{정원}명 / {간격}분」 */}
        <div
          className="bg-ms-white border-ms-gray-300"
          style={{ position: 'sticky', top: 0, zIndex: 4, display: 'grid', gridTemplateColumns: grid, height: HEAD_H, boxSizing: 'border-box', borderBottomWidth: 2, borderBottomStyle: 'solid' }}
        >
          <div className="bg-ms-white" style={{ position: 'sticky', left: 0, zIndex: 1 }} />
          {cols.map(({ col }) => (
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

        {/* 몸통 */}
        <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: grid, height }}>
          {/* 시각 라벨 30분 — sticky left */}
          <div className="bg-ms-white" style={{ position: 'sticky', left: 0, zIndex: 3, height }}>
            {labels.map((m) => {
              const now = nowMin !== null && m <= nowMin && nowMin < m + 30;
              return (
                <span
                  key={m}
                  className={'text-typo-caption-md-500 ' + (now ? 'text-primary' : 'text-ms-gray-600')}
                  style={{ position: 'absolute', top: (m - a0) * PPM, right: 12, paddingTop: 8, fontVariantNumeric: 'tabular-nums' }}
                >
                  {minToHm(m)}
                </span>
              );
            })}
          </div>

          {cols.map(({ col, placed, lanes, inner }, ci) => {
            const iv = col.intervalMinutes || 30;
            const lines: number[] = [];
            for (let m = rowBase(iv) + iv; m < a1; m += iv) if (m > a0) lines.push(m);
            const showPlus = !drag && hover?.col === ci && col.groupId !== null && plusOf(col.groupId, hover.m);
            const plusLane = showPlus && hover ? freeLane(placed, hover.m, hover.m + iv, lanes) : 0;
            const ov = over?.col === ci ? over : null;
            const dragSpan = drag ? spanOf(drag.card) : null;
            const dragLen = dragSpan ? dragSpan.e - dragSpan.s : iv;
            return (
              <div
                key={String(col.groupId)}
                className={(col.groupId === null ? 'bg-ms-white' : 'bg-ms-gray-100') + ' border-ms-gray-300'}
                style={{ position: 'relative', height, borderLeftWidth: 1, borderLeftStyle: 'solid', overflowX: inner > cols[ci].width ? 'auto' : 'hidden', overflowY: 'hidden' }}
                onMouseMove={(e) => {
                  if (drag) return;
                  const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
                  const m = rowAt(col, y);
                  if (hover?.col !== ci || hover.m !== m) setHover({ col: ci, m });
                }}
                onMouseLeave={() => setHover((h) => (h?.col === ci ? null : h))}
                onDragOver={(e) => {
                  if (!drag) return;
                  const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
                  const m = rowAt(col, y);
                  const origin = col.groupId === drag.card.groupId && m === kstMin(drag.card.start);
                  // 놓기 금지 = 「그룹 없음」 칸 · 그 칸에 끄는 카드 구역이 안 켜짐(addendum-1 W2) · 그 줄의 (그 칸 그룹 · 카드 구역) 슬롯 full — 제자리는 허용(§5.4)
                  const zoneOn = col.capacities.some((z) => z.zoneId === drag.card.zoneId);
                  const allowed = col.groupId !== null && (origin || (zoneOn && !fullOf(col.groupId, drag.card.zoneId, m)));
                  if (allowed) e.preventDefault();
                  e.dataTransfer.dropEffect = allowed ? 'move' : 'none';
                  if (over?.col !== ci || over.m !== m || over.allowed !== allowed) setOver({ col: ci, m, allowed });
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver((o) => (o?.col === ci ? null : o));
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  const d = drag;
                  const o = over;
                  setDrag(null);
                  setOver(null);
                  if (!d || !o || o.col !== ci || !o.allowed || col.groupId === null) return;
                  if (col.groupId === d.card.groupId && o.m === kstMin(d.card.start)) return; // 제자리
                  onMove(d.card, col.groupId, o.m);
                }}
              >
                <div style={{ position: 'relative', width: inner, height }}>
                  {/* 운영 구간 = 흰색(그 밖 회색 · 쉬는 시간 빠진 조각) */}
                  {col.groupId !== null &&
                    col.open.map((o) => {
                      const s = Math.max(a0, hmToMin(o.start));
                      const e = Math.min(a1, hmToMin(o.end));
                      return e > s ? <div key={o.start} className="bg-ms-white" style={{ position: 'absolute', left: 0, right: 0, top: (s - a0) * PPM, height: (e - s) * PPM }} /> : null;
                    })}
                  {/* 칸 간격 줄 — 정시는 진하게 */}
                  {lines.map((m) => (
                    <div
                      key={m}
                      className={m % 60 === 0 ? 'border-ms-gray-300' : 'border-ms-gray-200'}
                      style={{ position: 'absolute', left: 0, right: 0, top: (m - a0) * PPM, borderTopWidth: 1, borderTopStyle: m % 60 === 0 ? 'solid' : 'dashed' }}
                    />
                  ))}

                  {/* 드래그 중 놓을 줄 — primary 점선 · 금지면 빨간 점선(§5.4) */}
                  {ov && (
                    <div
                      style={{
                        position: 'absolute',
                        left: 2,
                        right: 2,
                        top: band(ov.m, iv).top + 2,
                        height: band(ov.m, iv).height - 4,
                        outline: '2px dashed ' + (ov.allowed ? 'var(--ms-primary, #2498bd)' : 'var(--ms-red, #f04452)'),
                        outlineOffset: -1,
                        borderRadius: 4,
                        background: ov.allowed ? 'rgba(36, 152, 189, 0.08)' : 'rgba(240, 68, 82, 0.06)',
                        pointerEvents: 'none',
                        zIndex: 2, // 카드 위에 — 꽉 찬 줄은 카드로 덮여 있다
                      }}
                    />
                  )}

                  {placed.map((p) => (
                    <CardView
                      key={cardKey(p.card)}
                      card={p.card}
                      top={(p.s - a0) * PPM + 1}
                      left={GAP + p.lane * (CARD_W + GAP)}
                      height={Math.max((p.e - p.s) * PPM, iv * PPM) - 2}
                      focused={focusId === p.card.reservationId}
                      dragging={drag?.key === cardKey(p.card)}
                      onOpen={() => onOpen(p.card.reservationId)}
                      onDragStart={(e) => {
                        e.dataTransfer.effectAllowed = 'move';
                        e.dataTransfer.setData('text/plain', cardKey(p.card));
                        setHover(null);
                        setDrag({ key: cardKey(p.card), card: p.card });
                      }}
                      onDragEnd={() => {
                        setDrag(null);
                        setOver(null);
                      }}
                    />
                  ))}

                  {/* 끄는 카드 미리보기 — 점선(시안 M:1708-1717) */}
                  {ov && ov.allowed && drag && (
                    <div
                      className="bg-primary-100 border-primary"
                      style={{
                        position: 'absolute',
                        top: band(ov.m, iv).top + 1,
                        left: GAP + freeLane(placed, ov.m, ov.m + dragLen, lanes, drag.key) * (CARD_W + GAP),
                        width: CARD_W,
                        height: Math.max(dragLen, iv) * PPM - 2,
                        boxSizing: 'border-box',
                        borderWidth: 1,
                        borderStyle: 'dashed',
                        borderRadius: 6,
                        padding: '5px 8px',
                        pointerEvents: 'none',
                        zIndex: 2,
                      }}
                    >
                      <span className="text-typo-caption-md-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                        {drag.card.customer.name}
                      </span>
                    </div>
                  )}

                  {/* 빈 칸 호버 [+] — 점선 상자 196 · 최소 높이 50 · 위 검은 툴팁(시안 M:151-156) */}
                  {showPlus && hover && (
                    <div style={{ position: 'absolute', top: band(hover.m, iv).top + GAP, left: GAP + plusLane * (CARD_W + GAP), width: CARD_W, zIndex: 3 }}>
                      <button
                        type="button"
                        aria-label="예약 추가"
                        onClick={(e) => {
                          e.stopPropagation();
                          onAdd(col, hover.m);
                        }}
                        className="bg-ms-gray-100 border-ms-gray-400 text-ms-gray-700"
                        style={{
                          width: '100%',
                          minHeight: 50,
                          height: Math.max(50, iv * PPM - 2 * GAP),
                          boxSizing: 'border-box',
                          borderWidth: 1,
                          borderStyle: 'dashed',
                          borderRadius: 6,
                          fontSize: 24,
                          lineHeight: 1,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        +
                      </button>
                      {hover.m - a0 > 0 && (
                        <span
                          className="bg-ms-gray-800 text-ms-white text-typo-body-500"
                          style={{
                            position: 'absolute',
                            left: '50%',
                            bottom: 'calc(100% + 6px)',
                            transform: 'translateX(-50%)',
                            whiteSpace: 'nowrap',
                            padding: '6px 12px',
                            borderRadius: 8,
                            pointerEvents: 'none',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                          }}
                        >
                          {col.title}
                          <span style={{ opacity: 0.4 }}>|</span>
                          {minToHm(hover.m)} ~ {minToHm(hover.m + iv)}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {/* 지금 시각 줄(오늘만) — 가는 primary 가로선(§6.3 · 지난 시각 회색은 쓰지 않는다) */}
          {nowMin !== null && nowMin >= a0 && nowMin <= a1 && (
            <div
              aria-hidden
              style={{ position: 'absolute', left: LABEL_W, right: 0, top: (nowMin - a0) * PPM, height: 0, borderTop: '1.5px solid var(--ms-primary, #2498bd)', zIndex: 2, pointerEvents: 'none' }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// 예약 카드(§6.3 · 시안 M:130-149) — 폭 196 · 반경 6 · 왼쪽 막대 4px = 주 상태 색
function CardView({
  card,
  top,
  left,
  height,
  focused,
  dragging,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  card: ResvCard;
  top: number;
  left: number;
  height: number;
  focused: boolean;
  dragging: boolean;
  onOpen: () => void;
  onDragStart: (e: React.DragEvent) => void;
  onDragEnd: () => void;
}) {
  const c = card.customer;
  const bar = barStyle(card.state);
  const g = genderIcon(c.gender);
  const v = visitChip(c.isNew);
  const closed = isClosed(card.state);
  const two = height >= TWO_LINES;
  const pay = card.paymentRequiredCount >= 1 && (
    <span style={{ flexShrink: 0, display: 'inline-flex' }}>
      <Badge variant="warning" size="sm">
        수납 필요
      </Badge>
    </span>
  );
  return (
    <div
      data-resv={card.reservationId}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen();
      }}
      draggable={card.draggable}
      onDragStart={card.draggable ? onDragStart : undefined}
      onDragEnd={onDragEnd}
      className="bg-ms-white border-ms-gray-300"
      style={{
        position: 'absolute',
        top,
        left,
        width: CARD_W,
        height,
        boxSizing: 'border-box',
        display: 'flex',
        borderWidth: 1,
        borderStyle: 'solid',
        borderRadius: 6,
        overflow: 'hidden',
        cursor: card.draggable ? 'grab' : 'pointer',
        opacity: dragging ? 0.35 : closed ? 0.5 : 1,
        outline: focused ? '2px solid var(--ms-primary, #2498bd)' : 'none',
        zIndex: focused ? 2 : 1,
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
            <span
              className="border-ms-gray-300 text-ms-gray-600"
              style={{ flexShrink: 0, fontSize: 11, lineHeight: '14px', fontWeight: 600, padding: '0 4px', borderRadius: 4, borderWidth: 1, borderStyle: 'solid', whiteSpace: 'nowrap' }}
            >
              {SUB_NAME[card.state.sub]}
            </span>
          )}
          {!two && pay}
        </div>
        {two && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
            <Flag code={c.nationality} />
            <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {c.phoneticName ?? ''}
            </span>
            {pay}
          </div>
        )}
      </div>
    </div>
  );
}
