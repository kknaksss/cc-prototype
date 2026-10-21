'use client';

// 메모 = 원문 그대로(§0-b). 자르기 · 줄 숨김 · 강조 없음(WP12 — 위험 단어 · 직원 이름 강조 삭제). `**` 굵게만
import { useState } from 'react';
import type { PatientDetail } from './types';

// 원문 한 덩이 — `**` 굵게만(기호 안 보임)
export function Raw({ text }: { text: string }) {
  let bold = false;
  const out: React.ReactNode[] = [];
  String(text ?? '')
    .split(/(\*{2,})/)
    .forEach((part, i) => {
      if (/^\*{2,}$/.test(part)) {
        bold = !bold;
        return;
      }
      if (part) out.push(<span key={i} style={{ fontWeight: bold ? 700 : 400 }}>{part}</span>);
    });
  return <>{out}</>;
}

// 메모 블록 — 머리(방문 날짜) · 칸(제목 + 원문) · 안내 한 줄(시안 MEMO0)
export type MemoBlock =
  | { type: 'head'; head: string; sub: string; first: boolean }
  | { type: 'sec'; title: string; sub: string; text: string }
  | { type: 'note'; note: string };

const mmdd = (date: string) => date.slice(5);

// 오늘 칸 — 예약 메모 · 오늘 상담 내용 · 오늘 오더(상담사는 뺌) · 담당자 메모(완료된 시술의 것)
export function todayBlocks(
  p: PatientDetail,
  opt: { resvTitle?: string; hideOrder?: boolean; consultAt?: string },
): MemoBlock[] {
  const out: MemoBlock[] = [];
  if (p.reservationMemo) out.push({ type: 'sec', title: opt.resvTitle ?? '예약 메모', sub: '', text: p.reservationMemo });
  const v = p.visits.find((x) => x.today);
  // 상담 내용 — 잠금 중이어도 값이 있으면 그린다(잠금 중엔 데스크가 덧붙인 줄만 들어 있다 · SPEC-002 §5.1 D-33)
  if (v && v.consultation)
    out.push({
      type: 'sec',
      title: '상담 내용',
      sub: [v.counselors.length ? '· 상담사 ' + v.counselors.join(' · ') : '', opt.consultAt ? '· ' + opt.consultAt : '']
        .filter(Boolean)
        .join(' '),
      text: v.consultation,
    });
  if (v && !v.locked && v.orderMemo && !opt.hideOrder) out.push({ type: 'sec', title: '오늘 오더', sub: '· 오더 메모', text: v.orderMemo });
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
  if (!out.length) out.push({ type: 'note', note: p.isNew ? '첫내원' : '지난 방문 기록 없음' });
  return out;
}

export function MemoList({ blocks }: { blocks: MemoBlock[] }) {
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
          <MemoCard key={i} title={m.title} sub={m.sub} text={m.text} />
        ) : (
          <span key={i} className="text-typo-body-400 text-ms-gray-500">
            {m.note}
          </span>
        ),
      )}
    </>
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

// 메모 카드(#30) — 기본 접힘(첫 3줄 미리보기) + [펼치기]. 짧으면 버튼 없이 다 보인다
export function MemoCard({ title, sub, text }: { title: string; sub: string; text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.split('\n').length > 3 || text.length > 120;
  return (
    <div
      data-memo={title}
      className="bg-ms-white border-ms-gray-200"
      style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span className="text-typo-caption-md-600 text-ms-gray-700">
          {title} <span className="text-typo-caption-md-400 text-ms-gray-500">{sub}</span>
        </span>
        {long && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="cc-btn text-typo-caption-md-500 text-primary"
            style={{ whiteSpace: 'nowrap', flexShrink: 0 }}
          >
            {open ? '접기' : '펼치기'}
          </button>
        )}
      </div>
      <span
        className="text-typo-body-400 text-ms-gray-800"
        style={{
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
          wordBreak: 'keep-all',
          ...(long && !open ? { display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' } : {}),
        }}
      >
        <Raw text={text} />
      </span>
    </div>
  );
}
