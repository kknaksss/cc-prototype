import { AppHeader } from '@/components/common/AppHeader';

// 로그인 뒤 화면(/desk · /reservations · /staff)이 헤더 하나를 공유한다 — 갈래를 옮겨도 헤더는 다시 그리지 않는다(SPEC-002 §1)
export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AppHeader />
      {children}
    </>
  );
}
