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

// 한글 읽기(SPEC-002 §5.2 D-25) — 외국 고객 영문 이름 옆 회색 작은 글씨. 한국인 · 값 없으면 없음
export const readingOf = (nationality: string, phoneticName: string | null | undefined) =>
  nationality !== 'KR' && phoneticName ? phoneticName : null;
export const READING_CLS = 'text-typo-caption-md-400 text-ms-gray-600';

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
