'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@medisolve-ai/medikit';
import { getStaffList, login } from '@/lib/api';
import { ROLE_COLOR } from '@/lib/board';
import { homePath, writeSession } from '@/lib/session';
import type { StaffAccount } from '@/lib/types';

// 시연 카드 5장 — 데스크 · 의사 · 상담사 · 피부관리사 · 간호사(§7, 시안 r4). 시안 이름이 그날 근무에 없으면 그 직군 첫 사람
const DEMO: { role: string; prefer: string; dest: string; suffix: string }[] = [
  { role: '데스크', prefer: '', dest: '현황판', suffix: '' },
  { role: '의사', prefer: '권태윤', dest: '내 일(배정형)', suffix: ' 원장' },
  { role: '상담사', prefer: '류하린', dest: '내 일(배정형)', suffix: ' 상담사' },
  { role: '피부관리사', prefer: '안건우', dest: '내 일(배정형)', suffix: ' 피부관리사' },
  { role: '간호사', prefer: '유채원', dest: '지금 내원 고객(순회형)', suffix: ' 간호사' },
];

export default function LoginPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<StaffAccount[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [id, setId] = useState('');
  const [pw, setPw] = useState('');
  const [err, setErr] = useState(false);
  const [toast, setToast] = useState('');
  const busy = useRef(false);

  useEffect(() => {
    getStaffList()
      .then(setAccounts)
      .catch((e: Error) => setLoadErr(e.message));
  }, []);

  const demo = useMemo(
    () =>
      DEMO.map((d) => ({
        ...d,
        a: accounts.find((a) => a.role === d.role && (!d.prefer || a.name === d.prefer)) ?? accounts.find((a) => a.role === d.role),
      })).filter(
        (d): d is typeof d & { a: StaffAccount } => !!d.a,
      ),
    [accounts],
  );

  // 비밀번호는 받기만 하고 검증하지 않는다(D-26) — 비어 있으면 시안처럼 오류
  const submit = async () => {
    if (busy.current) return;
    const a = accounts.find((x) => x.staffId === id.trim());
    if (!a || !pw) {
      setErr(true);
      return;
    }
    busy.current = true;
    try {
      const r = await login(a.staffId, pw);
      writeSession({ staffId: r.staffId, name: r.name, role: r.role, frame: r.frame });
      router.replace(homePath(r.frame, r.home));
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
            <span className="text-typo-title-sm-600 text-ms-gray-800">직원 로그인</span>
            <span className="text-typo-body-400 text-ms-gray-600" style={{ wordBreak: 'keep-all' }}>
              내 계정으로 들어오면 역할에 맞는 첫 화면이 열려요.
            </span>
          </div>
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
                  setErr(false);
                }}
                placeholder="아이디"
                autoComplete="username"
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
                  setErr(false);
                }}
                placeholder="비밀번호"
                autoComplete="current-password"
              />
            </label>
            {err && <span className="text-typo-caption-md-500 text-red">아이디 또는 비밀번호가 맞지 않아요.</span>}
            <button type="submit" hidden />
          </form>
          <div data-fill-buttons="true" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr)' }}>
            <Button variant="solid" color="blue" size="lg" onClick={() => void submit()} style={{ width: '100%' }}>
              로그인
            </Button>
          </div>

          <div
            className="border-ms-gray-200"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              paddingTop: 16,
              borderTopWidth: 1,
              borderTopStyle: 'solid',
            }}
          >
            <span className="text-typo-caption-md-600 text-ms-gray-700">시연용 계정</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {demo.map((d) => (
                <button
                  key={d.a.staffId}
                  type="button"
                  onClick={() => {
                    setId(d.a.staffId);
                    setPw('••••••');
                    setErr(false);
                  }}
                  className={
                    'cc-btn ' + (id === d.a.staffId ? 'bg-primary-100 border-primary' : 'bg-ms-white border-ms-gray-300')
                  }
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
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: ROLE_COLOR[d.role] }} />
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                    <span className="text-typo-body-600 text-ms-gray-800">{d.a.name + d.suffix}</span>
                    <span className="text-typo-caption-md-400 text-ms-gray-600">{d.a.staffId}</span>
                  </span>
                  <span className="text-typo-caption-md-500 text-primary" style={{ whiteSpace: 'nowrap' }}>
                    → {d.dest}
                  </span>
                </button>
              ))}
              {loadErr && <span className="text-typo-caption-md-500 text-red">{loadErr}</span>}
            </div>
            <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ wordBreak: 'keep-all' }}>
              첫 화면은 계정의 역할로 정해져요 — 데스크: 현황판 · 의사 · 상담사 · 피부관리사: 내 일(배정형) · 코디 ·
              간호사: 지금 내원 고객(순회형).
            </span>
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
