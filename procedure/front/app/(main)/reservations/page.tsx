'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { readSession } from '@/lib/session';

// `/reservations` → 예약 현황(로그인 안 했으면 /login) — SPEC-005 §6.1
export default function ReservationsIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace(readSession() ? '/reservations/live' : '/login');
  }, [router]);
  return null;
}
