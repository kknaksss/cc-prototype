'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import * as api from '@/lib/api';
import { SSTATE, STATUS, boxKey, elapsedCls, hhmm, roomName, stateLines } from '@/lib/board';
import { Badge } from '@medisolve-ai/medikit';
import { HEADER_H } from '@/components/common/AppHeader';
import { useLive, useNow, useSession } from '@/lib/hooks';
import type { AssignedHome, AssignedItem, Role, RoundsHome, StaffAccount, StaffHome } from '@/lib/types';
import { READING_CLS, card, isForeign, natName, readingOf } from './common';
import { PatientView } from './PatientView';

const isRounds = (h: StaffHome): h is RoundsHome => h.frame === 'rounds';

// 직원 화면 틀(머리는 공통 헤더 AppHeader) — 배정형(의사 · 상담사 · 피부관리사) / 순회형(코디 · 간호사).
// 넓으면(≥760) 목록 + 상세 두 칸, 좁으면 /staff = 목록 · /staff/patient/[id] = 상세(시안 baseVals)
export function StaffShell() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const now = useNow();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(390);
  const [accounts, setAccounts] = useState<StaffAccount[]>([]);

  const staffId = session?.staffId ?? null;
  const loadHome = useCallback(() => api.getStaffHome(staffId as string), [staffId]);
  const home = useLive<StaffHome>(staffId ? loadHome : null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, [session]);

  // 동선 담당 줄의 직군(「원장 ○○」) — 직원 목록에서
  useEffect(() => {
    api
      .getStaffList()
      .then(setAccounts)
      .catch(() => undefined);
  }, []);

  // 데스크 계정은 직원 홈이 없다 — /staff 를 직접 열면 /desk 로(SPEC-002 §1, 남기는 가드)
  useEffect(() => {
    if (session && session.frame === 'desk') router.replace('/desk');
  }, [session, router]);

  if (!session) return null;

  const m = /^\/staff\/patient\/([^/]+)/.exec(pathname ?? '');
  const routeSel = m ? decodeURIComponent(m[1]) : null;
  const wide = w >= 760;
  const role = session.role as Role;
  const rounds = session.frame === 'rounds';
  const h = home.data;
  const roleOf = (id: string | null) => accounts.find((a) => a.staffId === id)?.role;

  let defaultSel: string | null = null;
  let list: React.ReactNode = null;
  const select = (id: string) => {
    router.push('/staff/patient/' + encodeURIComponent(id));
    if (!wide) window.scrollTo({ top: 0 });
  };

  if (h && isRounds(h)) {
    // 확인 필요 먼저, 그다음 경과 긴 순(시안)
    const rows = [...h.patients].sort((a, b) => Number(!!b.need) - Number(!!a.need) || (a.since ?? 0) - (b.since ?? 0));
    defaultSel = rows[0]?.scheduleId ?? null;
    list = <RoundsList home={h} rows={rows} now={now} selId={wide ? routeSel ?? defaultSel : null} onSelect={select} />;
  } else if (h) {
    const a = h as AssignedHome;
    defaultSel = (a.current ?? a.next[0] ?? a.done[0])?.scheduleId ?? null;
    list = <AssignedList home={a} now={now} selId={wide ? routeSel ?? defaultSel : null} onSelect={select} />;
  }

  const selId = routeSel ?? (wide ? defaultSel : null);
  const showList = wide || !routeSel;
  const showDetail = wide || !!routeSel;

  return (
    <div
      data-screen-label={rounds ? '직원 · 순회형' : '직원 · 배정형'}
      style={{ minHeight: `calc(100vh - ${HEADER_H}px)`, display: 'flex', justifyContent: 'center', background: '#e9ecef' }}
    >
      <div
        ref={wrapRef}
        className="bg-ms-gray-100"
        style={{
          width: '100%',
          minHeight: `calc(100vh - ${HEADER_H}px)`,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.04)',
          position: 'relative',
        }}
      >
        <div style={{ flex: 1, display: 'flex', flexDirection: wide ? 'row' : 'column', gap: 16, padding: 16, alignItems: 'flex-start' }}>
          <section
            style={{
              flex: wide ? '0 0 360px' : '0 0 auto',
              width: '100%',
              minWidth: 0,
              display: showList ? 'flex' : 'none',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            {list ?? (
              <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 4 }}>
                {home.error ?? '불러오는 중…'}
              </span>
            )}
          </section>
          <section
            style={{
              flex: wide ? '1 1 0' : '0 0 auto',
              width: '100%',
              minWidth: 0,
              display: showDetail ? 'flex' : 'none',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            {!wide && (
              <button
                type="button"
                onClick={() => {
                  router.push('/staff');
                  window.scrollTo({ top: 0 });
                }}
                className="cc-btn text-typo-body-500 text-ms-gray-700"
                style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15 18l-6-6 6-6" />
                </svg>
                {rounds ? '지금 내원 고객' : '내 일'}
              </button>
            )}
            {selId && showDetail && (
              <PatientView
                key={selId}
                scheduleId={selId}
                staffId={session.staffId}
                frame={rounds ? 'rounds' : 'assigned'}
                roleOf={roleOf}
                hideOrder={role === '상담사'}
                now={now}
                wide={wide}
                width={w}
                onChanged={home.reload}
                onPin={(id) => {
                  if (id !== routeSel) router.replace('/staff/patient/' + encodeURIComponent(id));
                }}
              />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

const rowStyle = {
  display: 'grid',
  gridTemplateColumns: '44px minmax(0,1fr) auto',
  gap: 10,
  alignItems: 'center',
  padding: '12px 16px',
  minHeight: 56,
  boxSizing: 'border-box',
  borderTopWidth: 1,
  borderTopStyle: 'solid',
  cursor: 'pointer',
} as const;

// 배정형 — 지금 진행 중 · 다음(배정 순) · 완료. 예정 없음
function AssignedList({
  home,
  now,
  selId,
  onSelect,
}: {
  home: AssignedHome;
  now: number;
  selId: string | null;
  onSelect: (id: string) => void;
}) {
  const cur = home.current;
  const curLines = cur ? stateLines(cur.status, cur.startedAt, now) : null;
  const groups: { title: string; count: string; rows: AssignedItem[]; done: boolean; emptyText: string }[] = [
    {
      title: '다음',
      count: home.next.length + '건',
      rows: home.next,
      done: false,
      emptyText: '배정된 일 없음',
    },
    { title: '완료', count: home.done.length + '건', rows: home.done, done: true, emptyText: '끝낸 일 없음' },
  ];
  return (
    <>
      {cur ? (
        <div
          onClick={() => onSelect(cur.scheduleId)}
          className="bg-primary text-ms-white"
          style={{ borderRadius: 12, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6, cursor: 'pointer' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span className="text-typo-caption-md-500" style={{ opacity: 0.9 }}>
              지금 진행 중
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-title-sm-600">{roomName(cur.location)}</span>
            <span className="text-typo-body-500">{cur.name}</span>
          </div>
          {/* 현황 두 줄(SPEC-002 §5.5) — 현재 상태 / 경과 시간. 배정형 줄에는 since 가 없어 진행 시작(startedAt)이 상태 시작이다 */}
          {curLines && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="text-typo-body-600">{curLines.state}</span>
              <span className="text-typo-caption-md-500" style={{ opacity: 0.9, fontVariantNumeric: 'tabular-nums' }}>
                {curLines.elapsed}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-ms-white border-ms-gray-300" style={{ borderRadius: 12, padding: '14px 16px', borderWidth: 1, borderStyle: 'dashed' }}>
          <span className="text-typo-body-500 text-ms-gray-600">지금 진행 중인 일이 없어요</span>
        </div>
      )}
      {groups.map((g) => (
        <div key={g.title} className="bg-ms-white" style={{ borderRadius: 12, display: 'flex', flexDirection: 'column', ...card, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px 10px' }}>
            <span className="text-typo-heading-md-500 text-ms-gray-800">{g.title}</span>
            <span className="text-typo-caption-md-400 text-ms-gray-600">{g.count}</span>
          </div>
          {g.rows.map((x) => {
            const ss = SSTATE[x.state];
            return (
              <div
                key={x.stepId}
                onClick={() => onSelect(x.scheduleId)}
                className={x.scheduleId === selId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
                style={rowStyle}
              >
                <span
                  className={g.done ? 'text-typo-caption-md-500 text-ms-gray-500' : 'text-typo-caption-md-600 text-ms-gray-800'}
                  style={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {g.done ? hhmm(x.endedAt) : hhmm(x.assignedAt)}
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                  <span
                    className={g.done ? 'text-typo-body-500 text-ms-gray-500' : 'text-typo-body-600 text-ms-gray-800'}
                    style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {x.name}
                    {readingOf(x.nationality, x.phoneticName) && <span className={READING_CLS}> {readingOf(x.nationality, x.phoneticName)}</span>}{' '}
                    <span className="text-typo-caption-md-400 text-ms-gray-600">{roomName(x.location)}</span>
                  </span>
                  <span
                    className="text-typo-caption-md-400 text-ms-gray-600"
                    style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {x.label}
                  </span>
                </div>
                <Badge variant={ss.variant} size="sm" dot={ss.dot}>
                  {ss.name}
                </Badge>
              </div>
            );
          })}
          {!g.rows.length && (
            <span
              className="text-typo-body-400 text-ms-gray-500 border-ms-gray-200"
              style={{ padding: '12px 16px 14px', borderTopWidth: 1, borderTopStyle: 'solid' }}
            >
              {g.emptyText}
            </span>
          )}
        </div>
      ))}
    </>
  );
}

// 순회형 — 지금 내원 고객 · 확인 필요 · 오늘 시술
function RoundsList({
  home,
  rows,
  now,
  selId,
  onSelect,
}: {
  home: RoundsHome;
  rows: RoundsHome['patients'];
  now: number;
  selId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="bg-ms-white" style={{ borderRadius: 12, display: 'flex', flexDirection: 'column', ...card, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '14px 16px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className="text-typo-heading-md-500 text-ms-gray-800">지금 내원 고객</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {rows.length}명 · 외국인 {rows.filter((p) => isForeign(p.nationality)).length}명
          </span>
        </div>
        <span className="text-typo-caption-md-400 text-ms-gray-600">
          확인 필요 {home.summary.needNext + home.summary.needDischarge}
        </span>
      </div>
      {rows.map((p) => {
        const k = boxKey(p.status);
        const sl = stateLines(p.status, p.since, now);
        const procs = p.procedures;
        return (
          <div
            key={p.scheduleId}
            onClick={() => onSelect(p.scheduleId)}
            className={p.scheduleId === selId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0,1fr) auto',
              gap: 10,
              alignItems: 'start',
              padding: '12px 16px',
              boxSizing: 'border-box',
              borderTopWidth: 1,
              borderTopStyle: 'solid',
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, flexWrap: 'wrap' }}>
                <span
                  className="text-typo-body-600 text-ms-gray-800"
                  style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {p.name}
                </span>
                {readingOf(p.nationality, p.phoneticName) && (
                  <span className={READING_CLS} style={{ whiteSpace: 'nowrap' }}>
                    {readingOf(p.nationality, p.phoneticName)}
                  </span>
                )}
                {isForeign(p.nationality) && (
                  <span
                    className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700"
                    style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
                  >
                    {natName(p.nationality)}
                  </span>
                )}
                {p.need && (
                  <span
                    className="bg-red-100 text-red text-typo-caption-md-600"
                    style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
                  >
                    확인 필요 · {p.status?.label}
                  </span>
                )}
              </div>
              {/* 현황 두 줄(SPEC-002 §5.5) — 방 · 현재 상태 / 경과 시간(오래 기다림 빨강) */}
              <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ overflowWrap: 'anywhere' }}>
                <b className="text-primary" style={{ fontWeight: 600 }}>
                  {roomName(p.location)}
                </b>{' '}
                · {sl?.state}
              </span>
              {sl && (
                <span className={elapsedCls(sl.long, 'text-typo-caption-md-500 text-ms-gray-700')} style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {sl.elapsed}
                </span>
              )}
              <span className="text-typo-caption-md-400 text-ms-gray-700" style={{ overflowWrap: 'anywhere' }}>
                오늘 시술 ·{' '}
                {procs.length
                  ? procs
                      .map((s) => s.label + (s.state === 'done' ? ' ✓' : s.state === 'in_progress' ? ' (진행 중)' : ''))
                      .join(' · ')
                  : '아직 없음'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
              <Badge variant={STATUS[k].variant} size="sm" dot>
                {STATUS[k].name}
              </Badge>
            </div>
          </div>
        );
      })}
    </div>
  );
}
