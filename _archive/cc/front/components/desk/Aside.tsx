'use client';

import { useState } from 'react';
import { Badge, Button, Tabs } from '@medisolve-ai/medikit';
import { BOX, KEYS, ROLES, ROLE_COLOR, RTITLE, SSTATE, STATUS, boxKey, elapsedCls, hereCustomers, roomName, stateLines, stepNum } from '@/lib/board';
import { elapsedSec, fmtElapsed } from '@/lib/time';
import type { Board, BoardCustomer, Reservation, StaffWork } from '@/lib/types';
import { READING_CLS, isForeign, natName, readingOf } from '@/components/staff/common';

export type TabId = 'resv' | 'status' | 'staff' | 'customer';
const TABS = [
  { id: 'resv', name: '예약' },
  { id: 'status', name: '현황' },
  { id: 'staff', name: '직원' },
  { id: 'customer', name: '고객' },
];

const rowBorder = { borderBottomWidth: 1, borderBottomStyle: 'solid' } as const;
const list = { flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' } as const;

function SummaryCards({
  items,
  cols,
  active,
  onPick,
}: {
  items: { key?: string; name: string; count: number; cls: string }[];
  cols: number;
  active?: string | null;
  onPick?: (key: string) => void;
}) {
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
          onClick={onPick && s.key ? () => onPick(s.key as string) : undefined}
          style={{
            cursor: onPick ? 'pointer' : undefined,
            outline: active && active === s.key ? '2px solid var(--ms-primary)' : 'none',
            outlineOffset: -1,
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
  onOpenCustomer,
  onCheckIn,
  onOpenResv,
  resvSel,
  narrow,
  open,
  onClose,
  full = false,
}: {
  board: Board;
  now: number;
  tab: TabId;
  onTab: (t: TabId) => void;
  sel: string | null;
  selC: string | null;
  onSelStaff: (id: string) => void;
  onSelCustomer: (id: string) => void;
  // 고객 패널(원내 고객 — scheduleId)
  onOpenCustomer: (scheduleId: string) => void;
  onCheckIn: (r: Reservation) => void;
  onOpenResv: (r: Reservation) => void;
  resvSel: string | null;
  narrow: boolean;
  open: boolean;
  onClose: () => void;
  // 폰 현황판(SPEC-002 §2) — 도면 없이 이 패널만 폭 전체로
  full?: boolean;
}) {
  const rn = (id: string | null) => roomName(id, board.rooms);
  const [q, setQ] = useState('');
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
        // 폰은 서랍이 아니라 본문 — 서랍용 zIndex 41 을 끄고 공통 헤더(30) · 햄버거 메뉴 아래로
        ...(full && { flex: 1, width: '100%', maxWidth: 'none', zIndex: 'auto' }),
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
      {/* 고객 검색(SPEC-002 §5.2 D-29) — 영문 이름 · 한글 읽기 · 전화번호, 오늘 예약 + 원내 고객 */}
      <div style={{ padding: '12px 16px 0' }}>
        <input
          className="cc-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="고객 검색 — 영문 이름 · 한글 읽기 · 전화번호"
          style={{ height: 40, fontSize: 14 }}
        />
      </div>
      {q.trim() ? (
        <SearchResults
          board={board}
          q={q}
          onOpenCustomer={(id) => {
            setQ('');
            onOpenCustomer(id);
          }}
          onOpenResv={(r) => {
            setQ('');
            onOpenResv(r);
          }}
        />
      ) : (
        <>
          <div style={{ padding: '8px 16px 0' }}>
            <Tabs tabs={TABS} selectedTab={tab} onSelectTab={(t: string) => onTab(t as TabId)} />
          </div>
          {tab === 'resv' && <ResvTab board={board} now={now} sel={resvSel} onOpen={onOpenResv} onCheckIn={onCheckIn} />}
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
          {tab === 'status' && <StatusTab board={board} now={now} onOpen={onOpenCustomer} />}
        </>
      )}
    </aside>
  );
}

// 현황 탭(SPEC-002 §5.2 D-30) — 원내 고객 카드: 상태 · 방 · 담당 · 대기 시간 · VIP. 오래 기다린 순, 누르면 고객 패널
function StatusTab({ board, now, onOpen }: { board: Board; now: number; onOpen: (scheduleId: string) => void }) {
  const counts = { wait: 0, consult: 0, treat: 0, need: 0 };
  const items = hereCustomers(board).map((c) => {
    const k = boxKey(c.status);
    counts[k]++;
    return { c, k, sec: elapsedSec(c.since, now) };
  });
  items.sort((a, b) => b.sec - a.sec);
  return (
    <>
      <SummaryCards cols={4} items={KEYS.map((k) => ({ name: STATUS[k].name, count: counts[k], cls: BOX[k] }))} />
      <div className="border-ms-gray-200" style={{ borderTopWidth: 1, borderTopStyle: 'solid' }} />
      <div style={{ ...list, gap: 8, padding: '12px 16px' }}>
        {items.map(({ c, k }) => {
          const reading = readingOf(c.nationality, c.phoneticName);
          const sl = stateLines(c.status, c.since, now);
          return (
            <div
              key={c.scheduleId}
              onClick={() => onOpen(c.scheduleId)}
              className="bg-ms-white border-ms-gray-200"
              style={{
                borderWidth: 1,
                borderStyle: 'solid',
                borderRadius: 10,
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                cursor: 'pointer',
                flexShrink: 0,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <Badge variant={STATUS[k].variant} size="sm" dot>
                    {STATUS[k].name}
                  </Badge>
                  <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                    {roomName(c.location, board.rooms)}
                  </span>
                </div>
                <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                  {ownerOf(board, c)}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <span className="text-typo-body-500 text-ms-gray-800">{c.name}</span>
                {reading && <span className={READING_CLS}>{reading}</span>}
                {c.vip && <VipChip />}
              </div>
              {/* 현황 두 줄(SPEC-002 §5.5) — 현재 상태 / 경과 시간(오래 기다림 빨강) */}
              {sl && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span className="text-typo-body-500 text-ms-gray-800">{sl.state}</span>
                  <span className={elapsedCls(sl.long)} style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {sl.elapsed}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// 담당 — 진행 중 단계의 담당, 없으면 다음 배정 단계의 담당
function ownerOf(board: Board, c: BoardCustomer): string {
  const s = c.steps.find((x) => x.state === 'in_progress') ?? c.steps.find((x) => x.state === 'assigned');
  if (!s || !s.assigneeName) return '미배정';
  const role = board.staff.find((x) => x.staffId === s.assigneeId)?.role;
  return (role ? RTITLE[role] + ' ' : '') + s.assigneeName;
}

// VIP 칩 — 변경 목업 .vip 색
export function VipChip() {
  return (
    <span
      className="text-typo-caption-md-600"
      style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap', color: '#8a5a00', background: '#fff3cf', border: '1px solid #f0d27a' }}
    >
      VIP
    </span>
  );
}

// 고객 검색 결과 — 원내 고객 = 고객 패널, 그 밖(미접수 · 귀가 · 노쇼) = 예약 상세
function SearchResults({
  board,
  q,
  onOpenCustomer,
  onOpenResv,
}: {
  board: Board;
  q: string;
  onOpenCustomer: (scheduleId: string) => void;
  onOpenResv: (r: Reservation) => void;
}) {
  const text = q.trim().toLowerCase().replace(/\s+/g, '');
  const digits = q.replace(/\D/g, '');
  const hit = (name: string, reading: string | null, phone: string | null) =>
    name.toLowerCase().replace(/\s+/g, '').includes(text) ||
    (!!reading && reading.replace(/\s+/g, '').includes(text)) ||
    (digits.length > 0 && !!phone && phone.replace(/\D/g, '').includes(digits));
  type Hit = { id: string; name: string; reading: string | null; nat: string; isNew: boolean; vip: boolean; where: string; open: () => void };
  const out: Hit[] = [];
  const here = hereCustomers(board);
  here.forEach((c) => {
    if (hit(c.name, c.phoneticName, c.phone))
      out.push({
        id: c.scheduleId,
        name: c.name,
        reading: c.phoneticName,
        nat: c.nationality,
        isNew: c.isNew,
        vip: c.vip,
        where: roomName(c.location, board.rooms),
        open: () => onOpenCustomer(c.scheduleId),
      });
  });
  board.resv.forEach((r) => {
    if (here.some((c) => c.scheduleId === r.scheduleId) || !hit(r.name, r.phoneticName, r.phone)) return;
    const gone = board.customers.find((c) => c.scheduleId === r.scheduleId)?.flowStep === 'COMPLETED';
    out.push({
      id: r.scheduleId,
      name: r.name,
      reading: r.phoneticName,
      nat: r.nationality,
      isNew: r.isNew,
      vip: r.vip,
      where: r.time + ' ' + (r.st === 'noshow' ? '노쇼' : gone ? '귀가' : '예약'),
      open: () => onOpenResv(r),
    });
  });
  return (
    <div style={{ ...list, paddingTop: 8 }}>
      {out.map((h) => {
        const reading = readingOf(h.nat, h.reading);
        return (
          <div
            key={h.id}
            onClick={h.open}
            className="bg-ms-white border-ms-gray-200"
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0,1fr) auto',
              gap: 10,
              alignItems: 'center',
              minHeight: 52,
              boxSizing: 'border-box',
              padding: '8px 16px',
              ...rowBorder,
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, flexWrap: 'wrap' }}>
              <span className="text-typo-body-600 text-ms-gray-800">{h.name}</span>
              {reading && <span className={READING_CLS}>{reading}</span>}
              <VisitChip isNew={h.isNew} />
              {h.vip && <VipChip />}
            </div>
            <span className="text-typo-caption-md-500 text-ms-gray-600" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
              {h.where}
            </span>
          </div>
        );
      })}
      {!out.length && (
        <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 16 }}>
          검색 결과 없음
        </span>
      )}
    </div>
  );
}

// 예약 탭(SPEC-002 §5.3 · §5.4 · D-34) — 칸 = 전체 · 접수 전 · 지연 · 귀가. 「전체」(오늘 예약 수)가 처음 선택, 다른 칸은 그 상태만.
// 노쇼는 칸 없이 목록 맨 아래 흐리게. 원내 고객은 현황 탭
type RState = 'booked' | 'late' | 'gone' | 'noshow';
type RFilter = 'all' | 'booked' | 'late' | 'gone';
const RESV_ORDER: Record<RState, number> = { late: 0, booked: 0, gone: 1, noshow: 2 };

function ResvTab({
  board,
  now,
  sel,
  onOpen,
  onCheckIn,
}: {
  board: Board;
  now: number;
  sel: string | null;
  onOpen: (r: Reservation) => void;
  onCheckIn: (r: Reservation) => void;
}) {
  const [filter, setFilter] = useState<RFilter>('all');
  const d = new Date(now);
  const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  // 예약 시각(오늘 HH:MM) → ms — 지연 표시(D-28 형식)
  const atMs = (t: string) => {
    const [h, m] = t.split(':').map(Number);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, m).getTime();
  };
  const all = board.resv
    .map((r) => {
      const c = board.customers.find((x) => x.scheduleId === r.scheduleId);
      const st: RState | null =
        r.st === 'booked'
          ? r.time < hm
            ? 'late'
            : 'booked'
          : r.st === 'noshow'
            ? 'noshow'
            : r.st === 'checked' && c?.flowStep === 'COMPLETED'
              ? 'gone'
              : null;
      return { r, st };
    })
    .filter((x): x is { r: Reservation; st: RState } => x.st !== null);
  all.sort((a, b) => RESV_ORDER[a.st] - RESV_ORDER[b.st] || a.r.time.localeCompare(b.r.time));
  const n = { booked: 0, late: 0, gone: 0, noshow: 0 };
  all.forEach((x) => n[x.st]++);
  const rows = filter === 'all' ? all : all.filter((x) => x.st === filter);
  return (
    <>
      <SummaryCards
        cols={4}
        active={filter}
        onPick={(k) => setFilter(k as RFilter)}
        items={[
          { key: 'all', name: '전체', count: board.resv.length, cls: 'bg-ms-white border-ms-gray-300 text-ms-gray-800' },
          { key: 'booked', name: '접수 전', count: n.booked, cls: 'bg-ms-white border-ms-gray-300 text-ms-gray-800' },
          { key: 'late', name: '지연', count: n.late, cls: 'bg-ms-white border-ms-gray-300 text-red' },
          { key: 'gone', name: '귀가', count: n.gone, cls: 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-600' },
        ]}
      />
      <div className="border-ms-gray-200" style={{ borderTopWidth: 1, borderTopStyle: 'solid' }} />
      <div style={list}>
        {rows.map(({ r, st }) => {
          const open = st === 'booked' || st === 'late';
          const reading = readingOf(r.nationality, r.phoneticName);
          const late = st === 'late' ? fmtElapsed(atMs(r.time), now) + ' 지연' : '';
          return (
            <div
              key={r.scheduleId}
              data-resv={r.scheduleId}
              onClick={() => onOpen(r)}
              className={sel === r.scheduleId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
              style={{
                display: 'grid',
                gridTemplateColumns: 'auto minmax(0,1fr) auto',
                gap: 10,
                alignItems: 'center',
                minHeight: 52,
                boxSizing: 'border-box',
                padding: '8px 16px',
                ...rowBorder,
                cursor: 'pointer',
                opacity: st === 'noshow' ? 0.55 : 1,
              }}
            >
              {/* 왼쪽 칸 = 시각 / 그 아래 첫내원 · 재내원 뱃지(SPEC-002 §5.4) */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 4, alignSelf: 'start' }}>
                <span
                  className={open ? 'text-typo-caption-md-600 text-ms-gray-800' : 'text-typo-caption-md-500 text-ms-gray-500'}
                  style={{ fontVariantNumeric: 'tabular-nums', paddingTop: 3 }}
                >
                  {r.time}
                </span>
                <VisitChip isNew={r.isNew} />
              </div>
              {/* 오른쪽 두 줄 — 1줄 영문 이름 · 국적 칩(1차 직원 화면 규칙) · VIP(이름은 자르지 않는다) / 2줄 한글 읽기 · 지연 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', minWidth: 0 }}>
                  <span
                    className={open ? 'text-typo-body-600 text-ms-gray-800' : 'text-typo-body-500 text-ms-gray-600'}
                    style={{ overflowWrap: 'anywhere' }}
                  >
                    {r.name}
                  </span>
                  {isForeign(r.nationality) && (
                    <span
                      className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700"
                      style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
                    >
                      {natName(r.nationality)}
                    </span>
                  )}
                  {r.vip && <VipChip />}
                </div>
                {(reading || late) && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {reading && <span className={READING_CLS}>{reading}</span>}
                    {late && (
                      <span className="text-typo-caption-md-600 text-red" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                        {late}
                      </span>
                    )}
                  </div>
                )}
              </div>
              {open ? (
                <span onClick={(e) => e.stopPropagation()}>
                  <Button variant="solid" color="blue" size="sm" onClick={() => onCheckIn(r)}>
                    접수
                  </Button>
                </span>
              ) : (
                <span className="text-typo-caption-md-500 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                  {st === 'noshow' ? '노쇼' : '귀가'}
                </span>
              )}
            </div>
          );
        })}
        {!rows.length && (
          <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 16 }}>
            예약 없음
          </span>
        )}
      </div>
    </>
  );
}

export function VisitChip({ isNew }: { isNew: boolean }) {
  return (
    <span
      className={
        isNew ? 'bg-primary-100 text-primary text-typo-caption-md-600' : 'bg-ms-gray-200 text-ms-gray-700 text-typo-caption-md-600'
      }
      style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
    >
      {isNew ? '첫내원' : '재내원'}
    </span>
  );
}
