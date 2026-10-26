'use client';

// 시술 현황판(SPEC-003 §6 · 전체현황판 시안 「현황 › 시술 현황」 M:777-1098). 사이드바 없음 — main 여백 · 제목 줄 · 카드판 · 오른쪽 패널 · 토스트
import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { useBoardStream, useNow, useSession, useWide } from '@/lib/hooks';
import { clearSession } from '@/lib/session';
import { hms } from '@/lib/time';
import type { Card, CallTarget, OpenCall, Procedure } from '@/lib/types';
import { HEADER_H } from '@/components/common/AppHeader';
import { Aside, type TabId } from '@/components/procedures/Aside';
import { CallPopover, placePopover, type CallDraft } from '@/components/procedures/CallPopover';
import { OrderCard } from '@/components/procedures/OrderCard';
import { LEGEND, filterFn, liveIds, procsOf, moveCard, sameOrder, withLocalOrder, type FilterId } from '@/components/procedures/view';

// 놓은 뒤 응답을 받고 이만큼 안에 「같음」 스냅샷이 없으면 그냥 스냅샷을 따른다(§5.12 ③)
const SETTLE_MS = 3000;

// 놓은 뒤 로컬 순서(§5.12 「놓은 뒤 화면」) — req = 마지막 요청 번호 · ids = 로컬 순서 · saved = 성공 응답 visitIds(받기 전엔 null)
interface LocalOrder {
  req: number;
  ids: number[];
  saved: number[] | null;
}
// 끄는 중 — from = 끄는 카드 · start = 드래그 시작 때의 전체 순서(앞 · 뒤 판정 기준) · over = 지금 올라간 카드
interface Drag {
  from: number;
  start: number[];
  over: number | null;
}

export default function ProceduresLivePage() {
  const session = useSession();
  const live = useBoardStream(session?.token ?? null);
  const board = live.board;
  const now = useNow() + live.skew;
  const wide = useWide();

  const [local, setLocal] = useState<LocalOrder | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const reqNo = useRef(0);
  const [tab, setTab] = useState<TabId>('status');
  const [filter, setFilter] = useState<FilterId>('all');
  const [focus, setFocus] = useState<number | null>(null);
  // 카드에서 고른 호출할 시술 — 카드(visitId)마다 procedure id
  const [picks, setPicks] = useState<Record<number, number[]>>({});
  const [draft, setDraft] = useState<CallDraft | null>(null);
  // 토스트 — 시안 문구 · 2.6초 · 되돌리기 없음(D-28). n 이 바뀌면 타이머를 다시 건다
  const [toast, setToast] = useState<{ text: string; n: number } | null>(null);
  const flash = useCallback((text: string) => setToast((t) => ({ text, n: (t?.n ?? 0) + 1 })), []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  // 조작 → 응답 {ok…} 만 · 화면은 뒤따르는 board 이벤트로 바뀐다(§7.5). 되돌리기 없음(D-28)
  const run = useCallback(
    async (fn: () => Promise<unknown>, msg?: string) => {
      try {
        await fn();
        if (msg) flash(msg);
        return true;
      } catch (e) {
        if (e instanceof api.ApiError && e.status === 401) {
          clearSession();
          return false;
        }
        flash(e instanceof Error ? e.message : '요청을 처리하지 못했어요');
        return false;
      }
    },
    [flash],
  );

  // 응답 뒤 「같음」이 성립하는 첫 스냅샷부터 서버 순서(§5.12 ②) — 렌더 중에 확인해 로컬 순서를 놓는다
  if (local?.saved && board && sameOrder(board.cards, local.saved)) setLocal(null);

  // 놓기 → 로컬 순서 → PUT(전체 순서 · 필터로 숨긴 카드 포함). 마지막 요청만 본다 · 앞선 요청의 응답 · 실패는 무시
  const saveOrder = async (ids: number[]) => {
    const req = ++reqNo.current;
    setLocal({ req, ids, saved: null });
    try {
      const res = await api.putBoardOrder(ids);
      if (req !== reqNo.current) return;
      setLocal({ req, ids, saved: res.visitIds });
      setTimeout(() => setLocal((l) => (l && l.req === req ? null : l)), SETTLE_MS);
    } catch (e) {
      if (req !== reqNo.current) return;
      // 실패(가짜 보드 403 fake_board 포함 · 예외 없음) = 오류 토스트 + 바로 스냅샷 순서(§5.12 ④ · §6.3)
      setLocal(null);
      if (e instanceof api.ApiError && e.status === 401) {
        clearSession();
        return;
      }
      flash(e instanceof Error ? e.message : '요청을 처리하지 못했어요');
    }
  };

  if (!session) return null;

  const selectTab = (t: TabId) => {
    // 탭을 옮기면 필터 · 고른 카드 모두 풀림(r3 #20)
    setTab(t);
    setFocus(null);
    setFilter('all');
  };

  const act = {
    onPick: (c: Card) => (ids: number[]) => setPicks((x) => ({ ...x, [c.visitId]: ids })),
    onAnes: (c: Card) =>
      void run(
        () => (c.anesthesia.canEnd ? api.anesEnd(c.visitId) : api.anesStart(c.visitId)),
        c.room.title + (c.anesthesia.canEnd ? ' 마취 종료' : ' 마취 시작'),
      ),
    onStart: (_c: Card, p: Procedure) => void run(() => api.startProcedure(p.id)),
    onFinish: (_c: Card, p: Procedure) => void run(() => api.finishProcedure(p.id)),
    onHome: (c: Card) => void run(() => api.goHome(c.visitId), c.room.title + ' ' + c.customer.name + ' 귀가 대기'),
    onOpenCall: (c: Card, rect: DOMRect | null) => {
      const ids = (picks[c.visitId] ?? []).filter((id) => procsOf(c).some((p) => p.id === id && p.pickable));
      if (!ids.length) return;
      setDraft({ visitId: c.visitId, procedureIds: ids, ...placePopover(rect) });
    },
  };

  const sendCall = async (target: CallTarget, label: string) => {
    if (!draft || !board) return;
    const d = draft;
    const c = board.cards.find((x) => x.visitId === d.visitId);
    setDraft(null);
    const ok = await run(() => api.createCall(d.visitId, d.procedureIds, target), (c?.room.title ?? '') + ' ' + d.procedureIds.length + '개 시술 · ' + label);
    // 보낸 뒤 카드 체크 비움(r3 #25)
    if (ok) setPicks((x) => ({ ...x, [d.visitId]: [] }));
  };
  const accept = (k: OpenCall, doctorId: number) => void run(() => api.acceptCall(k.callId, doctorId));
  const reassign = (k: OpenCall) => void run(() => api.reassignAll(k.callId));

  const draftCard = draft && board ? board.cards.find((c) => c.visitId === draft.visitId) : undefined;
  // 카드 순서 = 스냅샷 cards[] 그대로 + 놓은 뒤 응답까지 로컬 순서(§5.12) · 끄는 동안 미리보기(드래그 시작 순서 기준 방향 따라)
  const ordered = board ? withLocalOrder(board.cards, local?.ids ?? null) : [];
  // 미리보기는 DOM 순서를 그대로 두고 격자 order 로만 옮겨 그린다 — 끄는 동안 카드 노드를 옮기지 않는다
  const preview = drag && drag.over != null ? withLocalOrder(ordered, moveCard(drag.start, drag.from, drag.over)) : ordered;
  const slot = new Map(preview.map((c, i) => [c.visitId, i]));
  const cards = board ? ordered.filter(filterFn(filter, board)) : [];
  const dragOf = (c: Card) => {
    const order = slot.get(c.visitId) ?? 0;
    if (c.state === 'home') return { dragging: false, order }; // 귀가 대기 = 끌기 · 놓기 모두 없음(§5.12)
    return {
      dragging: drag?.from === c.visitId,
      order,
      onStart: () => setDrag({ from: c.visitId, start: liveIds(ordered), over: null }),
      onOver: () => {
        if (drag && drag.from !== c.visitId && drag.over !== c.visitId) setDrag({ ...drag, over: c.visitId });
      },
      onDrop: () => {
        if (!drag) return;
        const target = drag.over ?? c.visitId;
        setDrag(null);
        if (target === drag.from) return;
        const ids = moveCard(drag.start, drag.from, target);
        if (ids.every((id, i) => id === drag.start[i])) return;
        void saveOrder(ids);
      },
      // 놓지 않고 끝남(판 밖 · 취소) = 원래 순서
      onEnd: () => setDrag(null),
    };
  };

  return (
    <div
      data-screen-label="시술 현황판 v2"
      style={{ display: 'flex', flexDirection: 'column', height: `calc(100vh - ${HEADER_H}px)`, background: 'var(--ms-gray-100, #f5f6f8)' }}
    >
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <main
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            padding: wide ? '20px 28px' : 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            overflow: 'hidden',
          }}
        >
          {/* 제목 줄 — 시술 현황 · 마지막 KOS 동기화 · 조회 시간 밖 · 동기화 실패 · 범례 5(§6.2 · 시안 M:781-800) */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px 24px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
              <h1 className="text-typo-title-md-600 text-ms-gray-800" style={{ margin: 0, whiteSpace: 'nowrap' }}>
                시술 현황
              </h1>
              <span className="text-typo-body-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                마지막 KOS 동기화 {board?.sync.lastOkAt ? hms(board.sync.lastOkAt) : '—'}
              </span>
              {board && !board.sync.inWindow && (
                <span className="text-typo-caption-md-500 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                  조회 시간 밖
                </span>
              )}
              {board?.sync.lastError && (
                <span className="text-typo-caption-md-600 text-red" title={board.sync.lastError} style={{ whiteSpace: 'nowrap' }}>
                  동기화 실패
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px 20px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                {LEGEND.map((k) => (
                  <Badge key={k.name} variant={k.variant} size="sm" dot>
                    {k.name}
                  </Badge>
                ))}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0 }}>
            {/* 가운데 — 흰 판 안 회색 격자 · 칸 = 오더지 카드 */}
            <div
              className="bg-ms-white"
              style={{
                flex: 1,
                minWidth: 0,
                borderRadius: 12,
                padding: 12,
                // 판 = 크기 컨테이너 — 안의 격자가 판의 보이는 높이(cqh)로 줄 최소 높이를 잡는다(카드 수 · 내용과 무관)
                containerType: 'size',
                display: 'flex',
                overflow: 'auto',
                boxShadow: '0px 2px 10px 0px rgba(0,0,0,0.04)',
              }}
            >
              {board ? (
                <div
                  className="bg-ms-gray-100"
                  style={{
                    flex: 1,
                    alignSelf: 'flex-start',
                    minHeight: '100%',
                    boxSizing: 'border-box',
                    borderRadius: 8,
                    padding: 'var(--grid-pad)',
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
                    // 줄 높이 = 판 보이는 높이의 절반을 최소로, 내용이 더 길면 그 줄의 가장 긴 카드만큼(시안 stretch). 좁은 화면은 내용 높이
                    ...(wide ? { gridAutoRows: 'minmax(calc((100cqh - var(--grid-pad) * 2 - var(--grid-gap)) / 2), auto)' } : null),
                    gap: 'var(--grid-gap)',
                    ...({ '--grid-pad': '6px', '--grid-gap': '8px' } as React.CSSProperties),
                    alignItems: 'stretch',
                    alignContent: 'start',
                  }}
                >
                  {cards.map((c) => (
                    <OrderCard
                      key={c.visitId}
                      board={board}
                      card={c}
                      now={now}
                      picks={picks[c.visitId] ?? []}
                      focus={focus}
                      act={{ ...act, onPick: act.onPick(c) }}
                      drag={dragOf(c)}
                    />
                  ))}
                  {!cards.length && (
                    <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>
                      {board.cards.length ? '조건에 맞는 고객 없음' : '시술 대기 중인 고객 없음'}
                    </span>
                  )}
                </div>
              ) : (
                <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>
                  {live.error ?? (live.connected ? '불러오는 중…' : '서버에 연결하는 중…')}
                </span>
              )}
            </div>
            {board && wide && (
              <Aside
                board={board}
                now={now}
                ordered={ordered}
                tab={tab}
                onTab={selectTab}
                filter={filter}
                onFilter={setFilter}
                focus={focus}
                onFocus={setFocus}
                onAccept={accept}
                onReassign={reassign}
              />
            )}
          </div>

          {toast && (
            <div
              className="bg-ms-gray-800 text-ms-white"
              style={{
                position: 'fixed',
                left: '50%',
                bottom: 28,
                transform: 'translateX(-50%)',
                zIndex: 9999,
                borderRadius: 10,
                padding: '10px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                boxShadow: '0 6px 20px rgba(0,0,0,0.18)',
              }}
            >
              <span className="text-typo-body-500" style={{ whiteSpace: 'nowrap' }}>
                {toast.text}
              </span>
            </div>
          )}
        </main>
      </div>

      {board && draft && draftCard && (
        <CallPopover key={draft.visitId} board={board} card={draftCard} draft={draft} onClose={() => setDraft(null)} onSubmit={(t, l) => void sendCall(t, l)} />
      )}
    </div>
  );
}
