'use client';

// 가운데 오더지 카드 1장(SPEC-003 §6.3 · 전체현황판 시안 M:808-905). 버튼이 보이는 · 켜지는 조건은 스냅샷 값(§5.11) 그대로
import { Fragment } from 'react';
import { Badge, Button, ResetIcon, Tooltip, TooltipContent, TooltipTrigger } from '@medisolve-ai/medikit';
import { MemoCard } from '@/lib/memo';
import { hm, minutesSince, pad } from '@/lib/time';
import type { Board, Card, Procedure } from '@/lib/types';
import type { UndoKind } from './UndoConfirm';
import { STATE_BADGE, STATE_NAME, cardLook, checkBox, needView, orderedProcs, procsOf, procLine, visitCls } from './view';

export interface CardActions {
  onPick: (ids: number[]) => void; // 고른 시술 id 전체(바꾼 뒤)
  onAnes: (c: Card) => void;
  onStart: (c: Card, p: Procedure) => void;
  onFinish: (c: Card, p: Procedure) => void;
  onUndo: (c: Card, p: Procedure, kind: UndoKind) => void; // 줄 되돌리기 아이콘 → 확인 모달(§5.13)
  onHome: (c: Card) => void;
  onOpenCall: (c: Card, rect: DOMRect | null) => void;
}

// 카드 드래그(SPEC-003 §5.12 · §6.3) — 귀가 대기 카드는 끌 수 없고 놓을 곳도 아니다(handlers 없음)
export interface CardDrag {
  dragging: boolean; // 이 카드를 끄는 중
  order: number; // 격자 안 그리는 자리(미리보기 포함)
  onStart?: () => void;
  onOver?: () => void;
  onDrop?: () => void;
  onEnd?: () => void;
}

export function OrderCard({
  board,
  card: c,
  now,
  picks,
  focus,
  act,
  drag,
}: {
  board: Board;
  card: Card;
  now: number;
  picks: number[];
  focus: number | null;
  act: CardActions;
  drag: CardDrag;
}) {
  const home = c.state === 'home';
  const need = c.need ? needView(board, c, c.need, now) : null;
  const anesOn = !!c.anesthesia.runningSince;
  const look = cardLook(c, focus, drag.dragging);
  const badgeVariant = need ? 'danger' : home ? 'neutral' : anesOn ? 'purple' : STATE_BADGE[c.state];
  const badgeText = need ? need.state : !home && anesOn ? '마취 중' : STATE_NAME[c.state];

  const pickable = procsOf(c).filter((p) => p.pickable);
  const sel = picks.filter((id) => pickable.some((p) => p.id === id));
  const all = pickable.length > 0 && sel.length === pickable.length;
  const some = sel.length > 0;

  const headEl = (
    <>
      {/* 1. 머리 한 줄 — 방 · 상태 배지 / 입실. 경과 글자 · 반영 상태 줄은 그리지 않는다(SPEC-003 §6.3 · §6.7 #8 · #11) */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <span className="text-typo-title-lg-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
            {c.room.title}
          </span>
          <Badge variant={badgeVariant} size="sm" dot>
            {badgeText}
          </Badge>
        </div>
        <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
          {c.inAt ? '입실 ' + hm(c.inAt) : ''}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'nowrap', minWidth: 0 }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: '#3e3e3e' }} />
        <span
          className="text-typo-caption-md-600 text-ms-gray-800"
          title={c.customer.name}
          style={{ flex: '0 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {c.customer.name}
        </span>
        {c.customer.nationality && (
          <span
            className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700"
            style={{ flexShrink: 0, padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}
          >
            {c.customer.nationality}
          </span>
        )}
        <span className={visitCls(c.customer.isNew)} style={{ flexShrink: 0, padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>
          {c.customer.isNew ? '첫내원' : '재내원'}
        </span>
        {/* 수납 필요 — 고객 줄 끝 Badge warning sm(§6.7 #7 · 시안 M:825-827) */}
        {c.paymentRequired && (
          <span style={{ flexShrink: 0, display: 'inline-flex' }}>
            <Badge variant="warning" size="sm">
              수납 필요
            </Badge>
          </span>
        )}
      </div>
    </>
  );
  const memoEl = (
    <>
      {/* 2. 오더 메모 — MemoCard(3줄 · 120자 넘으면 접기) */}
      {c.orderMemo && <MemoCard title="오더 메모" sub="" text={c.orderMemo} />}
    </>
  );
  const anesEl = (
    <>
      {/* 3. 마취 — 대기 · 진행 어느 때나 버튼(D-23 · §6.7 #1) */}
      <div
        data-compact-buttons="true"
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, minHeight: 26, padding: '0 6px 0 10px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, flexWrap: 'nowrap' }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700" style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            마취
          </span>
          {anesOn ? (
            <span
              className={c.anesthesia.long ? 'text-typo-caption-md-600 text-red' : 'text-typo-caption-md-600 text-purple'}
              style={{ flexShrink: 0, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}
            >
              {pad(minutesSince(c.anesthesia.runningSince, now))}분 경과
            </span>
          ) : (
            <span
              className="text-typo-caption-md-400 text-ms-gray-600"
              style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}
            >
              {c.anesthesia.lastMinutes != null ? '완료 ' + c.anesthesia.lastMinutes + '분' : '안 함'}
            </span>
          )}
        </div>
        {!home && (c.anesthesia.canStart || c.anesthesia.canEnd) && (
          <Button
            variant={c.anesthesia.canEnd ? 'solid' : 'outlined'}
            color={c.anesthesia.canEnd ? 'blue' : 'gray'}
            size="sm"
            onClick={() => act.onAnes(c)}
          >
            {c.anesthesia.canEnd ? '마취 종료' : '마취 시작'}
          </Button>
        )}
      </div>
    </>
  );
  const procsEl = (
    <>
      {/* 4. 선택 줄 + 시술 줄 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {!home && (
          <div
            className={some ? 'bg-primary-100 border-primary' : 'bg-ms-white border-ms-gray-200'}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 6px 6px 10px', borderRadius: 8, borderWidth: 1, borderStyle: 'solid' }}
          >
            <span
              role="checkbox"
              aria-checked={all ? true : some ? 'mixed' : false}
              onClick={pickable.length ? () => act.onPick(all ? [] : pickable.map((p) => p.id)) : undefined}
              className={
                !pickable.length
                  ? 'bg-ms-gray-100 border-ms-gray-200 text-ms-gray-100'
                  : some
                    ? 'bg-primary border-primary text-ms-white'
                    : 'bg-ms-white border-ms-gray-400 text-ms-white'
              }
              style={{ ...BOX, cursor: pickable.length ? 'pointer' : 'default', flexShrink: 0 }}
            >
              {some && !all ? '–' : '✓'}
            </span>
            <span
              onClick={pickable.length ? () => act.onPick(all ? [] : pickable.map((p) => p.id)) : undefined}
              className={some ? 'text-typo-body-600 text-primary' : 'text-typo-body-500 text-ms-gray-700'}
              style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', cursor: pickable.length ? 'pointer' : 'default' }}
            >
              {!pickable.length ? '호출할 대기 시술 없음' : some ? sel.length + '개 선택됨' : '전체 선택'}
            </span>
          </div>
        )}
        {orderedProcs(c).map((p, i, arr) => {
          const on = sel.includes(p.id);
          const line = procLine(board, p);
          const waitingCall = p.state === 'wait' && !!p.call && p.call.acceptedBy == null;
          // 완료 묶음 앞 점선 — 위에 진행 · 대기 시술이 있을 때만(§5.9 · 시안 cut)
          const prev = arr[i - 1];
          const cut = p.state === 'done' && !!prev && prev.state !== 'done';
          return (
            <Fragment key={p.id}>
              {cut && <div className="border-ms-gray-300" style={{ margin: '4px 0', borderTopWidth: 1, borderTopStyle: 'dashed' }} />}
              <div
                className={p.state === 'doing' ? 'bg-primary-100 border-primary' : on ? 'bg-ms-white border-primary' : 'bg-ms-white border-ms-gray-200'}
                style={{
                  borderWidth: 1,
                  borderStyle: 'solid',
                  borderRadius: 8,
                  padding: '8px 10px',
                  display: 'grid',
                  gridTemplateColumns: '20px minmax(0,1fr) auto',
                  gap: '4px 8px',
                  alignItems: 'center',
                }}
              >
                <span
                  role="checkbox"
                  aria-checked={on}
                  onClick={p.pickable ? () => act.onPick(on ? sel.filter((id) => id !== p.id) : [...sel, p.id]) : undefined}
                  className={
                    p.state === 'done'
                      ? 'bg-ms-gray-300 border-ms-gray-300 text-ms-white'
                      : p.pickable
                        ? checkBox(on)
                        : 'bg-ms-gray-100 border-ms-gray-200 text-ms-gray-100'
                  }
                  style={{ ...BOX, cursor: p.pickable ? 'pointer' : 'default' }}
                >
                  ✓
                </span>
                <span
                  className={
                    p.state === 'done'
                      ? 'text-typo-heading-sm-400 text-ms-gray-500'
                      : p.state === 'doing'
                        ? 'text-typo-title-sm-600 text-primary'
                        : 'text-typo-heading-md-500 text-ms-gray-800'
                  }
                  style={{ minWidth: 0, wordBreak: 'keep-all', overflowWrap: 'anywhere' }}
                >
                  {p.title}
                </span>
                <div data-compact-buttons="true" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {/* 「호출함」은 누르지 못한다 — 수락은 호출 탭에서만(§6.7 #4) */}
                  {waitingCall && (
                    <span data-badge-call="true" style={{ display: 'inline-flex' }}>
                      <Badge variant="primary" size="sm">
                        호출함
                      </Badge>
                    </span>
                  )}
                  {!home && p.state === 'wait' && (
                    <Button variant="outlined" color="blue" size="sm" disabled={!p.canStart} onClick={() => act.onStart(c, p)}>
                      시작
                    </Button>
                  )}
                  {/* 되돌리기 아이콘 — 진행 줄 [종료] 왼쪽 · 완료 줄 「완료」 왼쪽. 조건은 스냅샷 canUndo* 만(§5.13) */}
                  {p.state === 'doing' && p.canUndoStart && <UndoIcon onClick={() => act.onUndo(c, p, 'start')} />}
                  {p.state === 'done' && p.canUndoFinish && <UndoIcon onClick={() => act.onUndo(c, p, 'finish')} />}
                  {!home && p.state === 'doing' && (
                    <Button variant="solid" color="blue" size="sm" disabled={!p.canFinish} onClick={() => act.onFinish(c, p)}>
                      종료
                    </Button>
                  )}
                  {p.state === 'done' && (
                    <Badge variant="neutral" size="sm">
                      완료
                    </Badge>
                  )}
                </div>
                <span className={line.cls} style={{ gridColumn: '2 / -1', fontVariantNumeric: 'tabular-nums' }}>
                  {line.text}
                </span>
              </div>
            </Fragment>
          );
        })}
      </div>
    </>
  );
  const bottomEl = (
    <>
      {/* 5. 카드 맨 아래 큰 버튼 하나 — 남은 시술 있으면 [의사 호출](체크해야 켜짐) · 다 끝나면 [귀가 대기](Q1 ~ Q4) */}
      {!home && (c.canCall || c.canHome) && (
        <div data-fill-buttons="true" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr)', paddingTop: 4, marginTop: 'auto' }}>
          {c.canHome ? (
            <Button variant="solid" color="blue" size="md" onClick={() => act.onHome(c)}>
              귀가 대기
            </Button>
          ) : (
            <Button
              variant="solid"
              color="blue"
              size="md"
              disabled={!some}
              onClick={(e: React.MouseEvent<HTMLButtonElement>) => act.onOpenCall(c, e.currentTarget.getBoundingClientRect())}
            >
              {some ? '의사 호출 · ' + sel.length + '건' : '시술 선택 후 의사 호출'}
            </Button>
          )}
        </div>
      )}
    </>
  );

  return (
    <div
      data-visit={c.visitId}
      draggable={!!drag.onStart}
      onDragStart={
        drag.onStart
          ? (e: React.DragEvent<HTMLDivElement>) => {
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', String(c.visitId));
              drag.onStart?.();
            }
          : undefined
      }
      // 놓을 곳 = dragenter · dragover 를 모두 막아야 한다(dragenter 를 안 막으면 미리보기로 옮겨 온 카드 위에서 drop 이 안 온다)
      onDragEnter={drag.onOver ? (e: React.DragEvent<HTMLDivElement>) => e.preventDefault() : undefined}
      onDragOver={
        drag.onOver
          ? (e: React.DragEvent<HTMLDivElement>) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
              drag.onOver?.();
            }
          : undefined
      }
      onDrop={
        drag.onDrop
          ? (e: React.DragEvent<HTMLDivElement>) => {
              e.preventDefault();
              drag.onDrop?.();
            }
          : undefined
      }
      onDragEnd={drag.onEnd}
      className={'cc-room ' + (c.need ? 'bg-ms-white border-red text-ms-gray-800' : 'bg-ms-white border-ms-gray-300 text-ms-gray-800')}
      style={{
        minWidth: 0,
        boxSizing: 'border-box',
        borderRadius: 6,
        borderWidth: 1,
        borderStyle: 'solid',
        padding: '6px 8px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        outline: look.outline,
        outlineOffset: 2,
        opacity: look.opacity,
        boxShadow: look.shadow,
        order: drag.order,
        cursor: drag.onStart ? 'grab' : undefined,
        transition: 'opacity 160ms ease, box-shadow 160ms ease',
      }}
    >
      {headEl}
      {memoEl}
      {anesEl}
      {procsEl}
      {/* 큰 버튼은 marginTop:auto 로 카드 바닥(줄 높이가 카드 내용보다 클 때도) */}
      {bottomEl}
    </div>
  );
}

// 26 × 26 아이콘 버튼(줄 버튼 26px 높이와 맞춤) · 테두리 없음 · gray-500 → 호버 primary · 호버 툴팁 「되돌리기」(§6.3)
// medikit ResetIcon 은 시계 방향 새로고침 화살표라 좌우로 뒤집어 반시계(되돌리기) 방향으로 그린다
function UndoIcon({ onClick }: { onClick: () => void }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label="되돌리기"
          onClick={onClick}
          className="text-ms-gray-500 hover:text-primary"
          style={ICON_BTN}
        >
          <span style={{ display: 'inline-flex', transform: 'scaleX(-1)' }}>
            <ResetIcon size="sm" />
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent>되돌리기</TooltipContent>
    </Tooltip>
  );
}

const ICON_BTN: React.CSSProperties = {
  width: 26,
  height: 26,
  padding: 0,
  border: 'none',
  borderRadius: 6,
  background: 'transparent',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
  cursor: 'pointer',
};

const BOX: React.CSSProperties = {
  width: 20,
  height: 20,
  borderRadius: 4,
  borderWidth: 1,
  borderStyle: 'solid',
  boxSizing: 'border-box',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 12,
  fontWeight: 700,
};
