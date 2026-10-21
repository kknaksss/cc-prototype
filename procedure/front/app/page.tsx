'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { HOME, readSession } from '@/lib/session';

// `/` → 시술 현황판(로그인 안 했으면 /login) — SPEC-003 §6.1
export default function Index() {
  const router = useRouter();
  useEffect(() => {
    router.replace(readSession() ? HOME : '/login');
  }, [router]);
  return null;
}
