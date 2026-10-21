'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button, Menu } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { BOX, KEYS, ROLES, ROLE_COLOR, STATUS, hereCustomers } from '@/lib/board';
import { useLive, useNow, useSession, useWide } from '@/lib/hooks';
import type { Board, BoardCustomer, Reservation } from '@/lib/types';
import { HEADER_H } from '@/components/common/AppHeader';
import { Aside, type TabId } from '@/components/desk/Aside';
import { CheckInModal } from '@/components/desk/CheckInModal';
import { FloorGrid, type Route } from '@/components/desk/FloorGrid';
import { DischargeModal, RoomPanel } from '@/components/desk/RoomPanel';
import { ResvDetail } from '@/components/desk/ResvDetail';
import { useDeskActions } from '@/components/desk/useDeskActions';

const PATH = '/board/live';
const icon = (d: string) => (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);
const MENUS = [
  {
    name: '현황판',
    href: '/board',
    menus: [{ name: '실시간 현황판', href: PATH, icon: icon('M3 12h4l3-8 4 16 3-8h4') }],
  },
];

// 데스크가 고른 직원 · 고객의 동선(시안 v4 activeRoute)
function activeRoute(board: Board, tab: TabId, sel: string | null, selC: string | null): Route | null {
  if (tab === 'staff' && sel) {
    const s = board.staff.find((x) => x.staffId === sel);
    if (!s) return null;
    const now = s.work.find((w) => w.state === 'in_progress');
    const next = s.work.filter((w) => w.state === 'assigned');
    const ids = [now, ...next].filter((w) => w && w.location).map((w) => w!.location as string);
    return ids.length ? { ids, cur: now ? 0 : -1 } : null;
  }
  if (tab === 'customer' && selC) {
    const c = board.customers.find((x) => x.scheduleId === selC);
    if (!c || !c.location) return null;
    if (c.location === 'reception') return { ids: ['reception'], cur: 0 };
    if (c.prevRoom) return { ids: ['reception', c.prevRoom, c.location, c.prevRoom], cur: 2 };
    return { ids: ['reception', c.location], cur: 1 };
  }
  return null;
}

export default function DeskPage() {
  const session = useSession();
  const live = useLive<Board>(session ? api.getBoard : null);
  const board = live.data;
  const now = useNow();
  const { toast, run, undo } = useDeskActions(live.reload);

  // 폰(< 760px) = 도면 · 메뉴 사이드바 없이 Aside 만 폭 전체(SPEC-002 §2). 탭 · 데스크톱은 1차 그대로
  const phone = !useWide();
  const [vw, setVw] = useState(1440);
  const [drawer, setDrawer] = useState(false);
  const [tab, setTab] = useState<TabId>('status');
  const [sel, setSel] = useState<string | null>(null);
  const [selC, setSelC] = useState<string | null>(null);
  const [rp, setRp] = useState<string | null>(null);
  // 고객 패널(SPEC-002 §5.2 D-27 · D-29 · D-30) — 방이 아니라 고객으로 연다(접수대기실 고객 · 검색 · 현황 카드)
  const [cp, setCp] = useState<string | null>(null);
  const openRoom = (id: string) => {
    setCp(null);
    setRp(id);
  };
  const openCustomer = (scheduleId: string) => {
    setRp(null);
    setCp(scheduleId);
  };
  const closePanel = () => {
    setRp(null);
    setCp(null);
  };
  const [ci, setCi] = useState<Reservation | null>(null);
  const [resetAsk, setResetAsk] = useState(false);
  const [rd, setRd] = useState<Reservation | null>(null);
  const [dc, setDc] = useState<BoardCustomer | null>(null);

  useEffect(() => {
    const on = () => setVw(document.documentElement.clientWidth);
    on();
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);

  const selectTab = useCallback(
    (id: TabId) => {
      setTab(id);
      if (!board) return;
      // 처음 여는 탭은 동선이 보이는 사람을 먼저 고른다(시안은 샘플 이름으로 고정)
      if (id === 'staff' && !sel) {
        const list = ROLES.flatMap((r) => board.staff.filter((s) => s.role === r));
        setSel((list.find((s) => s.work.length) ?? list[0])?.staffId ?? null);
      }
      if (id === 'customer' && !selC) {
        const list = hereCustomers(board);
        setSelC((list.find((c) => c.location !== 'reception') ?? list[0])?.scheduleId ?? null);
      }
    },
    [board, sel, selC],
  );

  if (!session) return null;

  const panelCust = cp && board ? (board.customers.find((c) => c.scheduleId === cp && c.location) ?? null) : null;
  const narrow = !phone && vw < 1280;
  const open = narrow && drawer;
  const itemCount = board ? hereCustomers(board).length : 0;

  const doReset = async () => {
    setResetAsk(false);
    closePanel();
    setCi(null);
    setRd(null);
    setDc(null);
    await run(() => api.resetBoard(), '시드 상태로 초기화');
  };

  return (
    <div
      data-screen-label="실시간 현황판 v4"
      style={{ display: 'flex', flexDirection: 'column', height: `calc(100vh - ${HEADER_H}px)`, background: 'var(--ms-gray-100, #f5f6f8)' }}
    >
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {!phone && <Menu menus={MENUS} currentPath={PATH} onMenuClick={(_href: string, e: React.MouseEvent) => e?.preventDefault()} />}
        <main
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            padding: phone ? '16px' : '20px 28px',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            overflow: 'hidden',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px 24px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <h1 className="text-typo-title-md-600 text-ms-gray-800" style={{ margin: 0, whiteSpace: 'nowrap' }}>
                실시간 현황판
              </h1>
              <span className="text-typo-body-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                명동점 · 1층
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px 20px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                {['고객', ...ROLES].map((name) => (
                  <span key={name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: ROLE_COLOR[name] }} />
                    <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                      {name}
                    </span>
                  </span>
                ))}
              </div>
              <span className="bg-ms-gray-300" style={{ width: 1, height: 14 }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {KEYS.map((k) => (
                  <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span
                      className={BOX[k]}
                      style={{ width: 14, height: 10, borderRadius: 3, borderWidth: 1, borderStyle: 'solid', boxSizing: 'border-box' }}
                    />
                    <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                      {STATUS[k].name}
                    </span>
                  </span>
                ))}
              </div>
              <Button variant="outlined" color="gray" size="sm" onClick={() => setResetAsk(true)}>
                초기화
              </Button>
              {narrow && (
                <Button variant="outlined" color="gray" size="sm" onClick={() => setDrawer(true)}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span>진행 목록</span>
                    <span>{itemCount}</span>
                  </span>
                </Button>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0 }}>
            {phone && !board && (
              <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>
                {live.error ?? '불러오는 중…'}
              </span>
            )}
            {!phone && (
              <div
                className="bg-ms-white"
                style={{
                  flex: 1,
                  minWidth: 0,
                  borderRadius: 12,
                  padding: 12,
                  display: 'flex',
                  overflow: 'auto',
                  boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)',
                }}
              >
                {board ? (
                  <FloorGrid board={board} now={now} route={activeRoute(board, tab, sel, selC)} onOpen={openRoom} onOpenCustomer={openCustomer} />
                ) : (
                  <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>
                    {live.error ?? '불러오는 중…'}
                  </span>
                )}
              </div>
            )}
            {open && (
              <div onClick={() => setDrawer(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.24)', zIndex: 40 }} />
            )}
            {board && (
              <Aside
                board={board}
                now={now}
                tab={tab}
                onTab={selectTab}
                sel={sel}
                selC={selC}
                onSelStaff={(id) => {
                  setSel(id);
                  setDrawer(false);
                }}
                onSelCustomer={(id) => {
                  setSelC(id);
                  setDrawer(false);
                }}
                onOpenCustomer={openCustomer}
                onCheckIn={(r) => setCi(r)}
                onOpenResv={(r) => setRd(r)}
                resvSel={rd?.scheduleId ?? null}
                narrow={narrow}
                full={phone}
                open={open}
                onClose={() => setDrawer(false)}
              />
            )}
          </div>

          {resetAsk && (
            <div
              className="bg-ms-white"
              style={{
                position: 'fixed',
                top: 84,
                right: 28,
                zIndex: 9998,
                width: 300,
                borderRadius: 12,
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                boxShadow: '0 6px 20px rgba(0,0,0,0.18)',
                ...(phone && { right: 16, maxWidth: 'calc(100vw - 32px)', boxSizing: 'border-box' }),
              }}
            >
              <span className="text-typo-body-600 text-ms-gray-800">시드 상태로 초기화할까요?</span>
              <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ wordBreak: 'keep-all' }}>
                접수 · 배정 · 시작/종료 기록이 지워져요.
              </span>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
                <Button variant="text" color="gray" size="sm" onClick={() => setResetAsk(false)}>
                  취소
                </Button>
                <Button variant="solid" color="red" size="sm" onClick={() => void doReset()}>
                  초기화
                </Button>
              </div>
            </div>
          )}

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
                padding: '10px 12px 10px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                boxShadow: '0 6px 20px rgba(0,0,0,0.18)',
              }}
            >
              <span className="text-typo-body-500" style={{ whiteSpace: 'nowrap' }}>
                {toast.text}
              </span>
              {toast.version !== null && (
                <button
                  type="button"
                  onClick={() => void undo()}
                  className="text-typo-body-600"
                  style={{ background: 'none', border: 0, color: '#7fd0ea', cursor: 'pointer', padding: '4px 6px', font: 'inherit' }}
                >
                  되돌리기
                </button>
              )}
            </div>
          )}

          {board && ci && (
            <CheckInModal
              key={ci.scheduleId}
              resv={ci}
              onClose={() => setCi(null)}
              onConfirm={(steps, memo) => {
                const t = ci;
                setCi(null);
                void run(() => api.checkIn(t.scheduleId, steps, memo), t.name + ' 접수 · 접수대기실');
              }}
            />
          )}

          {board && rd && !ci && (
            <ResvDetail
              key={rd.scheduleId}
              board={board}
              resv={board.resv.find((r) => r.scheduleId === rd.scheduleId) ?? rd}
              onClose={() => setRd(null)}
              onCheckIn={() => {
                setCi(rd);
                setRd(null);
              }}
              onNoShow={() => {
                const t = rd;
                setRd(null);
                void run(() => api.noShow(t.scheduleId), t.name + ' 노쇼');
              }}
            />
          )}

          {board && dc && (
            <DischargeModal
              board={board}
              c={board.customers.find((c) => c.scheduleId === dc.scheduleId) ?? dc}
              onCancel={() => setDc(null)}
              onConfirm={() => {
                const t = dc;
                setDc(null);
                closePanel();
                void run(() => api.discharge(t.scheduleId), t.name + ' 귀가');
              }}
            />
          )}

          {/* 귀가 모달이 떠 있는 동안 방 패널은 숨긴다 — [취소] 하면 다시 보인다(시안) */}
          {board && (rp || panelCust) && !dc && (
            <RoomPanel
              key={panelCust ? 'c:' + panelCust.scheduleId : rp}
              board={board}
              now={now}
              id={panelCust ? (panelCust.location as string) : (rp as string)}
              focus={panelCust?.scheduleId}
              onFocus={openCustomer}
              onClose={closePanel}
              onSwitch={openRoom}
              onDischarge={(c) => setDc(c)}
              run={run}
            />
          )}
        </main>
      </div>
    </div>
  );
}
