// 메모 표시 규칙(§3.4) — `**` 는 만날 때마다 굵게 켜고 끔(3개 이상 연속은 하나로), 기호는 안 보임.
// 값 없는 양식 줄(「고민:」 · 「H)」 · 빈 번호 「1.」)은 숨김. 메모 원문은 고치지 않는다(자르기 · 고르기만).
import { Fragment } from 'react';

const EMPTY_FORM = /^\s*(?:[^:：]{1,12}[:：]|[A-Za-z]\)|\d+\s*\.)\s*$/;

export const isEmptyFormLine = (line: string) => EMPTY_FORM.test(line);

export function visibleLines(lines: string[]): string[] {
  return lines.filter((l) => !isEmptyFormLine(l));
}

// 한 줄 → [글, 굵게?] 조각
export function boldSegments(text: string): { t: string; b: boolean }[] {
  const parts = text.split(/\*{2,}/);
  return parts.map((t, i) => ({ t, b: i % 2 === 1 })).filter((s) => s.t);
}

export function Bold({ text }: { text: string }) {
  return (
    <>
      {boldSegments(text).map((s, i) => (
        <span key={i} style={{ fontWeight: s.b ? 700 : 400 }}>
          {s.t}
        </span>
      ))}
    </>
  );
}

// 여러 줄 — 줄바꿈 유지(부모에 white-space:pre-wrap)
export function BoldLines({ lines }: { lines: string[] }) {
  const v = visibleLines(lines);
  return (
    <>
      {v.map((l, i) => (
        <Fragment key={i}>
          <Bold text={l} />
          {i < v.length - 1 ? '\n' : ''}
        </Fragment>
      ))}
    </>
  );
}
