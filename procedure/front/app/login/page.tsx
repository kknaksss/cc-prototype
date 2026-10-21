'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getAccounts, login } from '@/lib/api';
import { HOME, writeSession } from '@/lib/session';
import type { Account } from '@/lib/types';

// 로그인 — 계정 카드를 누르면 바로 로그인(1 · 2차 PoC 시연 카드 모양 · 아이디/비밀번호 입력 없음).
// 웹 = 간호 스테이션 · 의국 PC 용이라 back 목록 중 role=admin 카드만 보인다(SPEC-004 §3.6). 의사 · 간호사 카드는 앱 몫
export default function LoginPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState('');
  const busy = useRef(false);

  useEffect(() => {
    getAccounts()
      .then((list) => setAccounts(list.filter((a) => a.role === 'admin')))
      .catch((e: Error) => setLoadErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  const enter = async (a: Account) => {
    if (busy.current) return;
    busy.current = true;
    try {
      const r = await login(a.id);
      writeSession({ token: r.token, id: r.id, expiresAt: r.expiresAt, role: r.role, name: r.name });
      router.replace(HOME);
    } catch (e) {
      setToast(e instanceof Error ? e.message : '로그인하지 못했어요');
      setTimeout(() => setToast(''), 2400);
    } finally {
      busy.current = false;
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', background: '#e9ecef' }}>
      <div
        className="bg-ms-gray-100"
        style={{
          width: '100%',
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '32px 16px',
          boxSizing: 'border-box',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.04)',
        }}
      >
        <div
          className="bg-ms-white"
          style={{
            width: '100%',
            maxWidth: 400,
            borderRadius: 16,
            padding: '28px 20px 24px',
            boxSizing: 'border-box',
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
            boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/ceramique-logo-color.svg" alt="CÉRAMIQUE" style={{ height: 20, display: 'block' }} />
            <span className="text-typo-caption-md-400 text-ms-gray-600">명동점</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="text-typo-title-sm-600 text-ms-gray-800">로그인</span>
            <span className="text-typo-body-400 text-ms-gray-600" style={{ wordBreak: 'keep-all' }}>
              계정을 누르면 바로 시술 현황판이 열려요.
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">시연용 계정</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {accounts.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => void enter(a)}
                  className="cc-btn bg-ms-white border-ms-gray-300 hover:bg-primary-100 hover:border-primary"
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '10px minmax(0,1fr) auto',
                    gap: 10,
                    alignItems: 'center',
                    padding: '11px 12px',
                    borderRadius: 8,
                    borderWidth: 1,
                    borderStyle: 'solid',
                  }}
                >
                  <span className="bg-primary" style={{ width: 8, height: 8, borderRadius: '50%' }} />
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                    <span className="text-typo-body-600 text-ms-gray-800">{a.name}</span>
                    <span className="text-typo-caption-md-400 text-ms-gray-600">{a.label}</span>
                  </span>
                  <span className="text-typo-caption-md-500 text-primary" style={{ whiteSpace: 'nowrap' }}>
                    → 시술 현황
                  </span>
                </button>
              ))}
              {loading && <span className="text-typo-caption-md-400 text-ms-gray-500">계정을 불러오는 중…</span>}
              {!loading && !loadErr && !accounts.length && (
                <span className="text-typo-caption-md-400 text-ms-gray-500">로그인할 수 있는 계정이 없어요</span>
              )}
              {loadErr && <span className="text-typo-caption-md-500 text-red">{loadErr}</span>}
            </div>
          </div>
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
              padding: '10px 16px',
              boxShadow: '0 6px 20px rgba(0,0,0,0.18)',
            }}
          >
            <span className="text-typo-body-500" style={{ whiteSpace: 'nowrap' }}>
              {toast}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
