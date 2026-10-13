import type { BoardState } from '@/lib/types';

// 직원 시안 STATUS — 현황판 v3 와 같은 상태 이름 · 배지 색
export const STAFF_STATUS: Record<BoardState, { name: string; variant: 'neutral' | 'purple' | 'primary'; dot: boolean }> = {
  lounge: { name: '대기', variant: 'neutral', dot: false },
  wait: { name: '대기', variant: 'neutral', dot: false },
  consult: { name: '상담', variant: 'purple', dot: true },
  treat: { name: '시술', variant: 'primary', dot: true },
};

export const NAT: Record<string, string> = {
  TW: '대만',
  CN: '중국',
  HK: '홍콩',
  JP: '일본',
  US: '미국',
  TH: '태국',
  FR: '프랑스',
  PH: '필리핀',
  IN: '인도',
  KR: '한국',
};
export const natName = (code: string) => NAT[code] ?? code;
// 국적을 아는 외국인 — 국적 칩 · 외국인 수에 쓴다(현장 접수는 국적이 비어 있다)
export const isForeign = (code: string) => !!code && code !== 'KR';

// 의사 「오늘 내 일정」 상태 — 예정 없음(D-24)
export type MySt = 'done' | 'now' | 'next';
export const MY: Record<MySt, { name: string; variant: 'neutral' | 'purple' | 'primary'; dot: boolean }> = {
  done: { name: '완료', variant: 'neutral', dot: false },
  now: { name: '진행 중', variant: 'primary', dot: true },
  next: { name: '다음', variant: 'purple', dot: true },
};

export const card = { boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)' } as const;

// 통역 언어(SPEC §7.2) — 국적 → 기본 언어, 그 밖은 en. KR 은 [통역] 숨김
export const NAT_LANG: Record<string, string> = {
  TW: 'zh',
  CN: 'zh',
  HK: 'zh',
  JP: 'ja',
  US: 'en',
  PH: 'en',
  IN: 'en',
  TH: 'th',
  FR: 'fr',
};
export const defaultLang = (nat: string) => NAT_LANG[nat] ?? 'en';
// 자막 번체 변환 — TW · HK 의 중국어
export const isTraditional = (nat: string, lang: string) => lang === 'zh' && (nat === 'TW' || nat === 'HK');
export const LANGS: [string, string][] = [
  ['zh', '중국어'],
  ['en', '영어'],
  ['ja', '일본어'],
  ['th', '태국어'],
  ['fr', '프랑스어'],
  ['es', '스페인어'],
  ['tl', '타갈로그어'],
  ['hi', '힌디어'],
];
export const LANG_NAME: Record<string, string> = Object.fromEntries(LANGS);
