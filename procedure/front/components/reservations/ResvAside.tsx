'use client';

// 오른쪽 패널(SPEC-005 §6.4 · 시안 M:164-243) — 폭 340 · 넓은 화면만
// 「예약 요청」 = 그 날짜 KOS 공지 하나(제자리 편집 [수정하기] — §5.15) + 예약 요청 자리(빈 상태 · D-07) / 「원내 현황」 = 오늘만 · 구역별 묶음 · 필터 5 · 금액 3칸
import { useState } from 'react';
import { Badge, Button, Tabs, Textarea, type BadgeVariant } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import type { ClinicItem, ResvBoard, ResvMain, ResvNotice } from '@/lib/types';
import { Flag, moneyOf, phaseOfSub, phaseStyle, stateText } from './view';

export type ResvTab = 'requests' | 'clinic';
const TABS = [
  { id: 'requests', name: '예약 요청' },
  { id: 'clinic', name: '원내 현황' },
];

// 필터 = 전체 · 접수 · 상담 · 시술 · 귀가 대기(2계층 주 상태 — §6.4 · §6.8 #7). 3칸 + 2칸
type ClinicFilter = 'all' | 'reception' | 'consultation' | 'procedure' | 'home';
const FILTERS: { id: ClinicFilter; name: string; dot: string }[] = [
  { id: 'all', name: '전체', dot: 'bg-ms-gray-300' },
  { id: 'reception', name: '접수', dot: 'bg-yellow' },
  { id: 'consultation', name: '상담', dot: 'bg-cons' },
  { id: 'procedure', name: '시술', dot: 'bg-primary' },
  { id: 'home', name: '귀가 대기', dot: 'bg-ms-gray-600' },
];

// 공지 영역 = 패널 높이의 이 비율(시안 420 고정 → 화면 높이에 비례 · E2E #20 「지금보다 크게」)
const NOTICE_SHARE = '55%';
const NOTICE_MAX = 2000; // 공지 글자 수 상한(trim 길이 — §5.15 · KOS 웹과 같음)

const BADGE: Partial<Record<ResvMain, BadgeVariant>> = { reception: 'warning', consultation: 'primary', procedure: 'primary', home: 'neutral' };

export function ResvAside({
  board,
  tab,
  onTab,
  onOpen,
  draft,
  onDraft,
  isShownDate,
  onNoticeSaved,
  onToast,
  onError,
}: {
  board: ResvBoard;
  tab: ResvTab;
  draft: NoticeDraft | null;
  onDraft: (d: NoticeDraft | null) => void;
  isShownDate: (date: string) => boolean; // 지금 보는 날짜인가 — 늦은 다시 읽기 응답 거르기(리뷰 r3 W3)
  onTab: (t: ResvTab) => void;
  onOpen: (reservationId: number) => void;
  onNoticeSaved: () => void;
  onToast: (text: string) => void;
  onError: (e: unknown) => void;
}) {
  const [filter, setFilter] = useState<ClinicFilter>('all');
  const select = (t: string) => {
    // 탭을 옮기면 필터는 「전체」로(시안)
    setFilter('all');
    onTab(t as ResvTab);
  };
  return (
    <aside
      className="bg-ms-white"
      style={{ display: 'flex', width: 340, flexShrink: 0, borderRadius: 12, flexDirection: 'column', minHeight: 0, boxSizing: 'border-box', boxShadow: '0px 0px 10px 0px rgba(0,0,0,0.09)' }}
    >
      <div style={{ padding: '8px 16px 0' }}>
        <Tabs tabs={TABS} selectedTab={tab} onSelectTab={select} />
      </div>
      {tab === 'requests' ? (
        <RequestsTab
          key={board.date}
          board={board}
          draft={draft?.date === board.date ? draft : null}
          onDraft={onDraft}
          isShownDate={isShownDate}
          onNoticeSaved={onNoticeSaved} onToast={onToast} onError={onError} />
      ) : (
        <ClinicTab board={board} filter={filter} onFilter={setFilter} onOpen={onOpen} />
      )}
    </aside>
  );
}

// 공지 편집 상태 — noticeId = 다시 읽은 그 날 첫 공지의 ccc 행 id(없으면 null · 기록용)
// 편집 글자는 페이지가 든다 — 탭을 옮겨도 남고, 날짜를 옮기면 페이지가 버린다 + 토스트(추가 지시 1)
export interface NoticeDraft {
  date: string;
  noticeId: number | null;
  text: string;
}

function RequestsTab({
  board,
  draft,
  onDraft: setDraft,
  isShownDate,
  onNoticeSaved,
  onToast,
  onError,
}: {
  board: ResvBoard;
  draft: NoticeDraft | null;
  onDraft: (d: NoticeDraft | null) => void;
  isShownDate: (date: string) => boolean;
  onNoticeSaved: () => void;
  onToast: (text: string) => void;
  onError: (e: unknown) => void;
}) {
  const [busy, setBusy] = useState<'open' | 'save' | null>(null);
  // 저장 직후 응답의 공지를 다음 표 응답이 올 때까지 보인다(그 사이 앞 내용이 번쩍이지 않게)
  const [saved, setSaved] = useState<{ base: ResvBoard; notice: ResvNotice | null } | null>(null);
  const notice = saved && saved.base === board ? saved.notice : (board.notices[0] ?? null); // 그 날 공지 하나 = 첫 번째(§5.15)
  const editable = board.noticeEditable;
  const len = draft ? draft.text.trim().length : 0;
  const over = len > NOTICE_MAX;

  // [수정하기] — 그 날 공지를 다시 불러 편집 시작(누를 때 다시 읽기 — KOS 웹과 같음 · §5.15)
  const open = async () => {
    setBusy('open');
    try {
      const date = board.date;
      const b = await api.reservationBoard(date);
      if (!isShownDate(date)) return; // 응답 전에 날짜를 옮겼으면 버린다(리뷰 r3 W3)
      const n = b.notices[0] ?? null;
      setDraft({ date, noticeId: n?.id ?? null, text: n?.content ?? '' });
    } catch (e) {
      onError(e);
    } finally {
      setBusy(null);
    }
  };
  // [저장] — 빈 내용 = 지우기(back 이 정함). 실패면 편집 상태 그대로(쓴 글자 유지)
  const save = async () => {
    if (!draft || over) return;
    setBusy('save');
    try {
      const r = await api.saveNotice(board.date, draft.noticeId, draft.text);
      setSaved({ base: board, notice: r.notice });
      setDraft(null);
      onToast('공지를 저장했어요');
      onNoticeSaved();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      {/* 공지사항 — 그 날짜 KOS 공지 하나(첫 번째 · §5.15) · 오늘 · 앞날만 [수정하기] → 제자리 편집 · 「저장」 · [취소] · 글자 수
          높이 = 패널의 고정 비율(공지 없어도 자리 유지 · 넘치면 안에서 스크롤 — E2E #5 · #20) · 시각 글자 없음(E2E #19)
          편집 중에는 10초 폴링이 공지 칸을 덮지 않는다(편집 글자는 이 칸의 상태) */}
      <div style={{ flex: `0 0 ${NOTICE_SHARE}`, minHeight: 0, boxSizing: 'border-box', padding: '12px 16px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, minHeight: 32 }}>
          <span className="text-typo-heading-sm-600 text-ms-gray-800">공지사항</span>
          {draft ? (
            <div style={{ display: 'flex', gap: 6 }}>
              <Button variant="text" color="gray" size="sm" disabled={busy !== null} onClick={() => setDraft(null)}>
                취소
              </Button>
              <Button variant="outlined" color="blue" size="sm" disabled={busy !== null || over} onClick={() => void save()}>
                {busy === 'save' ? '저장 중…' : '저장'}
              </Button>
            </div>
          ) : (
            editable && (
              <Button variant="outlined" color="gray" size="sm" disabled={busy !== null} onClick={() => void open()}>
                {busy === 'open' ? '불러오는 중…' : '수정하기'}
              </Button>
            )
          )}
        </div>
        {draft ? (
          <>
            <Textarea
              aria-label="공지 내용"
              autoFocus
              value={draft.text}
              onChange={(e) => setDraft({ ...draft, text: e.target.value })}
              placeholder="이 날짜 공지를 적어 주세요 · 비우고 저장하면 공지가 지워져요"
              isError={over}
              containerClassName="flex-1 min-h-0"
              textareaClassName="text-ms-gray-800"
            />
            <span className={'text-typo-caption-md-400 ' + (over ? 'text-red' : 'text-ms-gray-500')} style={{ alignSelf: 'flex-end', fontVariantNumeric: 'tabular-nums' }}>
              {len.toLocaleString()} / {NOTICE_MAX.toLocaleString()}
            </span>
          </>
        ) : (
          <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
            {notice ? (
              <span className="text-typo-body-400 text-ms-gray-800" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {notice.content}
              </span>
            ) : (
              <span className="text-typo-body-400 text-ms-gray-500">이 날짜 공지가 없어요</span>
            )}
          </div>
        )}
      </div>
      {/* 예약 요청 — 자리만(D-07 · 요청 카드 · 승인/반려 없음) */}
      <div
        className="border-ms-gray-200"
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 16px 16px', display: 'flex', flexDirection: 'column', gap: 8, borderTopWidth: 1, borderTopStyle: 'solid' }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span className="text-typo-heading-sm-600 text-ms-gray-800">예약 요청</span>
          <span className="text-typo-body-400 text-ms-gray-500">대기 0건</span>
        </div>
        <span className="text-typo-body-400 text-ms-gray-500">들어온 예약 요청이 없어요</span>
      </div>
    </>
  );
}

function ClinicTab({ board, filter, onFilter, onOpen }: { board: ResvBoard; filter: ClinicFilter; onFilter: (f: ClinicFilter) => void; onOpen: (id: number) => void }) {
  const clinic = board.clinic;
  if (!board.isToday || !clinic)
    return (
      <div style={{ padding: '16px' }}>
        <span className="text-typo-body-400 text-ms-gray-500">오늘만 볼 수 있어요</span>
      </div>
    );
  const items = clinic.items.filter((i) => filter === 'all' || i.state.main === filter);
  // 구역별 묶음 — 구역 order 순 · 0 명인 구역은 그리지 않는다(§6.4 · D-44). 구역 모르는 예약은 맨 끝 「구역 없음」
  const groups = [...board.zones]
    .sort((a, b) => a.order - b.order)
    .map((z) => ({ key: String(z.zoneId), title: z.title, items: items.filter((i) => i.zoneId === z.zoneId) }));
  const orphan = items.filter((i) => !board.zones.some((z) => z.zoneId === i.zoneId));
  if (orphan.length) groups.push({ key: 'none', title: '구역 없음', items: orphan });
  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 16px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', rowGap: 8, flexShrink: 0, margin: '0 0 4px' }}>
        {FILTERS.map((f, i) => {
          const on = filter === f.id;
          return (
            <button
              key={f.id}
              type="button"
              aria-pressed={on}
              onClick={() => onFilter(f.id)}
              className={(on ? 'text-typo-body-600 text-ms-gray-800' : 'text-typo-body-400 text-ms-gray-500') + ' border-ms-gray-300'}
              style={{
                minWidth: 0,
                borderWidth: 0,
                borderLeftWidth: i % 3 ? 1 : 0,
                borderStyle: 'solid',
                background: 'transparent',
                padding: '0 0 0 10px',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                cursor: 'pointer',
                fontFamily: 'inherit',
                whiteSpace: 'nowrap',
              }}
            >
              <span className={f.dot} style={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0 }} />
              <span>{f.name}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{clinic.counts[f.id === 'all' ? 'all' : f.id]}</span>
            </button>
          );
        })}
      </div>
      {groups
        .filter((g) => g.items.length)
        .map((g) => (
          <div key={g.key} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">
              {g.title} {g.items.length}명
            </span>
            {g.items.map((it) => (
              <ClinicCard key={it.reservationId} item={it} onOpen={() => onOpen(it.reservationId)} />
            ))}
          </div>
        ))}
      {!items.length && <span className="text-typo-body-400 text-ms-gray-500">{clinic.items.length ? '조건에 맞는 고객 없음' : '원내 고객 없음'}</span>}
    </div>
  );
}

function ClinicCard({ item, onOpen }: { item: ClinicItem; onOpen: () => void }) {
  const due = item.paymentRequiredCount >= 1;
  const cells = [
    { k: '전체', v: moneyOf(item.amount, 'total'), red: false },
    { k: '결제', v: moneyOf(item.amount, 'paid'), red: false },
    { k: '수납 필요', v: due ? item.paymentRequiredCount + '건' : '-', red: due },
  ];
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen();
      }}
      className="bg-ms-white border-ms-gray-300"
      style={{ flexShrink: 0, borderWidth: 1, borderStyle: 'solid', borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6, cursor: 'pointer' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span className="text-typo-body-600 text-ms-gray-800" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.customer.name}
          </span>
          {item.customer.phoneticName && (
            <span className="text-typo-body-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
              {item.customer.phoneticName}
            </span>
          )}
          <Flag code={item.customer.nationality} />
        </div>
        {due ? (
          <Badge variant="danger" size="sm">
            수납 필요
          </Badge>
        ) : (
          // 부상태 색 규칙(phaseStyle · E2E b3 #3) — 부상태 없으면 대기 꼴
          <Badge variant={BADGE[item.state.main] ?? 'neutral'} size="sm" className={phaseStyle(item.state.main, phaseOfSub(item.state.sub) ?? 'waiting').chip}>
            {stateText(item.state)}
          </Badge>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 4 }}>
        {cells.map((p) => (
          <div key={p.k} className={p.red ? 'bg-red-100' : 'bg-ms-gray-100'} style={{ borderRadius: 6, padding: '4px 8px', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <span className="text-typo-caption-md-400 text-ms-gray-500">{p.k}</span>
            <span
              className={'text-typo-body-600 ' + (p.red ? 'text-red' : p.v === '-' ? 'text-ms-gray-400' : 'text-ms-gray-800')}
              style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {p.v}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
