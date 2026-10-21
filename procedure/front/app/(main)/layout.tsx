import { AppHeader } from '@/components/common/AppHeader';

// 로그인 뒤 화면이 헤더 하나를 공유한다
export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AppHeader />
      {children}
    </>
  );
}
