'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useNow, useSession, useWide } from '@/lib/hooks';
import { HOME, clearSession } from '@/lib/session';
import { hm } from '@/lib/time';

// 공통 헤더 높이 — 아래 화면은 100vh 에서 이만큼 뺀다
export const HEADER_H = 57;

// 메뉴 = 「시술 현황」 하나(D-17 · SPEC-003 §6.2). 모양은 cc 기능 front 의 AppHeader 그대로
const NAVS = [{ name: '시술 현황', href: '/procedures' }];

export function AppHeader() {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname() ?? '';
  const now = useNow();
  const wide = useWide();

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
      <div style={{ display: 'flex', alignItems: 'center', gap: 48, minWidth: 0 }}>
        <Link href={HOME} style={{ display: 'flex', alignItems: 'center' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/ceramique-logo-color.svg" alt="CÉRAMIQUE" style={{ height: wide ? 22 : 18, display: 'block' }} />
        </Link>
        <nav style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
          {NAVS.map((n) => (
            <Link
              key={n.href}
              href={HOME}
              aria-current={isActive(n.href) ? 'page' : undefined}
              className={isActive(n.href) ? 'text-typo-heading-md-500 text-primary' : 'text-typo-heading-md-400 text-ms-gray-800 hover:text-primary-500'}
              style={{ whiteSpace: 'nowrap' }}
            >
              {n.name}
            </Link>
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
