'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Header, Menu } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { KEYS, LAYOUT, ROLE_DOT, ROLE_ORDER, STATUS, custIn, statusOf } from '@/lib/board';
import { useLive, useNow, useSession } from '@/lib/hooks';
import { clearSession } from '@/lib/session';
import type { Board, Reservation } from '@/lib/types';
import { Aside, type TabId } from '@/components/desk/Aside';
import { CheckInModal, type CheckInTarget } from '@/components/desk/CheckInModal';
import { FloorGrid, type Route } from '@/components/desk/FloorGrid';
import { RoomPanel } from '@/components/desk/RoomPanel';
import { clearPatientInfo, usePatientInfo } from '@/components/desk/usePatientInfo';
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

// 데스크가 고른 직원 · 고객의 동선(시안 activeRoute)
function activeRoute(board: Board, tab: TabId, sel: string | null, selC: string | null): Route | null {
  if (tab === 'staff' && sel) {
    const s = board.staff.find((x) => x.staffId === sel);
    if (!s) return null;
    const ids = s.queue.length ? [...s.queue] : s.home && s.home !== 'office' ? [s.home] : [];
    return ids.length ? { ids, cur: 0 } : null;
  }
  if (tab === 'customer' && selC) {
    const c = board.customers.find((x) => x.scheduleId === selC);
    if (!c || c.done || !c.room) return null;
    if (c.room === 'lounge') return { ids: ['lounge'], cur: 0 };
    if (c.prev) return { ids: ['lounge', c.prev, c.room, c.prev], cur: 2 };
    return { ids: ['lounge', c.room], cur: 1 };
  }
  return null;
}

export default function DeskPage() {
  const session = useSession();
  const router = useRouter();
  const live = useLive<Board>(session ? api.getBoard : null);
  const board = live.data;
  const now = useNow();
  const { toast, run, undo } = useDeskActions(live.reload);

  const [vw, setVw] = useState(1440);
  const [drawer, setDrawer] = useState(false);
  const [tab, setTab] = useState<TabId>('status');
  const [sel, setSel] = useState<string | null>(null);
  const [selC, setSelC] = useState<string | null>(null);
  const [rp, setRp] = useState<string | null>(null);
  const [ci, setCi] = useState<CheckInTarget | null>(null);
  const ciInfo = usePatientInfo(ci?.scheduleId ? [ci.scheduleId] : []);

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
        const list = ROLE_ORDER.flatMap((r) => board.staff.filter((s) => s.role === r));
        setSel((list.find((s) => s.queue.length) ?? list[0])?.staffId ?? null);
      }
      if (id === 'customer' && !selC) {
        const list = board.customers.filter((c) => !c.done);
        setSelC((list.find((c) => c.room && c.room !== 'lounge') ?? list[0])?.scheduleId ?? null);
      }
    },
    [board, sel, selC],
  );

  if (!session) return null;

  const narrow = vw < 1280;
  const open = narrow && drawer;

  // 진행 목록 건수 = 상태가 있는 방 + 라운지 대기(시안 items)
  const itemCount = board
    ? LAYOUT.filter((d) => statusOf(board, d.id)).length + custIn(board, 'lounge').length
    : 0;

  const reset = async () => {
    if (!window.confirm('현황판을 시드 상태로 되돌릴까요?')) return;
    clearPatientInfo();
    setRp(null);
    setCi(null);
    await run(() => api.resetBoard(), null);
  };

  const openCheckIn = (r: Reservation) =>
    setCi({ scheduleId: r.scheduleId, name: r.name, time: r.time, procedure: r.procedure, doctor: r.doctor });
  const walkIn = () => {
    const n = board ? board.resv.filter((r) => r.procedure === '현장 접수').length + 1 : 1;
    setCi({ scheduleId: null, name: '현장 고객 ' + n, time: '', procedure: '현장 접수', doctor: '미정' });
  };

  return (
    <div
      data-screen-label="실시간 현황판 v3"
      style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--ms-gray-100, #f5f6f8)' }}
    >
      <Header
        logo={
          // eslint-disable-next-line @next/next/no-img-element
          <img src="/ceramique-logo-color.svg" alt="CÉRAMIQUE" style={{ height: 22, display: 'block' }} />
        }
        menus={MENUS}
        currentPath={PATH}
        onMenuClick={(_href: string, e: React.MouseEvent) => e?.preventDefault()}
        branchName="세라미크 명동점"
        userName="관리자"
        onLogout={() => {
          clearSession();
          router.replace('/login');
        }}
      />
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <Menu menus={MENUS} currentPath={PATH} onMenuClick={(_href: string, e: React.MouseEvent) => e?.preventDefault()} />
        <main
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            padding: '20px 28px',
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
                명동점 · 1층 · 방을 눌러 배정
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px 20px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {Object.keys(ROLE_DOT).map((name) => (
                  <span key={name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className={ROLE_DOT[name]} style={{ width: 8, height: 8, borderRadius: '50%' }} />
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
                      className={STATUS[k].cls}
                      style={{ width: 14, height: 10, borderRadius: 3, borderWidth: 1, borderStyle: 'solid', boxSizing: 'border-box' }}
                    />
                    <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                      {STATUS[k].name}
                    </span>
                  </span>
                ))}
              </div>
              {narrow && (
                <Button variant="outlined" color="gray" size="sm" onClick={() => setDrawer(true)}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span>진행 목록</span>
                    <span>{itemCount}</span>
                  </span>
                </Button>
              )}
              {/* SPEC §5.4 — 시안에 없는 유일한 추가 요소 */}
              <Button variant="outlined" color="gray" size="sm" onClick={() => void reset()}>
                초기화
              </Button>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0 }}>
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
                <FloorGrid
                  board={board}
                  now={now}
                  route={activeRoute(board, tab, sel, selC)}
                  onOpen={(id) => setRp(id)}
                />
              ) : (
                <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>
                  {live.error ?? '불러오는 중…'}
                </span>
              )}
            </div>
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
                onOpenRoom={(id) => setRp(id)}
                onCheckIn={openCheckIn}
                onWalkIn={walkIn}
                narrow={narrow}
                open={open}
                onClose={() => setDrawer(false)}
              />
            )}
          </div>

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
              key={ci.scheduleId ?? ci.name}
              target={ci}
              info={ci.scheduleId ? ciInfo[ci.scheduleId] : undefined}
              onClose={() => setCi(null)}
              onConfirm={(order) => {
                const t = ci;
                setCi(null);
                void run(() => api.checkIn(t.scheduleId, order, t.name), t.name + ' 접수 · 라운지 대기');
              }}
            />
          )}

          {board && rp && <RoomPanel key={rp} board={board} now={now} id={rp} onClose={() => setRp(null)} run={run} />}
        </main>
      </div>
    </div>
  );
}
