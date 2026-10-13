'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Badge } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { roomName } from '@/lib/board';
import { useLive, useNow, useSession } from '@/lib/hooks';
import { isDeskRole, isDoctorRole } from '@/lib/session';
import { fmtMinSec, pad } from '@/lib/time';
import type { CodiHome, DoctorHome, HomePatient, StaffHome } from '@/lib/types';
import { MY, STAFF_STATUS, card, isForeign, natName, type MySt } from './common';
import { PatientView } from './PatientView';

const isCodiHome = (h: StaffHome): h is CodiHome => 'patients' in h;

// 직원 화면 틀 — 넓으면(≥760) 목록 + 상세 두 칸, 좁으면 /staff = 목록 · /staff/patient/[id] = 상세(시안 baseVals)
export function StaffShell() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const now = useNow();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(390);

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

  useEffect(() => {
    if (session && isDeskRole(session.role)) router.replace('/desk');
  }, [session, router]);

  if (!session) return null;

  const m = /^\/staff\/patient\/([^/]+)/.exec(pathname ?? '');
  const routeSel = m ? decodeURIComponent(m[1]) : null;
  const wide = w >= 760;
  const doctor = isDoctorRole(session.role);
  const h = home.data;

  // 목록 · 기본 선택 · 의사 기준 내 일정 상태
  let mineSt: Record<string, MySt> = {};
  let defaultSel: string | null = null;
  let list: React.ReactNode = null;
  const select = (id: string) => {
    router.push('/staff/patient/' + encodeURIComponent(id));
    if (!wide) window.scrollTo({ top: 0 });
  };

  if (h && isCodiHome(h)) {
    const rows = h.patients;
    defaultSel = (rows.find((p) => isForeign(p.nationality)) ?? rows[0])?.scheduleId ?? null;
    list = <CodiList home={h} now={now} selId={wide ? routeSel ?? defaultSel : null} onSelect={select} />;
  } else if (h) {
    const d = h as DoctorHome;
    const mine: (HomePatient & { st: MySt })[] = [
      ...d.done.map((p) => ({ ...p, st: 'done' as const })),
      ...(d.current ? [{ ...d.current, st: 'now' as const }] : []),
      ...(d.next ? [{ ...d.next, st: 'next' as const }] : []),
    ].sort((a, b) => a.time.localeCompare(b.time));
    mineSt = Object.fromEntries(mine.map((p) => [p.scheduleId, p.st]));
    defaultSel = (d.next ?? d.current ?? mine[0])?.scheduleId ?? null;
    list = (
      <DoctorList mine={mine} current={d.current} now={now} selId={wide ? routeSel ?? defaultSel : null} onSelect={select} />
    );
  }

  const selId = routeSel ?? (wide ? defaultSel : null);
  const showList = wide || !routeSel;
  const showDetail = wide || !!routeSel;
  const d = new Date(now);

  return (
    <div data-screen-label={doctor ? '직원 · 의사' : '직원 · 코디'} style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', background: '#e9ecef' }}>
      <div
        ref={wrapRef}
        className="bg-ms-gray-100"
        style={{
          width: '100%',
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.04)',
          position: 'relative',
        }}
      >
        <header
          className="bg-ms-white border-ms-gray-200"
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '12px 16px',
            borderBottomWidth: 1,
            borderBottomStyle: 'solid',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/ceramique-logo-color.svg" alt="CÉRAMIQUE" style={{ height: 16, display: 'block' }} />
            <span className="bg-ms-gray-300" style={{ width: 1, height: 14 }} />
            <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
              명동점
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className={doctor ? 'bg-purple' : 'bg-primary'} style={{ width: 8, height: 8, borderRadius: '50%' }} />
            <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
              {session.name} {doctor ? '원장' : '코디'}
            </span>
            <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
              {pad(d.getHours()) + ':' + pad(d.getMinutes())}
            </span>
          </div>
        </header>

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
                {h && isCodiHome(h) ? '지금 내원 환자' : '오늘 내 일정'}
              </button>
            )}
            {selId && showDetail && (
              <PatientView
                key={selId}
                scheduleId={selId}
                staffId={session.staffId}
                role={doctor ? 'doctor' : 'codi'}
                mySt={doctor ? mineSt[selId] ?? null : null}
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

function DoctorList({
  mine,
  current,
  now,
  selId,
  onSelect,
}: {
  mine: (HomePatient & { st: MySt })[];
  current: HomePatient | null;
  now: number;
  selId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      {current && (
        <div
          onClick={() => onSelect(current.scheduleId)}
          className="bg-primary text-ms-white"
          style={{ borderRadius: 12, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6, cursor: 'pointer' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span className="text-typo-caption-md-500" style={{ opacity: 0.9 }}>
              지금 진행 중
            </span>
            <span className="text-typo-body-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {fmtMinSec(current.since, now)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-title-sm-600">{roomName(current.room)}</span>
            <span className="text-typo-body-500">
              {current.name} · {current.procedure}
            </span>
          </div>
        </div>
      )}
      <div className="bg-ms-white" style={{ borderRadius: 12, display: 'flex', flexDirection: 'column', ...card, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px 10px' }}>
          <span className="text-typo-heading-md-500 text-ms-gray-800">오늘 내 일정</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {mine.filter((p) => p.st === 'done').length} / {mine.length} 완료
          </span>
        </div>
        {mine.map((p) => {
          const done = p.st === 'done';
          return (
            <div
              key={p.scheduleId}
              onClick={() => onSelect(p.scheduleId)}
              className={p.scheduleId === selId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
              style={{
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
              }}
            >
              <span
                className={done ? 'text-typo-caption-md-500 text-ms-gray-500' : 'text-typo-caption-md-600 text-ms-gray-800'}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {p.time}
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <span
                  className={done ? 'text-typo-body-500 text-ms-gray-500' : 'text-typo-body-600 text-ms-gray-800'}
                  style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {p.name} <span className="text-typo-caption-md-400 text-ms-gray-600">{roomName(p.room)}</span>
                </span>
                <span
                  className="text-typo-caption-md-400 text-ms-gray-600"
                  style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {p.procedure}
                </span>
              </div>
              <Badge variant={MY[p.st].variant} size="sm" dot={MY[p.st].dot}>
                {MY[p.st].name}
              </Badge>
            </div>
          );
        })}
      </div>
    </>
  );
}

function CodiList({
  home,
  now,
  selId,
  onSelect,
}: {
  home: CodiHome;
  now: number;
  selId: string | null;
  onSelect: (id: string) => void;
}) {
  const rows = home.patients;
  return (
    <div className="bg-ms-white" style={{ borderRadius: 12, display: 'flex', flexDirection: 'column', ...card, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '14px 16px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className="text-typo-heading-md-500 text-ms-gray-800">지금 내원 환자</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {rows.length}명 · 외국인 {rows.filter((p) => isForeign(p.nationality)).length}명
          </span>
        </div>
        <span className="text-typo-caption-md-400 text-ms-gray-600">
          대기 {home.summary.wait} · 상담 {home.summary.consult} · 시술 {home.summary.treat} · 경과 긴 순
        </span>
      </div>
      {rows.map((p) => {
        const s = STAFF_STATUS[p.state ?? 'wait'];
        const foreign = isForeign(p.nationality);
        return (
          <div
            key={p.scheduleId}
            onClick={() => onSelect(p.scheduleId)}
            className={p.scheduleId === selId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0,1fr) auto',
              gap: 10,
              alignItems: 'center',
              padding: '12px 16px',
              minHeight: 60,
              boxSizing: 'border-box',
              borderTopWidth: 1,
              borderTopStyle: 'solid',
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span
                  className="text-typo-body-600 text-ms-gray-800"
                  style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                >
                  {p.name}
                </span>
                {foreign && (
                  <span
                    className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700"
                    style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
                  >
                    {natName(p.nationality)}
                  </span>
                )}
              </div>
              <span
                className="text-typo-caption-md-400 text-ms-gray-600"
                style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
              >
                <b className="text-primary" style={{ fontWeight: 600 }}>
                  {roomName(p.room)}
                </b>{' '}
                · {p.label}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
              <Badge variant={s.variant} size="sm" dot={s.dot}>
                {s.name}
              </Badge>
              <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {fmtMinSec(p.since, now)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
