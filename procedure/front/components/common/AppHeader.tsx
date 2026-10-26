'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useNow, useSession, useWide } from '@/lib/hooks';
import { HOME, clearSession } from '@/lib/session';
import { hm } from '@/lib/time';

// 공통 헤더 높이 — 아래 화면은 100vh 에서 이만큼 뺀다
export const HEADER_H = 57;

// 상단 메뉴 = 「현황」 하나 + 호버 드롭다운(SPEC-003 §6.2 · 시안 M:67-81). 항목 = 「시술 현황」 하나(예약 현황 · 원내 현황은 없음 — OQ-520)
const NAVS = [{ id: 'live', name: '현황', base: '/procedures', items: [{ name: '시술 현황', href: '/procedures/live' }] }];

export function AppHeader() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname() ?? '';
  const now = useNow();
  const wide = useWide();
  const [hover, setHover] = useState<string | null>(null);

  if (!session) return null;

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/');
  const logout = () => {
    clearSession();
    router.replace('/login');
  };

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
      <div style={{ display: 'flex', alignItems: 'center', gap: 48, minWidth: 0, height: '100%' }}>
        <Link href={HOME} style={{ display: 'flex', alignItems: 'center' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/ceramique-logo-color.svg" alt="CÉRAMIQUE" style={{ height: wide ? 22 : 18, display: 'block' }} />
        </Link>
        <nav style={{ display: 'flex', alignItems: 'stretch', gap: 40, height: '100%', minWidth: 0 }}>
          {NAVS.map((n) => (
            <div
              key={n.id}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              style={{ position: 'relative', display: 'flex', alignItems: 'stretch' }}
            >
              {/* 글자를 누르면 그 메뉴 첫 항목 */}
              <Link
                href={n.items[0].href}
                onClick={() => setHover(null)}
                aria-current={isActive(n.base) ? 'page' : undefined}
                className={'text-typo-heading-md-500 ' + (isActive(n.base) ? 'text-primary' : 'text-ms-gray-700')}
                style={{ whiteSpace: 'nowrap', display: 'flex', alignItems: 'center' }}
              >
                {n.name}
              </Link>
              {hover === n.id && (
                <div
                  className="bg-ms-white border-ms-gray-200"
                  style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    minWidth: 180,
                    borderWidth: 1,
                    borderStyle: 'solid',
                    borderRadius: 10,
                    boxShadow: '0 8px 28px rgba(0,0,0,0.12)',
                    padding: 6,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                  }}
                >
                  {n.items.map((i) => (
                    <Link
                      key={i.href}
                      href={i.href}
                      onClick={() => setHover(null)}
                      aria-current={isActive(i.href) ? 'page' : undefined}
                      className={isActive(i.href) ? 'text-typo-body-600 text-primary bg-primary-100' : 'text-typo-body-500 text-ms-gray-800'}
                      style={{ height: 40, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' }}
                    >
                      {i.name}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
        {wide && (
          <>
            <span className="text-typo-heading-sm-400 text-ms-black" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {hm(now)}
            </span>
            <span className="text-typo-heading-sm-400 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
              세라미크 명동점
            </span>
          </>
        )}
        {/* 계정 표시 = 로그인 계정 이름(SPEC-004 §3.6) */}
        <span className="text-typo-heading-sm-400 text-primary" style={{ whiteSpace: 'nowrap' }}>
          {session.name || session.id}
        </span>
        <button type="button" onClick={logout} className="cc-btn text-typo-heading-sm-400 text-ms-gray-700 hover:text-primary-500" style={{ whiteSpace: 'nowrap' }}>
          로그아웃
        </button>
      </div>
    </header>
  );
}
