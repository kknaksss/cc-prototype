'use client';

// cc 기능 front 의 memo.tsx 의 MemoCard 만 복사(SPEC-003 §2.4) — 오더 메모 3줄 · 120자 넘으면 접기(P19)
import { useState } from 'react';

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

// 메모 카드 — 기본 접힘(첫 3줄 미리보기) + [펼치기]. 짧으면 버튼 없이 다 보인다
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
