'use client';

// 시술 현황판(SPEC-003 §6 · 시안 「Ceramique 시술현황판 v2」 r4). 틀은 cc 기능 front 의 desk 화면(사이드바 Menu · main 여백 · 제목 줄 · 토스트)
import { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Menu } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { useBoardStream, useNow, useSession, useWide } from '@/lib/hooks';
import { clearSession } from '@/lib/session';
import { hms } from '@/lib/time';
import type { Card, CallTarget, OpenCall, Procedure } from '@/lib/types';
import { HEADER_H } from '@/components/common/AppHeader';
import { Aside, type TabId } from '@/components/procedures/Aside';
import { CallPopover, placePopover, type CallDraft } from '@/components/procedures/CallPopover';
import { OrderCard } from '@/components/procedures/OrderCard';
import { LEGEND, filterFn, orderedCards, type FilterId, type SortKey } from '@/components/procedures/view';

const PATH = '/procedures/live';
const icon = (d: string) => (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);
// 사이드바 — 묶음 · 항목 모두 「시술 현황」(§6.2)
const MENUS = [{ name: '시술 현황', href: '/procedures', menus: [{ name: '시술 현황', href: PATH, icon: icon('M3 12h4l3-8 4 16 3-8h4') }] }];

export default function ProceduresLivePage() {
  const session = useSession();
  const live = useBoardStream(session?.token ?? null);
  const board = live.board;
  const now = useNow() + live.skew;
  const wide = useWide();

  const [sort, setSort] = useState<SortKey>('in');
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
      const ids = (picks[c.visitId] ?? []).filter((id) => c.procedures.some((p) => p.id === id && p.pickable));
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
  const cards = board ? orderedCards(board.cards, sort).filter(filterFn(filter, board)) : [];
  const sortBtn = (k: SortKey, name: string) => (
    <Button variant={sort === k ? 'solid' : 'outlined'} color={sort === k ? 'blue' : 'gray'} size="sm" onClick={() => setSort(k)}>
      {name}
    </Button>
  );

  return (
    <div
      data-screen-label="시술 현황판 v2"
      style={{ display: 'flex', flexDirection: 'column', height: `calc(100vh - ${HEADER_H}px)`, background: 'var(--ms-gray-100, #f5f6f8)' }}
    >
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {wide && <Menu menus={MENUS} currentPath={PATH} onMenuClick={(_href: string, e: React.MouseEvent) => e?.preventDefault()} />}
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
          {/* 제목 줄 — 시술 현황 · 마지막 KOS 동기화 · 범례 · [입실순 | 배치순] */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px 24px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
              <h1 className="text-typo-title-md-600 text-ms-gray-800" style={{ margin: 0, whiteSpace: 'nowrap' }}>
                시술 현황
              </h1>
              <span className="text-typo-body-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                명동점 · 마지막 KOS 동기화 {board?.sync.lastOkAt ? hms(board.sync.lastOkAt) : '—'}
              </span>
              {/* 조회 시간 밖 · 동기화 실패 — 시안에 없음(§6.2 기본값) */}
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
              <span className="bg-ms-gray-300" style={{ width: 1, height: 14 }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {sortBtn('in', '입실순')}
                {sortBtn('room', '배치순')}
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
                sort={sort}
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
