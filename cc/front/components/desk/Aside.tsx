'use client';

import { Badge, Button, Tabs } from '@medisolve-ai/medikit';
import { BOX, KEYS, ROLES, ROLE_COLOR, SSTATE, STATUS, boxKey, hereCustomers, roomName, stepNum } from '@/lib/board';
import { elapsedSec, fmtElapsed } from '@/lib/time';
import type { Board, Reservation, StaffWork } from '@/lib/types';
import { natName } from '@/components/staff/common';

export type TabId = 'resv' | 'status' | 'staff' | 'customer';
const TABS = [
  { id: 'resv', name: '예약' },
  { id: 'status', name: '현황' },
  { id: 'staff', name: '직원' },
  { id: 'customer', name: '고객' },
];

const rowBorder = { borderBottomWidth: 1, borderBottomStyle: 'solid' } as const;
const list = { flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' } as const;

function SummaryCards({ items, cols }: { items: { name: string; count: number; cls: string }[]; cols: number }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))`,
        gap: cols > 3 ? 6 : 8,
        padding: '16px 16px 12px',
      }}
    >
      {items.map((s) => (
        <div
          key={s.name}
          className={s.cls}
          style={{
            borderRadius: 8,
            borderWidth: 1,
            borderStyle: 'solid',
            padding: cols > 3 ? '8px 8px' : '8px 10px',
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
          }}
        >
          <span className="text-typo-caption-md-500" style={{ whiteSpace: 'nowrap' }}>
            {s.name}
          </span>
          <span className="text-typo-title-sm-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {s.count}
          </span>
        </div>
      ))}
    </div>
  );
}

// 직원의 지금 일 한 줄 — 「관리실 03 · 상담 (고객)」
export const workText = (board: Board, w: StaffWork) =>
  (w.location ? roomName(w.location, board.rooms) : '') + ' · ' + w.label + ' (' + w.customerName + ')';

export function Aside({
  board,
  now,
  tab,
  onTab,
  sel,
  selC,
  onSelStaff,
  onSelCustomer,
  onOpenRoom,
  onCheckIn,
  onWalkIn,
  narrow,
  open,
  onClose,
}: {
  board: Board;
  now: number;
  tab: TabId;
  onTab: (t: TabId) => void;
  sel: string | null;
  selC: string | null;
  onSelStaff: (id: string) => void;
  onSelCustomer: (id: string) => void;
  onOpenRoom: (id: string) => void;
  onCheckIn: (r: Reservation) => void;
  onWalkIn: () => void;
  narrow: boolean;
  open: boolean;
  onClose: () => void;
}) {
  const rn = (id: string | null) => roomName(id, board.rooms);
  return (
    <aside
      className="bg-ms-white"
      style={{
        display: 'flex',
        position: narrow ? 'fixed' : 'static',
        top: 12,
        right: 12,
        bottom: 12,
        zIndex: 41,
        transform: narrow && !open ? 'translateX(calc(100% + 24px))' : 'none',
        transition: 'transform 240ms ease',
        width: 340,
        maxWidth: 'calc(100vw - 24px)',
        flexShrink: 0,
        borderRadius: 12,
        flexDirection: 'column',
        minHeight: 0,
        boxSizing: 'border-box',
        boxShadow: '0px 0px 10px 0px rgba(0,0,0,0.09)',
      }}
    >
      {narrow && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 16px 0' }}>
          <span className="text-typo-heading-md-500 text-ms-gray-800">진행 목록</span>
          <Button variant="text" color="gray" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>
      )}
      <div style={{ padding: '8px 16px 0' }}>
        <Tabs tabs={TABS} selectedTab={tab} onSelectTab={(t: string) => onTab(t as TabId)} />
      </div>
      {tab === 'resv' && <ResvTab board={board} now={now} onCheckIn={onCheckIn} onWalkIn={onWalkIn} />}
      {tab === 'staff' && (
        <div style={list}>
          {ROLES.flatMap((role) => board.staff.filter((s) => s.role === role)).map((s) => {
            const cur = s.work.find((w) => w.state === 'in_progress');
            const next = s.work.filter((w) => w.state === 'assigned');
            return (
              <div
                key={s.staffId}
                onClick={() => onSelStaff(s.staffId)}
                className={sel === s.staffId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
                style={{ padding: '12px 16px', ...rowBorder, display: 'flex', flexDirection: 'column', gap: 8, cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: ROLE_COLOR[s.role] }} />
                  <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                    {s.name}
                  </span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                    {s.role}
                  </span>
                  <span
                    className={
                      next.length >= 2 ? 'text-typo-caption-md-600 text-red' : 'text-typo-caption-md-500 text-ms-gray-600'
                    }
                    style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}
                  >
                    {next.length ? '대기 ' + next.length + '건' : ''}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '28px minmax(0,1fr)', gap: '4px 8px', alignItems: 'baseline' }}>
                  <span className="text-typo-caption-md-500 text-ms-gray-600">지금</span>
                  <span className={cur ? 'text-typo-caption-md-400 text-ms-gray-800' : 'text-typo-caption-md-400 text-ms-gray-500'}>
                    {cur ? workText(board, cur) : '진행 중인 일 없음'}
                  </span>
                  <span className="text-typo-caption-md-500 text-primary">대기</span>
                  <span
                    className={next.length ? 'text-typo-caption-md-400 text-ms-gray-800' : 'text-typo-caption-md-400 text-ms-gray-500'}
                  >
                    {next.length ? next.map((w) => workText(board, w)).join(' → ') : '배정된 일 없음'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {tab === 'customer' && (
        <div style={list}>
          {hereCustomers(board).map((c) => {
            const k = boxKey(c.status);
            return (
              <div
                key={c.scheduleId}
                onClick={() => onSelCustomer(c.scheduleId)}
                className={selC === c.scheduleId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
                style={{ padding: '12px 16px', ...rowBorder, display: 'flex', flexDirection: 'column', gap: 8, cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    <Badge variant={STATUS[k].variant} size="sm" dot>
                      {STATUS[k].name}
                    </Badge>
                    <span
                      className="text-typo-body-600 text-ms-gray-800"
                      style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                    >
                      {c.name}
                    </span>
                  </div>
                  <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                    {rn(c.location)}
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {c.steps.map((s, i) => {
                    const v = stepNum(s.state);
                    return (
                      <div
                        key={s.stepId}
                        style={{ display: 'grid', gridTemplateColumns: '18px minmax(0,1fr) auto', gap: 8, alignItems: 'center' }}
                      >
                        <span
                          className={v.numCls}
                          style={{
                            width: 18,
                            height: 18,
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: 11,
                            fontWeight: 600,
                            boxSizing: 'border-box',
                            borderWidth: 1,
                            borderStyle: 'solid',
                          }}
                        >
                          {i + 1}
                        </span>
                        <span
                          className={v.textCls}
                          style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        >
                          {s.label}
                        </span>
                        <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                          {(s.assigneeName ? s.assigneeName + ' · ' : '') + SSTATE[s.state].name}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {tab === 'status' && <StatusTab board={board} now={now} onOpenRoom={onOpenRoom} />}
    </aside>
  );
}

function StatusTab({ board, now, onOpenRoom }: { board: Board; now: number; onOpenRoom: (id: string) => void }) {
  const counts = { wait: 0, consult: 0, treat: 0, need: 0 };
  const items = hereCustomers(board).map((c) => {
    const k = boxKey(c.status);
    counts[k]++;
    return {
      key: c.scheduleId,
      room: roomName(c.location, board.rooms),
      status: STATUS[k].name,
      variant: STATUS[k].variant,
      sec: elapsedSec(c.since, now),
      elapsed: fmtElapsed(c.since, now),
      customer: c.name,
      label: c.status?.label ?? '',
      need: c.status?.need ? 1 : 0,
      open: () => onOpenRoom(c.location as string),
    };
  });
  // 손 필요 먼저, 그다음 경과 긴 순
  items.sort((a, b) => b.need - a.need || b.sec - a.sec);
  return (
    <>
      <SummaryCards cols={4} items={KEYS.map((k) => ({ name: STATUS[k].name, count: counts[k], cls: BOX[k] }))} />
      <div className="border-ms-gray-200" style={{ borderTopWidth: 1, borderTopStyle: 'solid' }} />
      <div style={list}>
        {items.map((it) => (
          <div
            key={it.key}
            onClick={it.open}
            className="border-ms-gray-200"
            style={{ padding: '12px 16px', ...rowBorder, display: 'flex', flexDirection: 'column', gap: 6, cursor: 'pointer' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                <Badge variant={it.variant} size="sm" dot>
                  {it.status}
                </Badge>
                <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                  {it.room}
                </span>
              </div>
              <span className="text-typo-body-500 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {it.elapsed}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span className="text-typo-body-500 text-ms-gray-800">{it.customer}</span>
              <span className="text-typo-body-400 text-ms-gray-600">{it.label}</span>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

// 예약 줄 상태 — 접수 뒤 지금 위치 · 귀가 · 취소(시안 resvVals)
type RState = 'booked' | 'checked' | 'gone' | 'canceled';
const RESV_ORDER: Record<RState, number> = { booked: 0, checked: 1, gone: 2, canceled: 3 };

function ResvTab({
  board,
  now,
  onCheckIn,
  onWalkIn,
}: {
  board: Board;
  now: number;
  onCheckIn: (r: Reservation) => void;
  onWalkIn: () => void;
}) {
  const d = new Date(now);
  const nowMin = d.getHours() * 60 + d.getMinutes(); // 지연/임박 기준 = 지금 시각(시안 DEMO_NOW 자리)
  const rows = board.resv.map((r) => {
    const c = board.customers.find((x) => x.scheduleId === r.scheduleId);
    const st: RState = r.st === 'canceled' ? 'canceled' : r.st === 'booked' ? 'booked' : c && c.location ? 'checked' : 'gone';
    return { r, c, st };
  });
  rows.sort((a, b) => RESV_ORDER[a.st] - RESV_ORDER[b.st] || a.r.time.localeCompare(b.r.time));
  const n = { booked: 0, checked: 0, gone: 0, canceled: 0 };
  rows.forEach((x) => n[x.st]++);
  return (
    <>
      <SummaryCards
        cols={3}
        items={[
          { name: '예정', count: n.booked, cls: 'bg-ms-white border-primary text-ms-gray-800' },
          { name: '접수', count: n.checked, cls: 'bg-primary-100 border-primary text-ms-gray-800' },
          { name: '귀가', count: n.gone, cls: 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-600' },
        ]}
      />
      <div
        className="border-ms-gray-200"
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px 10px', ...rowBorder }}
      >
        <span className="text-typo-caption-md-400 text-ms-gray-600">오늘 예약 {board.resv.length}건</span>
        {/* 0.2.x 계약에 현장 접수(예약 없는 고객)가 없다 — 시안처럼 버튼만 두고 막아 둔다 */}
        <Button variant="outlined" color="gray" size="sm" disabled onClick={onWalkIn}>
          현장 접수
        </Button>
      </div>
      <div style={list}>
        {rows.map(({ r, c, st }) => {
          const [h, m] = r.time.split(':').map(Number);
          const diff = h * 60 + m - nowMin;
          const booked = st === 'booked';
          return (
            <div
              key={r.scheduleId}
              className="border-ms-gray-200"
              style={{
                display: 'grid',
                gridTemplateColumns: '40px minmax(0,1fr) auto',
                gap: 10,
                alignItems: 'center',
                padding: '12px 16px',
                ...rowBorder,
              }}
            >
              <span
                className={booked ? 'text-typo-caption-md-600 text-ms-gray-800' : 'text-typo-caption-md-500 text-ms-gray-500'}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {r.time}
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                  <span
                    className={booked ? 'text-typo-body-600 text-ms-gray-800' : 'text-typo-body-500 text-ms-gray-600'}
                    style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {r.name}
                  </span>
                  {r.isNew && (
                    <span
                      className="bg-primary-100 text-primary text-typo-caption-md-600"
                      style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
                    >
                      첫 방문
                    </span>
                  )}
                  <span
                    className={diff < 0 ? 'text-typo-caption-md-600 text-red' : 'text-typo-caption-md-600 text-primary'}
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    {booked ? (diff < 0 ? -diff + '분 지연' : diff <= 15 ? '곧 도착' : '') : ''}
                  </span>
                </div>
                <span
                  className="text-typo-caption-md-400 text-ms-gray-600"
                  style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  시술 {r.procedure || '-'} · 원장 {r.doctor || '-'} · {natName(r.nationality)}
                </span>
              </div>
              {booked ? (
                <Button variant="solid" color="blue" size="sm" onClick={() => onCheckIn(r)}>
                  접수
                </Button>
              ) : (
                <span
                  className={
                    st === 'checked' ? 'text-typo-caption-md-500 text-primary' : 'text-typo-caption-md-500 text-ms-gray-500'
                  }
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {st === 'canceled' ? '취소' : st === 'gone' ? '귀가' : roomName(c?.location, board.rooms)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
