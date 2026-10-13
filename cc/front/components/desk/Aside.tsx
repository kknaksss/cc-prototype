'use client';

import { Badge, Button, Tabs } from '@medisolve-ai/medikit';
import { KEYS, LAYOUT, RLABEL, ROLE_DOT, ROLE_ORDER, STATUS, custIn, presentIn, roomName, statusOf, stepView, taskAt } from '@/lib/board';
import { elapsedSec, fmtElapsed } from '@/lib/time';
import type { Board, Reservation, ResvState } from '@/lib/types';

export type TabId = 'resv' | 'status' | 'staff' | 'customer';
const TABS = [
  { id: 'resv', name: '예약' },
  { id: 'status', name: '현황' },
  { id: 'staff', name: '직원' },
  { id: 'customer', name: '고객' },
];

const rowBorder = { borderBottomWidth: 1, borderBottomStyle: 'solid' } as const;

function SummaryCards({ items }: { items: { name: string; count: number; cls: string }[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 8, padding: '16px 16px 12px' }}>
      {items.map((s) => (
        <div
          key={s.name}
          className={s.cls}
          style={{
            borderRadius: 8,
            borderWidth: 1,
            borderStyle: 'solid',
            padding: '8px 10px',
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
          }}
        >
          <span className="text-typo-caption-md-500">{s.name}</span>
          <span className="text-typo-title-sm-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {s.count}
          </span>
        </div>
      ))}
    </div>
  );
}


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
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {ROLE_ORDER.flatMap((role) => board.staff.filter((s) => s.role === role)).map((s) => {
            const cur = s.queue[0];
            const rest = s.queue.slice(1);
            return (
              <div
                key={s.staffId}
                onClick={() => onSelStaff(s.staffId)}
                className={sel === s.staffId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
                style={{ padding: '12px 16px', ...rowBorder, display: 'flex', flexDirection: 'column', gap: 8, cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className={ROLE_DOT[s.role]} style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0 }} />
                  <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                    {s.name}
                  </span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                    {RLABEL[s.role]}
                  </span>
                  <span
                    className={
                      rest.length >= 2
                        ? 'text-typo-caption-md-600 text-red'
                        : 'text-typo-caption-md-500 text-ms-gray-600'
                    }
                    style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}
                  >
                    {rest.length ? '대기 ' + rest.length + '건' : ''}
                  </span>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '28px minmax(0,1fr)',
                    gap: '4px 8px',
                    alignItems: 'baseline',
                  }}
                >
                  <span className="text-typo-caption-md-500 text-ms-gray-600">현재</span>
                  <span
                    className={
                      cur ? 'text-typo-caption-md-400 text-ms-gray-800' : 'text-typo-caption-md-400 text-primary'
                    }
                  >
                    <b style={{ fontWeight: 600 }}>{cur ? rn(cur) : '비어있음'}</b>
                    {cur ? taskAt(board, cur) : ' · ' + rn(s.home)}
                  </span>
                  <span className="text-typo-caption-md-500 text-primary">다음</span>
                  <span
                    className={
                      rest.length
                        ? 'text-typo-caption-md-400 text-ms-gray-800'
                        : 'text-typo-caption-md-400 text-ms-gray-500'
                    }
                  >
                    {rest.length ? rest.map((id) => rn(id) + taskAt(board, id)).join(' → ') : '다음 일정 없음'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {tab === 'customer' && (
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {board.customers
            .filter((c) => !c.done)
            .map((c) => {
              const st =
                c.room === 'lounge' || !c.room ? { key: 'wait' as const } : statusOf(board, c.room) || { key: 'wait' as const };
              return (
                <div
                  key={c.scheduleId}
                  onClick={() => onSelCustomer(c.scheduleId)}
                  className={
                    selC === c.scheduleId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'
                  }
                  style={{ padding: '12px 16px', ...rowBorder, display: 'flex', flexDirection: 'column', gap: 8, cursor: 'pointer' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                      <Badge variant={STATUS[st.key].variant} size="sm" dot>
                        {STATUS[st.key].name}
                      </Badge>
                      <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                        {c.name}
                      </span>
                    </div>
                    <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                      {rn(c.room)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {c.order.map((s, i) => {
                      const v = stepView(s, i, c.step);
                      return (
                        <div
                          key={i}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: '18px minmax(0,1fr) auto',
                            gap: 8,
                            alignItems: 'center',
                          }}
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
                            {v.n}
                          </span>
                          <span className={v.textCls} style={{ minWidth: 0 }}>
                            {v.label}
                          </span>
                          <span className="text-typo-caption-md-400 text-ms-gray-500">{v.role}</span>
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
  const counts = { wait: 0, consult: 0, treat: 0 };
  const items: {
    key: string;
    room: string;
    status: string;
    variant: 'neutral' | 'purple' | 'primary';
    sec: number;
    elapsed: string;
    customer: string;
    label: string;
    open: () => void;
    staff: { key: string; role: string; name: string; cls: string }[];
  }[] = [];
  LAYOUT.forEach((d) => {
    const st = statusOf(board, d.id);
    if (!st) return;
    const cs = custIn(board, d.id);
    counts[st.key]++;
    items.push({
      key: d.id,
      room: roomName(d.id, board.rooms),
      status: STATUS[st.key].name,
      variant: STATUS[st.key].variant,
      sec: elapsedSec(cs[0].since, now),
      elapsed: fmtElapsed(cs[0].since, now),
      customer: cs.map((c) => c.name).join(', '),
      label: st.label,
      open: () => onOpenRoom(d.id),
      staff: presentIn(board, d.id).map((s) => ({ key: s.staffId, role: RLABEL[s.role], name: s.name, cls: ROLE_DOT[s.role] })),
    });
  });
  custIn(board, 'lounge').forEach((c) => {
    counts.wait++;
    items.push({
      key: 'lounge-' + c.scheduleId,
      room: '라운지',
      status: '대기',
      variant: 'neutral',
      sec: elapsedSec(c.since, now),
      elapsed: fmtElapsed(c.since, now),
      customer: c.name,
      label: '접수 후 대기 · 관리실 배정 필요',
      open: () => onOpenRoom('lounge'),
      staff: [],
    });
  });
  items.sort((a, b) => b.sec - a.sec);
  return (
    <>
      <SummaryCards items={KEYS.map((k) => ({ name: STATUS[k].name, count: counts[k], cls: STATUS[k].cls }))} />
      <div className="border-ms-gray-200" style={{ borderTopWidth: 1, borderTopStyle: 'solid' }} />
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px 10px', flexWrap: 'wrap' }}>
              {it.staff.map((m) => (
                <span key={m.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span className={m.cls} style={{ width: 8, height: 8, borderRadius: '50%' }} />
                  <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                    {m.role} {m.name}
                  </span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

const RESV_ORDER: Record<ResvState, number> = { booked: 0, noshow: 1, canceled: 2, checked: 3 };

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
  const nowMin = d.getHours() * 60 + d.getMinutes(); // 예약 지연/임박 판단 기준(시안 DEMO_NOW → 지금 시각)
  const list = [...board.resv].sort((a, b) => RESV_ORDER[a.st] - RESV_ORDER[b.st] || a.time.localeCompare(b.time));
  const n = { booked: 0, checked: 0, noshow: 0, canceled: 0 };
  board.resv.forEach((r) => n[r.st]++);
  return (
    <>
      <SummaryCards
        items={[
          { name: '예정', count: n.booked, cls: 'bg-ms-white border-primary text-ms-gray-800' },
          { name: '접수', count: n.checked, cls: 'bg-primary-100 border-primary text-ms-gray-800' },
          { name: '노쇼', count: n.noshow, cls: 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-600' },
        ]}
      />
      <div
        className="border-ms-gray-200"
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px 10px', ...rowBorder }}
      >
        <span className="text-typo-caption-md-400 text-ms-gray-600">오늘 예약 {board.resv.length}건</span>
        <Button variant="outlined" color="gray" size="sm" onClick={onWalkIn}>
          현장 접수
        </Button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        {list.map((r, i) => {
          const [h, m] = r.time.split(':').map(Number);
          const diff = h * 60 + m - nowMin;
          const booked = r.st === 'booked';
          const c =
            r.st === 'checked' ? board.customers.find((x) => x.scheduleId === r.scheduleId) : undefined;
          const gone = r.st === 'noshow' || r.st === 'canceled' || !c || c.done;
          const stateText =
            r.st === 'noshow' ? '노쇼' : r.st === 'canceled' ? '취소' : !c || c.done ? '귀가' : roomName(c.room, board.rooms);
          return (
            <div
              key={(r.scheduleId ?? 'w') + i}
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
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    {r.name}
                  </span>
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
                  {r.procedure} · {r.doctor}
                </span>
              </div>
              {booked ? (
                <Button variant="solid" color="blue" size="sm" onClick={() => onCheckIn(r)}>
                  접수
                </Button>
              ) : (
                <span
                  className={gone ? 'text-typo-caption-md-500 text-ms-gray-500' : 'text-typo-caption-md-500 text-primary'}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {stateText}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
