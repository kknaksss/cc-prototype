import { StaffShell } from '@/components/staff/StaffShell';

// /staff 와 /staff/patient/[scheduleId] 가 같은 틀(목록 + 상세)을 쓴다 — 선택은 경로로 정해진다
export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <StaffShell />
      {children}
    </>
  );
}
