'use client';

// 오른쪽 패널(SPEC-003 §6.4) — 틀은 cc 기능 front 의 desk Aside(폭 340 · 반경 12 · 그림자 · 검색 · 탭)
import { useState } from 'react';
import { Badge, Button, Tabs } from '@medisolve-ai/medikit';
import { minutesSince, toMs } from '@/lib/time';
import type { Board, Card, OpenCall } from '@/lib/types';
import {
  FILTERS,
  docName,
  needView,
  procSubName,
  procsOf,
  stateBadge,
  stateText,
  visitCls,
  type FilterId,
} from './view';

export type TabId = 'status' | 'calls' | 'customers';
const TABS = [
  { id: 'status', name: '현황' },
  { id: 'calls', name: '호출' },
  { id: 'customers', name: '고객' },
];

const list: React.CSSProperties = { flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 8, padding: '12px 16px' };

export function Aside({
  board,
  now,
  ordered,
  tab,
  onTab,
  filter,
  onFilter,
  focus,
  onFocus,
  onAccept,
  onReassign,
}: {
  board: Board;
  now: number;
  ordered: Card[]; // 카드판과 같은 카드 순서(스냅샷 cards[] · 경합 중이면 로컬 순서 — §6.4)
  tab: TabId;
  onTab: (t: TabId) => void;
  filter: FilterId;
  onFilter: (f: FilterId) => void;
  focus: number | null;
  onFocus: (visitId: number | null) => void;
  onAccept: (k: OpenCall, doctorId: number) => void;
  onReassign: (k: OpenCall) => void;
}) {
  const [q, setQ] = useState('');
  const text = q.trim().toLowerCase().replace(/\s+/g, '');
  // 검색 — 이름 · 읽기 · 차트번호(차트번호는 검색에만 · D-14)
  const hits = text
    ? board.cards.filter((c) =>
        [c.customer.name, c.customer.phoneticName, c.customer.chartNumber].some((v) => (v ?? '').toLowerCase().replace(/\s+/g, '').includes(text)),
      )
    : [];

  return (
    <aside
      className="bg-ms-white"
      style={{
        display: 'flex',
        width: 340,
        maxWidth: 'calc(100vw - 24px)',
        flexShrink: 0,
        borderRadius: 12,
        flexDirection: 'column',
        minHeight: 0,
        boxSizing: 'border-box',
        boxShadow: '0px 0px 10px 0px rgba(0,0,0,0.09)',
      }}
    >
      <div style={{ padding: '12px 16px 0' }}>
        <input
          className="cc-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="고객 검색 — 영문 이름 · 한글 읽기"
          style={{ height: 40, fontSize: 14 }}
        />
      </div>
      {text ? (
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', paddingTop: 8 }}>
          {hits.map((c) => (
            <div
              key={c.visitId}
              onClick={() => {
                setQ('');
                onTab('customers');
                onFocus(c.visitId);
              }}
              className="bg-ms-white border-ms-gray-200"
              style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0,1fr) auto',
                gap: 10,
                alignItems: 'center',
                minHeight: 52,
                boxSizing: 'border-box',
                padding: '8px 16px',
                borderBottomWidth: 1,
                borderBottomStyle: 'solid',
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, flexWrap: 'wrap' }}>
                <span className="text-typo-body-600 text-ms-gray-800">{c.customer.name}</span>
                <span className={visitCls(c.customer.isNew)} style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>
                  {c.customer.isNew ? '첫내원' : '재내원'}
                </span>
              </div>
              <span className="text-typo-caption-md-500 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                {c.room.title} · {stateText(c.state)}
              </span>
            </div>
          ))}
          {!hits.length && (
            <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 16 }}>
              검색 결과 없음
            </span>
          )}
        </div>
      ) : (
        <>
          <div style={{ padding: '8px 16px 0' }}>
            <Tabs tabs={TABS} selectedTab={tab} onSelectTab={(t: string) => onTab(t as TabId)} />
          </div>
          {tab === 'status' && <StatusTab board={board} now={now} filter={filter} onFilter={onFilter} focus={focus} onFocus={onFocus} />}
          {tab === 'calls' && <CallsTab board={board} now={now} focus={focus} onFocus={onFocus} onAccept={onAccept} onReassign={onReassign} />}
          {tab === 'customers' && <CustomersTab board={board} cards={ordered} focus={focus} onFocus={onFocus} />}
        </>
      )}
    </aside>
  );
}

function StatusTab({
  board,
  now,
  filter,
  onFilter,
  focus,
  onFocus,
}: {
  board: Board;
  now: number;
  filter: FilterId;
  onFilter: (f: FilterId) => void;
  focus: number | null;
  onFocus: (visitId: number | null) => void;
}) {
  // 확인이 필요한 고객 — 경과가 긴 순(§5.8)
  const needs = board.cards
    .filter((c): c is Card & { need: NonNullable<Card['need']> } => !!c.need)
    .map((c) => ({ c, v: needView(board, c, c.need, now) }))
    .sort((a, b) => (toMs(a.c.need.since) ?? 0) - (toMs(b.c.need.since) ?? 0));
  return (
    <>
      {/* 상태 수 6칸 = 3 × 2 · 점 · 이름 · 수. 칸 바탕 · 테두리 상자 없음 — 줄의 2 · 3번째 칸만 왼쪽 구분선(§6.4 · 시안 M:945-955) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', rowGap: 8, padding: '14px 12px 10px' }}>
        {FILTERS.map((f, i) => (
          <button
            key={f.id}
            type="button"
            onClick={() => onFilter(f.id)}
            aria-pressed={filter === f.id}
            className={(filter === f.id ? 'text-typo-body-600 text-ms-gray-800' : 'text-typo-body-400 text-ms-gray-500') + ' border-ms-gray-300'}
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
            <span
              className={f.dot}
              style={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0, boxSizing: 'border-box', ...(f.ring ? { borderWidth: 2, borderStyle: 'solid' } : null) }}
            />
            <span>{f.name}</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{board.counts[f.id]}</span>
          </button>
        ))}
      </div>
      <div className="border-ms-gray-200" style={{ borderTopWidth: 1, borderTopStyle: 'solid' }} />
      <div style={list}>
        <span className="text-typo-caption-md-600 text-ms-gray-700">확인이 필요한 고객</span>
        {needs.map(({ c, v }) => {
          const doing = procsOf(c).find((p) => p.state === 'doing');
          const assigned = procsOf(c).find((p) => p.doctor && p.state !== 'done');
          const owner = doing?.doctor?.name ?? assigned?.doctor?.name ?? '미배정';
          return (
            <div
              key={c.visitId}
              onClick={() => onFocus(focus === c.visitId ? null : c.visitId)}
              className={focus === c.visitId ? 'bg-primary-100 border-primary' : 'bg-ms-white border-ms-gray-200'}
              style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6, cursor: 'pointer', flexShrink: 0 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <Badge variant="danger" size="sm" dot>
                    확인 필요
                  </Badge>
                  <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                    {c.room.title}
                  </span>
                </div>
                <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
                  {owner}
                </span>
              </div>
              <span className="text-typo-body-500 text-ms-gray-800">
                {c.customer.name} <span className="text-typo-caption-md-400 text-ms-gray-600">{v.state}</span>
              </span>
              <div className="bg-red-100" style={{ borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                    <span className="text-typo-caption-md-600 text-red">{v.kind}</span>
                    <span className="text-typo-title-sm-600 text-red" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {v.min}분
                    </span>
                  </div>
                  <span className="text-typo-caption-md-600 text-red" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                    {v.overText}
                  </span>
                </div>
                {v.hasLimit && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <div style={{ position: 'relative', height: 6, borderRadius: 3, background: 'var(--ms-red, #e5484d)', overflow: 'hidden' }}>
                      <div className="bg-ms-gray-300" style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: v.barPct }} />
                    </div>
                    <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {v.limitText}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {!needs.length && (
          <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '4px 0' }}>
            확인이 필요한 고객 없음
          </span>
        )}
      </div>
    </>
  );
}

// 호출 탭 = 의국 화면 — 호출 카드 1장 = 호출 1건(받을 시술이 남은 호출 · §6.4 · §6.7 #2). [되돌리기] 없음(D-28)
function CallsTab({
  board,
  now,
  focus,
  onFocus,
  onAccept,
  onReassign,
}: {
  board: Board;
  now: number;
  focus: number | null;
  onFocus: (visitId: number | null) => void;
  onAccept: (k: OpenCall, doctorId: number) => void;
  onReassign: (k: OpenCall) => void;
}) {
  // 전체 호출에서 고른 원장 — 호출 id 마다
  const [picks, setPicks] = useState<Record<number, number>>({});
  // 호출 미수락 기준 = 스냅샷 limits.callMin(back 한 곳)
  const limit = board.limits.callMin;
  const calls = board.calls.slice().sort((a, b) => (toMs(a.createdAt) ?? 0) - (toMs(b.createdAt) ?? 0));
  const docs = board.doctors.slice().sort((a, b) => Number(a.busy) - Number(b.busy));
  const docState = (id: number | null) => {
    const d = board.doctors.find((x) => x.id === id);
    return d?.busy ? { busy: true, text: (d.busyRoom ? d.busyRoom + ' ' : '') + '시술 중' } : { busy: false, text: '비어있음' };
  };
  return (
    <div style={list}>
      <span className="text-typo-caption-md-600 text-ms-gray-700">수락 대기 {calls.length}건</span>
      {calls.map((k) => {
        const min = minutesSince(k.createdAt, now);
        const late = min >= limit;
        const isAll = k.kind === 'all';
        const pick = picks[k.callId] ?? null;
        const pickOk = pick != null && board.doctors.some((d) => d.id === pick);
        const ds = isAll ? null : docState(k.targetDoctorId);
        const on = focus === k.visitId;
        return (
          <div
            key={k.callId}
            onClick={() => onFocus(on ? null : k.visitId)}
            className={on ? (late ? 'bg-primary-100 border-red' : 'bg-primary-100 border-primary') : late ? 'bg-ms-white border-red' : 'bg-ms-white border-ms-gray-200'}
            style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0, cursor: 'pointer' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                <span data-badge-call={isAll ? 'false' : 'true'} style={{ display: 'inline-flex' }}>
                  <Badge variant="primary" size="sm">
                    {isAll ? '전체 호출' : '지정 호출'}
                  </Badge>
                </span>
                <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                  {k.room.title}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, whiteSpace: 'nowrap' }}>
                <span className={late ? 'text-typo-body-600 text-red' : 'text-typo-body-600 text-primary'} style={{ fontVariantNumeric: 'tabular-nums' }}>
                  호출 {min}분
                </span>
                <span className={late ? 'text-typo-caption-md-600 text-red' : 'text-typo-caption-md-400 text-ms-gray-600'} style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {late ? (min - limit > 0 ? '+' + (min - limit) + '분 초과' : '기준 도달') : '기준 ' + limit + '분'}
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              <span className="text-typo-body-500 text-ms-gray-800" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {k.customer.name}
              </span>
              {k.customer.nationality && (
                <span className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700" style={{ flexShrink: 0, padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>
                  {k.customer.nationality}
                </span>
              )}
            </div>
            <div className="bg-ms-gray-100" style={{ borderRadius: 6, padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
              {k.procedures.map((p) => (
                <span key={p.id} className="text-typo-caption-md-500 text-ms-gray-800" style={{ wordBreak: 'keep-all' }}>
                  · {p.title}
                </span>
              ))}
            </div>
            {isAll ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="text-typo-caption-md-600 text-ms-gray-700">담당의 선택</span>
                {docs.map((d) => {
                  const st = docState(d.id);
                  return (
                    <div
                      key={d.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        setPicks((x) => ({ ...x, [k.callId]: d.id }));
                      }}
                      className={pick === d.id ? 'bg-primary-100 border-primary' : 'bg-ms-white border-ms-gray-200'}
                      style={{
                        borderWidth: 1,
                        borderStyle: 'solid',
                        borderRadius: 8,
                        padding: '6px 10px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        cursor: 'pointer',
                        minHeight: 36,
                        boxSizing: 'border-box',
                      }}
                    >
                      <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: '#ac47ff' }} />
                      <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                        {d.name}
                      </span>
                      <span
                        className={st.busy ? 'text-typo-caption-md-400 text-ms-gray-600' : 'text-typo-caption-md-500 text-primary'}
                        style={{ marginLeft: 'auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      >
                        {st.text}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="text-typo-caption-md-600 text-ms-gray-700">지정</span>
                <span className="text-typo-body-600 text-ms-gray-800">{docName(board, k.targetDoctorId)}</span>
                <span
                  className={ds && !ds.busy ? 'text-typo-caption-md-500 text-primary' : 'text-typo-caption-md-400 text-ms-gray-600'}
                  style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                >
                  {ds?.text}
                </span>
              </div>
            )}
            <div
              data-fill-buttons="true"
              onClick={(e) => e.stopPropagation()}
              style={{ display: 'grid', gridTemplateColumns: isAll ? 'minmax(0,1fr)' : 'minmax(0,1fr) minmax(0,1fr)', gap: 6 }}
            >
              {!isAll && (
                <Button variant="outlined" color="gray" size="sm" onClick={() => onReassign(k)}>
                  다른 원장에게
                </Button>
              )}
              <Button
                variant="solid"
                color="blue"
                size="sm"
                disabled={isAll && !pickOk}
                onClick={() => {
                  const id = isAll ? pick : k.targetDoctorId;
                  if (id != null) onAccept(k, id);
                }}
              >
                {isAll ? (pickOk ? docName(board, pick) + ' 수락' : '원장 선택 후 수락') : '수락'}
              </Button>
            </div>
          </div>
        );
      })}
      {!calls.length && (
        <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '4px 0' }}>
          수락 대기 중인 호출 없음
        </span>
      )}
      {board.recentAccepts.length > 0 && (
        <>
          <span className="text-typo-caption-md-600 text-ms-gray-500" style={{ paddingTop: 8 }}>
            최근 수락
          </span>
          {board.recentAccepts.slice(0, 3).map((r, i) => (
            <div
              key={r.at + ':' + i}
              className="border-ms-gray-200"
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottomWidth: 1, borderBottomStyle: 'solid', opacity: 0.7 }}
            >
              <span className="text-typo-caption-md-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                {r.room}
              </span>
              <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.doctorName} 수락 · {r.count}건
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// 고객 탭 — 고객 줄(상태 배지 · 이름 · 방 / 번호 원 시술 줄) · 귀가 대기까지 · 누르면 그 카드만 남기고 흐림
function CustomersTab({
  board,
  cards,
  focus,
  onFocus,
}: {
  board: Board;
  cards: Card[];
  focus: number | null;
  onFocus: (visitId: number | null) => void;
}) {
  return (
    <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
      {cards.map((c) => (
        <div
          key={c.visitId}
          onClick={() => onFocus(focus === c.visitId ? null : c.visitId)}
          className={focus === c.visitId ? 'bg-primary-100 border-ms-gray-200' : 'bg-ms-white border-ms-gray-200'}
          style={{
            padding: '12px 16px',
            borderBottomWidth: 1,
            borderBottomStyle: 'solid',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            cursor: 'pointer',
            opacity: c.state === 'home' ? 0.55 : 1,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <Badge variant={stateBadge(c.state).variant} size="sm" className={stateBadge(c.state).cls}>
                {stateText(c.state)}
              </Badge>
              <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {c.customer.name}
              </span>
            </div>
            <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ whiteSpace: 'nowrap' }}>
              {c.room.title}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {procsOf(c)
              .sort((a, b) => a.sequence - b.sequence)
              .map((p, i) => {
                const now = p.state === 'doing';
                const past = p.state === 'done';
                const who =
                  p.state === 'wait' && p.call && p.call.acceptedBy == null
                    ? p.call.kind === 'all'
                      ? '호출함 · 전체'
                      : '호출함 · ' + docName(board, p.call.targetDoctorId)
                    : (p.doctor?.name ?? '');
                return (
                  <div key={p.id} style={{ display: 'grid', gridTemplateColumns: '18px minmax(0,1fr) auto', gap: 8, alignItems: 'center' }}>
                    <span
                      className={
                        now
                          ? 'bg-primary border-primary text-ms-white'
                          : past
                            ? 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-500'
                            : 'bg-ms-white border-primary text-primary'
                      }
                      style={{
                        width: 18,
                        height: 18,
                        borderRadius: '50%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 11,
                        fontWeight: 600,
                        boxSizing: 'border-box',
                        borderWidth: 1,
                        borderStyle: 'solid',
                      }}
                    >
                      {i + 1}
                    </span>
                    <span
                      className={
                        now
                          ? 'text-typo-caption-md-600 text-primary'
                          : past
                            ? 'text-typo-caption-md-400 text-ms-gray-500'
                            : 'text-typo-caption-md-400 text-ms-gray-800'
                      }
                      style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      {p.title}
                    </span>
                    <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                      {(who ? who + ' · ' : '') + procSubName(p.state)}
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      ))}
    </div>
  );
}
