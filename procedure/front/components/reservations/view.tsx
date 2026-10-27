// 예약 현황 화면 문구 · 색 · 시각 계산 — 응답 값을 보여 주는 방법만. 규칙(full · plusAllowed · draggable · can.* …)은 back 값(SPEC-005 §5 머리)
import type { BadgeVariant } from '@medisolve-ai/medikit';
import { pad, toMs } from '@/lib/time';
import type { Gender, Money, ResvColumn, ResvMain, ResvState, ResvSub, ResvZone } from '@/lib/types';

// ─── 상태(§5.1 · 시안 BK_BAR M:1189 · 범례 M:1885)
export const MAIN_NAME: Record<ResvMain, string> = {
  reserved: '예약',
  reception: '접수',
  consultation: '상담',
  procedure: '시술',
  home: '귀가',
  canceled: '취소',
  noshow: '부도',
};
export const SUB_NAME: Record<Exclude<ResvSub, null>, string> = { waiting: '대기', doing: '진행', done: '완료' };

// 카드 왼쪽 막대 · 상세 머리 색. 귀가는 대기(gray-600) / 완료(gray-300). 부도 = 빨강 외곽선(시안에 없음 · §6.8 #23)
export function barStyle(s: ResvState): { cls: string; style?: React.CSSProperties } {
  switch (s.main) {
    case 'reserved':
      return { cls: 'bg-purple' };
    case 'reception':
      return { cls: 'bg-yellow' };
    case 'consultation':
      return { cls: 'bg-cons' };
    case 'procedure':
      return { cls: 'bg-primary' };
    case 'home':
      return { cls: s.sub === 'done' ? 'bg-ms-gray-300' : 'bg-ms-gray-600' };
    case 'canceled':
      return { cls: 'bg-red' };
    case 'noshow':
      return { cls: 'bg-ms-white', style: { boxShadow: 'inset 0 0 0 1px var(--ms-red, #f04452)' } };
  }
}

// 범례 Badge 7(§6.2) — 상담 · 귀가 · 부도는 시안처럼 className 으로 색을 덮는다
export const LEGEND: { main: ResvMain; variant: BadgeVariant; cls?: string; style?: React.CSSProperties }[] = [
  { main: 'reserved', variant: 'purple' },
  { main: 'reception', variant: 'warning' },
  { main: 'consultation', variant: 'neutral', cls: 'bg-cons-100 text-cons' },
  { main: 'procedure', variant: 'primary' },
  { main: 'home', variant: 'neutral', cls: 'bg-ms-gray-200 text-ms-gray-800' },
  { main: 'canceled', variant: 'danger' },
  { main: 'noshow', variant: 'danger', cls: 'bg-ms-white text-red', style: { boxShadow: 'inset 0 0 0 1px currentColor' } },
];

// 상세 머리(§6.6) — 색 + 제목
export function headOf(s: ResvState): { cls: string; style?: React.CSSProperties; title: string } {
  const sub = s.sub ? SUB_NAME[s.sub] : '';
  switch (s.main) {
    case 'reserved':
      return { cls: 'bg-purple text-ms-white', title: '접수 전' };
    case 'reception':
      return { cls: 'bg-yellow text-ms-gray-800', title: '접수 완료' };
    case 'consultation':
      return { cls: 'bg-cons text-ms-white', title: '상담 ' + (sub || '대기') };
    case 'procedure':
      return { cls: 'bg-primary text-ms-white', title: '시술 ' + (sub || '대기') };
    case 'home':
      return { cls: (s.sub === 'done' ? 'bg-ms-gray-400' : 'bg-ms-gray-600') + ' text-ms-white', title: '귀가 ' + (s.sub === 'done' ? '완료' : '대기') };
    case 'canceled':
      return { cls: 'bg-red text-ms-white', title: '예약 취소' };
    case 'noshow':
      return { cls: 'bg-ms-white text-red', style: { boxShadow: 'inset 0 0 0 2px var(--ms-red, #f04452)' }, title: '예약 부도' };
  }
}

// ─── 부상태 색 규칙(E2E b3 #3) — 주 상태 색은 그대로 · 같은 색 안에서 진하기로. 예약 현황 전부 이 함수 하나로
//   대기 = 연한 배경(100) + 그 색 글자 · 점 ○ / 진행 = 그 색 채움 + 흰 글자 · 점 ●(채운 카드 위라 흰 점) / 완료 = 회색(주 상태 무관) / 아직 = 흰 바탕 · 회색 ○
// 클래스는 Tailwind 가 찾을 수 있게 글자 그대로 적는다
export type Phase = 'none' | 'waiting' | 'doing' | 'done';
const MAIN_TONE: Record<ResvMain, { fill: string; soft: string; text: string; border: string }> = {
  reserved: { fill: 'bg-purple', soft: 'bg-purple-100', text: 'text-purple', border: 'border-purple' },
  reception: { fill: 'bg-yellow', soft: 'bg-yellow-100', text: 'text-yellow', border: 'border-yellow' },
  consultation: { fill: 'bg-cons', soft: 'bg-cons-100', text: 'text-cons', border: 'border-cons' },
  procedure: { fill: 'bg-primary', soft: 'bg-primary-100', text: 'text-primary', border: 'border-primary' },
  home: { fill: 'bg-ms-gray-600', soft: 'bg-ms-gray-200', text: 'text-ms-gray-700', border: 'border-ms-gray-600' },
  canceled: { fill: 'bg-red', soft: 'bg-red-100', text: 'text-red', border: 'border-red' },
  noshow: { fill: 'bg-red', soft: 'bg-red-100', text: 'text-red', border: 'border-red' },
};
export interface PhaseStyle {
  chip: string; // 칩 · Badge(배경 + 글자)
  dot: string; // 점(테두리 2px 원 — ○ 는 흰 속 · ● 는 채움)
  card: string; // 내원 현황 단계 카드(배경 + 테두리)
  title: string; // 카드 제목 글자
  sub: string; // 카드 상세 · 시각 글자
}
export function phaseStyle(main: ResvMain, phase: Phase): PhaseStyle {
  const t = MAIN_TONE[main];
  switch (phase) {
    case 'waiting':
      return { chip: t.soft + ' ' + t.text, dot: 'bg-ms-white ' + t.border, card: t.soft + ' ' + t.border, title: t.text, sub: 'text-ms-gray-600' };
    case 'doing':
      return { chip: t.fill + ' text-ms-white', dot: 'bg-ms-white border-ms-white', card: t.fill + ' ' + t.border, title: 'text-ms-white', sub: 'text-ms-white' };
    case 'done':
      return { chip: 'bg-ms-gray-100 text-ms-gray-500', dot: 'bg-ms-gray-400 border-ms-gray-400', card: 'bg-ms-white border-ms-gray-300', title: 'text-ms-gray-500', sub: 'text-ms-gray-500' };
    case 'none':
      return { chip: 'bg-ms-gray-100 text-ms-gray-500', dot: 'bg-ms-white border-ms-gray-300', card: 'bg-ms-white border-ms-gray-300', title: 'text-ms-gray-400', sub: 'text-ms-gray-400' };
  }
}
// 부상태 → 단계(부상태가 없으면 null — 칩을 그리지 않는다)
export const phaseOfSub = (sub: ResvSub): Phase | null => (sub === 'waiting' ? 'waiting' : sub === 'doing' ? 'doing' : sub === 'done' ? 'done' : null);

// 상태 글자 「상담 · 대기」 꼴
export const stateText = (s: ResvState) => MAIN_NAME[s.main] + (s.sub ? ' · ' + SUB_NAME[s.sub] : '');
export const isClosed = (s: ResvState) => s.main === 'canceled' || s.main === 'noshow';

// ─── 시각(KST) — 브라우저 시간대와 상관없이
const KST = 9 * 3600 * 1000;
const WD = ['일', '월', '화', '수', '목', '금', '토'];

// ISO → 그날 KST 분(0 ~ 1440)
export function kstMin(iso: string | null | undefined): number | null {
  const t = toMs(iso);
  if (t === null) return null;
  const d = new Date(t + KST);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}
export const hmToMin = (v: string) => {
  const [h, m] = v.split(':').map(Number);
  return h * 60 + (m || 0);
};
export const minToHm = (m: number) => pad(Math.floor(m / 60)) + ':' + pad(m % 60);
// 그 날짜 KST HH:MM → ISO(+09:00)
export const isoAt = (date: string, m: number) => `${date}T${minToHm(m)}:00+09:00`;

// YYYY-MM-DD ± n 일
export function shiftDate(date: string, n: number): string {
  const [y, m, d] = date.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.getUTCFullYear() + '-' + pad(t.getUTCMonth() + 1) + '-' + pad(t.getUTCDate());
}
const dateParts = (date: string) => {
  const [y, m, d] = date.split('-').map(Number);
  return { y, m, d, wd: WD[new Date(Date.UTC(y, m - 1, d)).getUTCDay()] };
};
// 「2026. 10. 26. (월)」(§6.2)
export function dateTitle(date: string): string {
  const p = dateParts(date);
  return `${p.y}. ${p.m}. ${p.d}. (${p.wd})`;
}
// 「10/26 (월)」(등록 모달 머리 · §6.5)
export function dateShort(date: string): string {
  const p = dateParts(date);
  return `${p.m}/${p.d} (${p.wd})`;
}

// ─── 칸 머리 정원(§5.2) — 켜진 구역마다 「{구역} {N}명」 을 · 로 잇는다(구역 하나여도 같은 꼴 — E2E #7) · 없음 = 「- 명」
export function capacityText(col: ResvColumn, zones: ResvZone[]): string {
  const caps = col.capacities;
  if (!caps.length) return '- 명';
  const order = (id: number) => zones.find((z) => z.zoneId === id)?.order ?? 0;
  const title = (id: number) => zones.find((z) => z.zoneId === id)?.title ?? '';
  return caps
    .slice()
    .sort((a, b) => order(a.zoneId) - order(b.zoneId))
    .map((c) => [title(c.zoneId), c.capacity + '명'].filter(Boolean).join(' '))
    .join(' · ');
}

// ─── 고객 표시
export const genderIcon = (g: Gender): { icon: string; cls: string; label: string } | null =>
  g === 'MALE' ? { icon: '♂', cls: 'text-primary', label: '남성' } : g === 'FEMALE' ? { icon: '♀', cls: 'text-red', label: '여성' } : null;
export const visitChip = (isNew: boolean) =>
  isNew ? { text: '초진', cls: 'bg-purple-100 text-purple' } : { text: '재진', cls: 'bg-ms-gray-100 text-ms-gray-600' };

// 금액(§5.9) — KRW 는 「₩」 + 천 단위 쉼표 · 모르면 「-」
export function money(v: number | null | undefined, currency: string | null | undefined): string {
  if (v == null) return '-';
  const n = v.toLocaleString('ko-KR');
  return !currency || currency === 'KRW' ? '₩' + n : n + ' ' + currency;
}
export const moneyOf = (a: Money | null, k: 'total' | 'paid') => (a ? money(a[k], a.currency) : '-');

// ─── 국가 이름(front 고정 ISO alpha-2 표 — §6.3 · §6.5 · U Q-48). 표에 없으면 코드 그대로
export const NATIONS: Record<string, string> = {
  KR: '한국',
  CN: '중국',
  TW: '대만',
  HK: '홍콩',
  MO: '마카오',
  JP: '일본',
  US: '미국',
  CA: '캐나다',
  GB: '영국',
  AU: '호주',
  NZ: '뉴질랜드',
  IE: '아일랜드',
  SG: '싱가포르',
  MY: '말레이시아',
  TH: '태국',
  VN: '베트남',
  PH: '필리핀',
  ID: '인도네시아',
  MN: '몽골',
  KZ: '카자흐스탄',
  UZ: '우즈베키스탄',
  KH: '캄보디아',
  MM: '미얀마',
  LA: '라오스',
  BN: '브루나이',
  IN: '인도',
  NP: '네팔',
  BD: '방글라데시',
  PK: '파키스탄',
  LK: '스리랑카',
  AE: '아랍에미리트',
  SA: '사우디아라비아',
  QA: '카타르',
  KW: '쿠웨이트',
  IL: '이스라엘',
  TR: '튀르키예',
  RU: '러시아',
  UA: '우크라이나',
  DE: '독일',
  FR: '프랑스',
  IT: '이탈리아',
  ES: '스페인',
  PT: '포르투갈',
  NL: '네덜란드',
  BE: '벨기에',
  CH: '스위스',
  AT: '오스트리아',
  SE: '스웨덴',
  NO: '노르웨이',
  DK: '덴마크',
  FI: '핀란드',
  PL: '폴란드',
  CZ: '체코',
  HU: '헝가리',
  GR: '그리스',
  RO: '루마니아',
  MX: '멕시코',
  BR: '브라질',
  AR: '아르헨티나',
  CL: '칠레',
  CO: '콜롬비아',
  PE: '페루',
  EG: '이집트',
  ZA: '남아프리카공화국',
  NG: '나이지리아',
  KE: '케냐',
  MA: '모로코',
};
export const nationName = (code: string | null | undefined) => (code ? (NATIONS[code.toUpperCase()] ?? code) : '');
// 국적 select 목록(등록 모달) — 이름 순 · 한국 먼저
export const NATION_OPTIONS = Object.entries(NATIONS)
  .map(([code, name]) => ({ code, name }))
  .sort((a, b) => (a.code === 'KR' ? -1 : b.code === 'KR' ? 1 : a.name.localeCompare(b.name, 'ko')));

// 국기(18×12 · flag-icons — §6.3 · OQ-734). 표에 없는 코드 · 빈 값 = 회색 상자 + 코드 글자(없으면 「-」)
export function Flag({ code }: { code: string | null | undefined }) {
  const c = (code ?? '').toUpperCase();
  const known = !!NATIONS[c];
  const box: React.CSSProperties = {
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    padding: '2px 4px',
    borderWidth: 1,
    borderStyle: 'solid',
    borderRadius: 4,
  };
  if (!known)
    return (
      <span className="bg-ms-gray-100 border-ms-gray-300 text-ms-gray-500" title={c || '국적 없음'} style={{ ...box, fontSize: 10, lineHeight: '12px', fontWeight: 600 }}>
        {c || '-'}
      </span>
    );
  return (
    <span className="bg-ms-gray-100 border-ms-gray-300" title={NATIONS[c]} style={box}>
      <span role="img" aria-label={NATIONS[c]} className={'fi fi-' + c.toLowerCase()} style={{ width: 18, height: 12, display: 'block', borderRadius: 1, lineHeight: '12px', backgroundSize: 'cover' }} />
    </span>
  );
}
