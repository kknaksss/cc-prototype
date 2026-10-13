// 메모 = 원문 그대로(§0-b). 자르기 · 줄 숨김 없음. 강조만:
// `**` 는 만날 때마다 굵게 켜고 끔(기호 안 보임) · 위험 단어(back riskWords) = 빨강 바탕 굵게 · 오늘 근무 직원 이름 = 파랑 굵게
import { RTITLE } from './board';
import type { PatientDetail, Role } from './types';

export interface Hl {
  risk: string[];
  staff: string[];
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function Highlight({ text, hl }: { text: string; hl: Hl }) {
  const words = [...hl.risk, ...hl.staff].filter(Boolean).sort((a, b) => b.length - a.length);
  const re = words.length ? new RegExp('(' + words.map(esc).join('|') + ')') : null;
  const out: React.ReactNode[] = [];
  let bold = false;
  String(text ?? '')
    .split(/(\*{2,})/)
    .forEach((part, i) => {
      if (/^\*{2,}$/.test(part)) {
        bold = !bold;
        return;
      }
      (re ? part.split(re) : [part]).forEach((t, j) => {
        if (!t) return;
        const risk = hl.risk.includes(t);
        const st = hl.staff.includes(t);
        out.push(
          <span
            key={i + ':' + j}
            className={risk ? 'bg-red-100 text-red' : st ? 'text-primary' : undefined}
            style={{ fontWeight: bold || risk || st ? 700 : 400, borderRadius: 3 }}
          >
            {t}
          </span>,
        );
      });
    });
  return <>{out}</>;
}

// 메모 블록 — 머리(방문 날짜) · 칸(제목 + 원문) · 안내 한 줄(시안 MEMO0)
export type MemoBlock =
  | { type: 'head'; head: string; sub: string; first: boolean }
  | { type: 'sec'; title: string; sub: string; text: string }
  | { type: 'note'; note: string };

const mmdd = (date: string) => date.slice(5);

// 오늘 칸 — 접수 메모 · 오늘 상담 내용 · 오늘 오더(상담사는 뺌) · 담당자 메모(완료된 시술의 것)
export function todayBlocks(
  p: PatientDetail,
  opt: { resvTitle?: string; hideOrder?: boolean; consultAt?: string },
): MemoBlock[] {
  const out: MemoBlock[] = [];
  if (p.reservationMemo) out.push({ type: 'sec', title: opt.resvTitle ?? '접수 메모', sub: '', text: p.reservationMemo });
  const v = p.visits.find((x) => x.today);
  if (v && !v.locked) {
    if (v.consultation)
      out.push({
        type: 'sec',
        title: '상담 내용',
        sub: [v.counselors.length ? '· 상담사 ' + v.counselors.join(' · ') : '', opt.consultAt ? '· ' + opt.consultAt : '']
          .filter(Boolean)
          .join(' '),
        text: v.consultation,
      });
    if (v.orderMemo && !opt.hideOrder) out.push({ type: 'sec', title: '오늘 오더', sub: '· 오더 메모', text: v.orderMemo });
  }
  if (v && v.assigneeMemos.length)
    out.push({ type: 'sec', title: '담당자 메모', sub: '', text: v.assigneeMemos.map((m) => m.label + ' — ' + m.memo).join('\n') });
  return out;
}

// 히스토리 — 고객 메모 · 지난 방문 카드(최근이 위)
export function historyBlocks(p: PatientDetail): MemoBlock[] {
  const out: MemoBlock[] = [];
  if (p.customerMemo) out.push({ type: 'sec', title: '고객 메모', sub: '', text: p.customerMemo });
  p.visits
    .filter((v) => !v.today)
    .forEach((v, i) => {
      out.push({
        type: 'head',
        head: mmdd(v.date) + ' 방문',
        sub: v.counselors.length ? '상담사 ' + v.counselors.join(' · ') : '',
        first: i === 0 && !p.customerMemo,
      });
      if (v.consultation) out.push({ type: 'sec', title: '상담 내용', sub: '', text: v.consultation });
      if (v.orderMemo) out.push({ type: 'sec', title: '오더 메모', sub: '', text: v.orderMemo });
      if (v.procedures.length) out.push({ type: 'sec', title: '시술', sub: '', text: v.procedures.join('\n') });
      if (v.assigneeMemos.length)
        out.push({ type: 'sec', title: '담당자 메모', sub: '', text: v.assigneeMemos.map((m) => m.label + ' — ' + m.memo).join('\n') });
    });
  if (!out.length) out.push({ type: 'note', note: p.isNew ? '첫 방문' : '지난 방문 기록 없음' });
  return out;
}

export function MemoList({ blocks, hl }: { blocks: MemoBlock[]; hl: Hl }) {
  return (
    <>
      {blocks.map((m, i) =>
        m.type === 'head' ? (
          <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 8, paddingTop: m.first ? 0 : 6 }}>
            <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
              {m.head}
            </span>
            <span className="text-typo-caption-md-400 text-ms-gray-600">{m.sub}</span>
          </div>
        ) : m.type === 'sec' ? (
          <div
            key={i}
            className="bg-ms-white border-ms-gray-200"
            style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}
          >
            <span className="text-typo-caption-md-600 text-ms-gray-700">
              {m.title} <span className="text-typo-caption-md-400 text-ms-gray-500">{m.sub}</span>
            </span>
            <span
              className="text-typo-body-400 text-ms-gray-800"
              style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'keep-all' }}
            >
              <Highlight text={m.text} hl={hl} />
            </span>
          </div>
        ) : (
          <span key={i} className="text-typo-body-400 text-ms-gray-500">
            {m.note}
          </span>
        ),
      )}
    </>
  );
}

// ⚠ 위험 단어 · 지정 직원 칩 — back riskHits · mentionedStaffIds(문자열 일치)
export function FlagChips({
  riskHits,
  mentioned,
}: {
  riskHits: string[];
  mentioned: { name: string; role?: string }[];
}) {
  if (!riskHits.length && !mentioned.length) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {riskHits.map((w) => (
        <span key={'r' + w} className="bg-red-100 text-red text-typo-caption-md-600" style={{ padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap' }}>
          ⚠ {w}
        </span>
      ))}
      {mentioned.map((m) => (
        <span
          key={'s' + m.name}
          className="bg-primary-100 text-primary text-typo-caption-md-600"
          style={{ padding: '2px 8px', borderRadius: 999, whiteSpace: 'nowrap' }}
        >
          지정 · {(m.role && m.role in RTITLE ? RTITLE[m.role as Role] + ' ' : '') + m.name}
        </span>
      ))}
    </div>
  );
}

// 보유 시술권 묶음 n/m
export function Bundles({ tickets }: { tickets: PatientDetail['tickets'] }) {
  if (!tickets.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingTop: 6 }}>
      <span className="text-typo-body-600 text-ms-gray-800">보유 시술권</span>
      {tickets.map((b) => (
        <div
          key={b.bundleId}
          className="bg-ms-white border-ms-gray-200"
          style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 8, padding: '8px 10px', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}
        >
          <span className="text-typo-body-500 text-ms-gray-800">{b.name}</span>
          <span className="text-typo-body-600 text-primary" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
            {b.left}/{b.total}
          </span>
        </div>
      ))}
    </div>
  );
}

// 오늘 근무 직원 이름 → 강조 재료
export const hlOf = (riskWords: string[], staff: { name: string; role: string }[]): Hl => ({
  risk: riskWords,
  staff: staff.filter((s) => s.role !== '데스크').map((s) => s.name),
});
