'use client';

// 시술 줄 되돌리기 확인 모달(SPEC-003 §5.13 · §6.3) — medikit ConfirmModal. 바깥 누르면 닫힘(= 취소)
// 열린 동안 SSE 로 그 시술의 아이콘 조건이 꺼져도 모달은 그대로 — 누르면 back 이 409 로 답한다
import { ConfirmModal } from '@medisolve-ai/medikit';

export type UndoKind = 'start' | 'finish';

export interface UndoTarget {
  kind: UndoKind; // start = [시작] 되돌리기(→ 시술 대기) · finish = [종료] 되돌리기(→ 시술 중)
  procedureId: number;
  room: string;
  title: string;
}

export const UNDO_TITLE: Record<UndoKind, string> = {
  start: '시술 대기로 되돌리겠습니까?',
  finish: '시술 중으로 되돌리겠습니까?',
};

// medikit-patches.css [Button-1] 이 Button 전부에 flex-shrink:0 을 걸어 w-full 두 버튼이 모달 밖으로 넘친다 → 이 모달만 인라인으로 줄어들게(review-code-r2 F1)
const SHRINK: React.CSSProperties = { flexShrink: 1, minWidth: 0 };

export function UndoConfirm({ target, onClose, onConfirm }: { target: UndoTarget | null; onClose: () => void; onConfirm: (t: UndoTarget) => void }) {
  if (!target) return null;
  return (
    <ConfirmModal
      isOpen
      title={UNDO_TITLE[target.kind]}
      description={target.room + ' · ' + target.title}
      variant="caution"
      onBackdropClick={onClose}
      leftButton={{ label: '취소', onClick: onClose, style: SHRINK }}
      rightButton={{ label: '되돌리기', onClick: () => onConfirm(target), style: SHRINK }}
    />
  );
}
