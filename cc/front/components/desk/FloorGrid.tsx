'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CORRIDORS,
  EMPTY,
  LAYOUT,
  ROLE_DOT,
  STAFFED,
  STATUS,
  capOf,
  custIn,
  presentIn,
  queuedIn,
  statusOf,
} from '@/lib/board';
import { fmtElapsed } from '@/lib/time';
import type { Board } from '@/lib/types';

export interface Route {
  ids: string[];
  cur: number;
}

interface Arrow {
  d: string;
  stroke: string;
  dash: string;
  marker: string;
}

interface Person {
  key: string;
  name: string;
  sub: string;
  cls: string;
  textCls: string;
}

const person = (key: string, role: string, name: string, sub = ''): Person => ({
  key,
  name,
  sub,
  cls: ROLE_DOT[role],
  textCls:
    role === '고객' ? 'text-typo-caption-md-600 text-ms-gray-800' : 'text-typo-caption-md-400 text-ms-gray-700',
});

// 도면 — 시안 rooms · corridors · 경로 화살표
export function FloorGrid({
  board,
  now,
  route,
  onOpen,
}: {
  board: Board;
  now: number;
  route: Route | null;
  onOpen: (id: string) => void;
}) {
  const gridRef = useRef<HTMLDivElement>(null);
  const [arrows, setArrows] = useState<Arrow[]>([]);
  const routeKey = route ? route.ids.join(',') + '#' + route.cur : '';

  const measure = useCallback(() => {
    const g = gridRef.current;
    const next: Arrow[] = [];
    if (g && route && route.ids.length > 1) {
      const gr = g.getBoundingClientRect();
      const box = (id: string) => {
        const el = g.querySelector('[data-room="' + id + '"]');
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { x: r.left - gr.left + r.width / 2, y: r.top - gr.top + r.height / 2, hw: r.width / 2, hh: r.height / 2 };
      };
      const edge = (o: { hw: number; hh: number }, dx: number, dy: number) =>
        Math.min(dx ? (o.hw + 8) / Math.abs(dx) : Infinity, dy ? (o.hh + 8) / Math.abs(dy) : Infinity, 0.5);
      for (let i = 0; i < route.ids.length - 1; i++) {
        const a = box(route.ids[i]);
        const b = box(route.ids[i + 1]);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const sa = edge(a, dx, dy);
        const sb = edge(b, dx, dy);
        const x0 = a.x + dx * sa;
        const y0 = a.y + dy * sa;
        const x1 = b.x - dx * sb;
        const y1 = b.y - dy * sb;
        const len = Math.hypot(x1 - x0, y1 - y0) || 1;
        const bow = Math.min(40, len * 0.2);
        const cx = (x0 + x1) / 2 - ((y1 - y0) / len) * bow;
        const cy = (y0 + y1) / 2 + ((x1 - x0) / len) * bow;
        const past = i < route.cur;
        next.push({
          d: `M${x0.toFixed(1)},${y0.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`,
          stroke: past ? 'var(--ms-gray-500, #9ca3af)' : 'var(--ms-primary)',
          dash: past ? 'none' : '7 5',
          marker: past ? 'url(#route-head-past)' : 'url(#route-head)',
        });
      }
    }
    setArrows((prev) => (prev.map((a) => a.d).join('|') === next.map((a) => a.d).join('|') ? prev : next));
    // routeKey 로 경로 변화를 잡는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  // 그린 뒤 다음 프레임에 방 위치를 재서 화살표를 맞춘다
  useEffect(() => {
    const id = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(id);
  }, [measure, board]);

  useEffect(() => {
    const g = gridRef.current;
    if (!g) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(g);
    return () => ro.disconnect();
  }, [measure]);

  return (
    <div
      ref={gridRef}
      className="bg-ms-gray-100"
      style={{
        position: 'relative',
        flex: 1,
        minWidth: 680,
        alignSelf: 'flex-start',
        minHeight: '100%',
        boxSizing: 'border-box',
        borderRadius: 8,
        padding: 6,
        display: 'grid',
        gridTemplateColumns: 'repeat(8, minmax(0, 1fr))',
        gridTemplateRows:
          'repeat(2, minmax(84px, auto)) 28px repeat(3, minmax(84px, auto)) 28px minmax(84px, auto)',
        gap: 6,
      }}
    >
      {CORRIDORS.map((c) => (
        <div
          key={c.row}
          className="border-ms-gray-300 text-ms-gray-500"
          style={{
            gridColumn: '1 / -1',
            gridRow: c.row,
            borderTopWidth: 1,
            borderTopStyle: 'dashed',
            borderBottomWidth: 1,
            borderBottomStyle: 'dashed',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            letterSpacing: '0.4em',
          }}
        >
          복도
        </div>
      ))}
      {LAYOUT.map((d) => {
        const cs = custIn(board, d.id);
        const pres = presentIn(board, d.id);
        const idle = board.staff.filter((s) => !s.queue.length && s.home === d.id);
        const clickable = capOf(d.id) > 0 || d.id === 'lounge';
        let cls = EMPTY;
        let timer = '';
        let label = '';
        let people: Person[] = [];
        let queued: { key: string; name: string; cls: string }[] = [];
        if (d.id === 'lounge') {
          cls = cs.length ? STATUS.wait.cls : EMPTY;
          timer = '대기 ' + cs.length + '명';
          label = '접수 후 대기';
          people = cs.map((c) => person(c.scheduleId, '고객', c.name, fmtElapsed(c.since, now)));
        } else if (cs.length) {
          const st = statusOf(board, d.id)!;
          cls = STATUS[st.key].cls;
          timer = fmtElapsed(cs[0].since, now);
          label = st.label;
          people = [
            ...cs.map((c) => person(c.scheduleId, '고객', c.name)),
            ...pres.map((s) => person(s.staffId, s.role, s.name)),
          ];
          queued = queuedIn(board, d.id).map((s) => ({ key: s.staffId, name: '다음 ' + s.name, cls: ROLE_DOT[s.role] }));
        } else {
          const away = board.customers.find((c) => !c.done && c.prev === d.id);
          if (away) {
            cls = STAFFED;
            label = away.name + ' 수면 중 · 복귀 예정';
          } else if (idle.length) cls = STAFFED;
          else if (capOf(d.id)) label = '비어있음';
          people = idle.map((s) => person(s.staffId, s.role, s.name));
        }
        const inRoute = route ? route.ids.includes(d.id) : false;
        const isCur = inRoute && route!.ids[route!.cur] === d.id;
        const isNext = inRoute && !isCur && route!.ids.slice(route!.cur + 1).includes(d.id);
        return (
          <div
            key={d.id}
            data-room={d.id}
            onClick={clickable ? () => onOpen(d.id) : undefined}
            className={'cc-room ' + cls}
            style={{
              gridColumn: `${d.col} / span ${d.cs}`,
              gridRow: d.row,
              minWidth: 0,
              boxSizing: 'border-box',
              borderRadius: 6,
              borderWidth: 1,
              borderStyle: 'solid',
              padding: '6px 8px',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              outline: isCur ? '2px solid var(--ms-primary)' : isNext ? '2px dashed var(--ms-primary)' : 'none',
              outlineOffset: 2,
              opacity: route && !inRoute ? 0.45 : 1,
              transition: 'opacity 160ms ease, box-shadow 160ms ease',
              position: 'relative',
              cursor: clickable ? 'pointer' : 'default',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <span className="text-typo-caption-md-600" style={{ display: 'block', whiteSpace: 'nowrap' }}>
                {d.name}
              </span>
              <span
                className="text-typo-caption-md-500 text-ms-gray-700"
                style={{ display: 'block', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}
              >
                {timer}
              </span>
            </div>
            <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ wordBreak: 'keep-all' }}>
              {label}
            </span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 8px' }}>
              {people.map((p) => (
                <span
                  key={p.key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0 4px',
                    whiteSpace: 'nowrap',
                    minWidth: 0,
                    maxWidth: '100%',
                  }}
                >
                  <span className={p.cls} style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0 }} />
                  {/* 실데이터의 긴 로마자 이름이 칸 밖으로 나가지 않게 줄임표(전체 이름은 title) */}
                  <span
                    className={p.textCls}
                    title={p.name}
                    style={{ minWidth: 0, maxWidth: 'calc(100% - 11px)', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {p.name}
                  </span>
                  <span
                    className="text-typo-caption-md-400 text-ms-gray-600"
                    style={{ fontVariantNumeric: 'tabular-nums' }}
                  >
                    {p.sub}
                  </span>
                </span>
              ))}
            </div>
            {queued.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 8px' }}>
                {queued.map((q) => (
                  <span
                    key={q.key}
                    style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap', opacity: 0.6 }}
                  >
                    <span className={q.cls} style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0 }} />
                    <span className="text-typo-caption-md-400 text-ms-gray-700">{q.name}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {route && arrows.length > 0 && (
        <svg
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            pointerEvents: 'none',
            overflow: 'visible',
            zIndex: 2,
          }}
        >
          <defs>
            <marker
              id="route-head"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="var(--ms-primary)" />
            </marker>
            <marker
              id="route-head-past"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="var(--ms-gray-500, #9ca3af)" />
            </marker>
          </defs>
          {arrows.map((a, i) => (
            <g key={i}>
              <path d={a.d} fill="none" stroke="#ffffff" strokeWidth={6} strokeLinecap="round" />
              <path
                d={a.d}
                fill="none"
                stroke={a.stroke}
                strokeWidth={2.5}
                strokeDasharray={a.dash}
                strokeLinecap="round"
                markerEnd={a.marker}
              />
            </g>
          ))}
        </svg>
      )}
    </div>
  );
}
