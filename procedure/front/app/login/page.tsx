'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@medisolve-ai/medikit';
import { ApiError, login } from '@/lib/api';
import { HOME, writeSession } from '@/lib/session';

// 로그인 — 아이디 + 비밀번호(1차 cc 로그인 폼의 칸 · 버튼 모양). Enter 로 제출 · 실패는 빨간 한 줄
const BAD = '아이디 또는 비밀번호가 맞지 않아요.';

export default function LoginPage() {
  const router = useRouter();
  const [id, setId] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const busy = useRef(false);

  const submit = async () => {
    if (busy.current) return;
    if (!id.trim() || !pw) {
      setErr(BAD);
      return;
    }
    busy.current = true;
    try {
      const r = await login(id.trim(), pw);
      writeSession({ token: r.token, id: r.id, expiresAt: r.expiresAt, role: r.role, name: r.name });
      router.replace(HOME);
    } catch (e) {
      // 401 = 틀림 · 429 = 잠금(back 문구) · 그 밖(연결 · 설정) = back/front 문구
      if (e instanceof ApiError && e.status === 401) setErr(BAD);
      else setErr(e instanceof Error ? e.message : '로그인하지 못했어요');
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
          <span className="text-typo-title-sm-600 text-ms-gray-800">로그인</span>
          <form
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span className="text-typo-caption-md-600 text-ms-gray-700">아이디</span>
              <input
                className="cc-input"
                value={id}
                onChange={(e) => {
                  setId(e.target.value);
                  setErr('');
                }}
                placeholder="아이디"
                autoComplete="username"
                autoFocus
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span className="text-typo-caption-md-600 text-ms-gray-700">비밀번호</span>
              <input
                className="cc-input"
                type="password"
                value={pw}
                onChange={(e) => {
                  setPw(e.target.value);
                  setErr('');
                }}
                placeholder="비밀번호"
                autoComplete="current-password"
              />
            </label>
            {err && <span className="text-typo-caption-md-500 text-red">{err}</span>}
            {/* Enter 로 제출 */}
            <button type="submit" hidden />
          </form>
          <div data-fill-buttons="true" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr)' }}>
            <Button variant="solid" color="blue" size="lg" onClick={() => void submit()} style={{ width: '100%' }}>
              로그인
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
