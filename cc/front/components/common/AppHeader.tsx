'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ROLE_COLOR, RTITLE } from '@/lib/board';
import { useNow, useSession, useWide } from '@/lib/hooks';
import { clearSession, homePath } from '@/lib/session';
import { pad } from '@/lib/time';
import type { Role } from '@/lib/types';

// 공통 헤더 높이 — 아래 화면은 100vh 에서 이만큼 뺀다
export const HEADER_H = 57;

// 갈래(SPEC-002 §1) — 데스크 계정은 직원 홈이 없어 「내 스케쥴」이 없다(D-06)
const NAVS = [
  { name: '현황판', href: '/desk' },
  { name: '예약관리', href: '/reservations' },
  { name: '내 스케쥴', href: '/staff' },
];

export function AppHeader() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname() ?? '';
  const now = useNow();
  const wide = useWide();
  // 햄버거 메뉴는 연 경로에서만 열려 있다 — 갈래를 옮기거나 넓어지면 닫힌다
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = !wide && openAt === pathname;
  const setOpen = (v: boolean) => setOpenAt(v ? pathname : null);

  if (!session) return null;

  const desk = session.frame === 'desk';
  const navs = desk ? NAVS.filter((n) => n.href !== '/staff') : NAVS;
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/');
  const role = session.role as Role;
  const d = new Date(now);
  const logout = () => {
    clearSession();
    router.replace('/login');
  };

  const account = (
    <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
      {!desk && <span style={{ width: 8, height: 8, borderRadius: '50%', background: ROLE_COLOR[role], flexShrink: 0 }} />}
      <span className="text-typo-heading-sm-400 text-primary" style={{ whiteSpace: 'nowrap' }}>
        {desk ? '데스크' : `${session.name} ${RTITLE[role] ?? role}`}
      </span>
    </span>
  );
  const logoutBtn = (
    <button type="button" onClick={logout} className="cc-btn text-typo-heading-sm-400 text-ms-gray-700 hover:text-primary-500" style={{ whiteSpace: 'nowrap' }}>
      로그아웃
    </button>
  );

  return (
    <header
      className="bg-ms-white border-ms-gray-200"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 30,
        height: HEADER_H,
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        padding: wide ? '0 28px' : '0 16px',
        borderBottomWidth: 1,
        borderBottomStyle: 'solid',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 48, minWidth: 0 }}>
        <Link href={homePath(session.frame)} style={{ display: 'flex', alignItems: 'center' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/ceramique-logo-color.svg" alt="CÉRAMIQUE" style={{ height: wide ? 22 : 18, display: 'block' }} />
        </Link>
        {wide && (
          <nav style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
            {navs.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={isActive(n.href) ? 'page' : undefined}
                className={isActive(n.href) ? 'text-typo-heading-md-500 text-primary' : 'text-typo-heading-md-400 text-ms-gray-800 hover:text-primary-500'}
                style={{ whiteSpace: 'nowrap' }}
              >
                {n.name}
              </Link>
            ))}
          </nav>
        )}
      </div>

      {wide ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
          <span className="text-typo-heading-sm-400 text-ms-black" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {pad(d.getHours()) + ':' + pad(d.getMinutes())}
          </span>
          <span className="text-typo-heading-sm-400 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
            세라미크 명동점
          </span>
          {account}
          {logoutBtn}
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
              {navs.find((n) => isActive(n.href))?.name}
            </span>
            <button
              type="button"
              aria-label="메뉴"
              aria-expanded={open}
              onClick={() => setOpen(!open)}
              className="cc-btn text-ms-gray-800"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36 }}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d={open ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16'} />
              </svg>
            </button>
          </div>
          {open && (
            <>
              <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: `${HEADER_H}px 0 0 0`, background: 'rgba(0,0,0,0.24)' }} />
              <div
                className="bg-ms-white border-ms-gray-200"
                style={{
                  position: 'absolute',
                  top: HEADER_H,
                  left: 0,
                  right: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  borderBottomWidth: 1,
                  borderBottomStyle: 'solid',
                  boxShadow: '0 6px 20px rgba(0,0,0,0.12)',
                }}
              >
                <nav style={{ display: 'flex', flexDirection: 'column', padding: '4px 0' }}>
                  {navs.map((n) => (
                    <Link
                      key={n.href}
                      href={n.href}
                      onClick={() => setOpen(false)}
                      aria-current={isActive(n.href) ? 'page' : undefined}
                      className={
                        isActive(n.href) ? 'bg-primary-100 text-typo-body-600 text-primary' : 'text-typo-body-500 text-ms-gray-800'
                      }
                      style={{ padding: '14px 16px' }}
                    >
                      {n.name}
                    </Link>
                  ))}
                </nav>
                <div
                  className="border-ms-gray-200"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    padding: '12px 16px',
                    borderTopWidth: 1,
                    borderTopStyle: 'solid',
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                    {account}
                    <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                      명동점 · {pad(d.getHours()) + ':' + pad(d.getMinutes())}
                    </span>
                  </span>
                  {logoutBtn}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </header>
  );
}
