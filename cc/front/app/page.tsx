'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { homePath, readSession } from '@/lib/session';

export default function Index() {
  const router = useRouter();
  useEffect(() => {
    const s = readSession();
    router.replace(s ? homePath(s.frame) : '/login');
  }, [router]);
  return null;
}
