// 고객 문진 웹 /q#<토큰>(SPEC-006 §2) — (main) 묶음 밖: 공통 헤더 · 로그인 확인 · 직원 세션 없음. 토큰은 # 뒤라 서버 · 로그 · Referer 에 안 남는다
// 법적 검토 필요: 고객 공개 웹 문진 — 개인정보(이름 · 생년월일 · 성별 · 휴대폰 · 주소 · 건강 답) 수집 · 동의 · 보관 · 링크 노출
import type { Metadata, Viewport } from 'next';
import { QuestionnairePage } from '@/components/q/QuestionnairePage';

// 제목에 고객 이름 없음 · 검색 · Referer 막음 · 외부 스크립트 · 분석 태그 0
export const metadata: Metadata = {
  title: 'Céramique',
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
};

export const viewport: Viewport = { width: 'device-width', initialScale: 1 };

export default function Page() {
  return <QuestionnairePage />;
}
