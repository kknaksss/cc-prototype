'use client';

import { useState } from 'react';
import { Badge, Button, Modal } from '@medisolve-ai/medikit';
import {
  LAYOUT,
  RLABEL,
  ROLE_DOT,
  ROLE_ORDER,
  STATUS,
  canPlace,
  capOf,
  custIn,
  isSleep,
  pickCls,
  presentIn,
  queuedIn,
  roomName,
  statusOf,
  stepView,
  taskAt,
} from '@/lib/board';
import { fmtElapsed } from '@/lib/time';
import type { Board, MutationResult, Role } from '@/lib/types';
import * as api from '@/lib/api';
import { usePatientInfo } from './usePatientInfo';

type Run = (fn: () => Promise<MutationResult>, text: string | null) => Promise<void>;

const line = { borderBottomWidth: 1, borderBottomStyle: 'solid' } as const;
const dot8 = { width: 8, height: 8, borderRadius: '50%' } as const;

function StepList({ order, step, size }: { order: Board['customers'][number]['order']; step: number; size: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {order.map((s, i) => {
        const v = stepView(s, i, step);
        return (
          <div
            key={i}
            style={{ display: 'grid', gridTemplateColumns: `${size}px minmax(0,1fr) auto`, gap: 8, alignItems: 'center' }}
          >
            <span
              className={v.numCls}
              style={{
                width: size,
                height: size,
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
              {v.n}
            </span>
            <span className={v.textCls}>{v.label}</span>
            <span className="text-typo-caption-md-400 text-ms-gray-500">{v.role}</span>
          </div>
        );
      })}
    </div>
  );
}

// 방 패널 — 시안 panelVals(점유된 방 · 빈 방 넣기 · 라운지)
export function RoomPanel({
  board,
  now,
  id,
  onClose,
  run,
}: {
  board: Board;
  now: number;
  id: string;
  onClose: () => void;
  run: Run;
}) {
  const [role, setRole] = useState<Role | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const rn = (r: string | null) => roomName(r, board.rooms);
  const cs = custIn(board, id);
  const info = usePatientInfo(cs.map((c) => c.scheduleId));
  const isLounge = id === 'lounge';
  const isOcc = !isLounge && cs.length > 0;
  const isPlace = !isLounge && !isOcc;
  const st = statusOf(board, id);

  const nameOf = (scheduleId: string) => board.customers.find((c) => c.scheduleId === scheduleId)?.name ?? '';
  const doPlace = (scheduleId: string, room: string) =>
    run(() => api.place(scheduleId, room), nameOf(scheduleId) + ' → ' + rn(room));

  let body: React.ReactNode = null;
  if (isOcc) {
    const need = cs[0].order[cs[0].step];
    const curRole: Role = role || (need ? need.role : '코디');
    const pres = presentIn(board, id);
    const q = queuedIn(board, id);
    const pool = board.staff
      .filter((s) => s.role === curRole)
      .sort((a, b) => a.queue.length - b.queue.length);
    body = (
      <>
        {cs.map((c) => {
          const p = info[c.scheduleId];
          const step = c.order[c.step];
          const needSleep = !!(step && step.kind === 'sleep' && !isSleep(c.room));
          const sleepRooms = needSleep ? ['s01', 's02', 's03'].filter((r) => canPlace(board, r)) : [];
          return (
            <div
              key={c.scheduleId}
              className="bg-ms-gray-100"
              style={{ borderRadius: 10, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                <span className="text-typo-heading-md-500 text-ms-gray-800">{c.name}</span>
                <span className="text-typo-caption-md-400 text-ms-gray-600">{p?.meta ?? ''}</span>
              </div>
              {p && p.cautions.length > 0 && (
                <span className="text-typo-caption-md-500 text-red">주의 · {p.cautions.join(' · ')}</span>
              )}
              <StepList order={c.order} step={c.step} size={20} />
              {needSleep && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span className="text-typo-caption-md-600 text-primary">수면실로 이동</span>
                  {sleepRooms.map((r) => (
                    <Button key={r} variant="outlined" color="blue" size="sm" onClick={() => void doPlace(c.scheduleId, r)}>
                      {rn(r)}
                    </Button>
                  ))}
                  {!sleepRooms.length && (
                    <span className="text-typo-caption-md-400 text-ms-gray-600">빈 수면실 없음</span>
                  )}
                </div>
              )}
            </div>
          );
        })}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">현재 방에 있는 직원</span>
          {pres.map((s) => (
            <div
              key={s.staffId}
              className="border-ms-gray-200"
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', ...line }}
            >
              <span className={ROLE_DOT[s.role]} style={dot8} />
              <span className="text-typo-body-600 text-ms-gray-800">{s.name}</span>
              <span className="text-typo-caption-md-400 text-ms-gray-600">{RLABEL[s.role]}</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <Button
                  variant="outlined"
                  color="gray"
                  size="sm"
                  onClick={() => void run(() => api.removeStaff(s.staffId, id), s.name + ' 배정 해제 · ' + rn(id))}
                >
                  빼기
                </Button>
                <Button
                  variant="solid"
                  color="blue"
                  size="sm"
                  onClick={() => void run(() => api.complete(s.staffId, id), s.name + ' 완료 · ' + rn(id))}
                >
                  완료
                </Button>
              </div>
            </div>
          ))}
          {!pres.length && (
            <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '4px 0' }}>
              아직 들어온 직원이 없어요 · {need ? '필요: ' + RLABEL[need.role] + ' · ' + need.label : ''}
            </span>
          )}
          {q.length > 0 && (
            <>
              <span className="text-typo-caption-md-600 text-ms-gray-700" style={{ paddingTop: 6 }}>
                배정 대기
              </span>
              {q.map((s) => (
                <div key={s.staffId} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
                  <span className={ROLE_DOT[s.role]} style={{ ...dot8, opacity: 0.6 }} />
                  <span className="text-typo-body-500 text-ms-gray-800">{s.name}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">
                    {RLABEL[s.role] + ' · 앞 순서 ' + s.queue.indexOf(id) + '건 · 지금 ' + rn(s.queue[0])}
                  </span>
                  <div style={{ marginLeft: 'auto' }}>
                    <Button
                      variant="text"
                      color="gray"
                      size="sm"
                      onClick={() => void run(() => api.removeStaff(s.staffId, id), s.name + ' 배정 해제 · ' + rn(id))}
                    >
                      취소
                    </Button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">직원 배정하기</span>
            <span className="text-typo-caption-md-400 text-ms-gray-600">바쁜 직원은 큐 뒤에 쌓여요</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 6 }}>
            {ROLE_ORDER.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRole(r)}
                className={pickCls(r === curRole)}
                style={{
                  borderWidth: 1,
                  borderStyle: 'solid',
                  borderRadius: 8,
                  height: 36,
                  cursor: 'pointer',
                  font: 'inherit',
                  fontSize: 14,
                  fontWeight: 500,
                }}
              >
                {RLABEL[r]}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {pool.map((s) => {
              const inQ = s.queue.indexOf(id);
              const free = !s.queue.length;
              const n = s.queue.length;
              return (
                <div
                  key={s.staffId}
                  className="border-ms-gray-200"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 0',
                    minHeight: 44,
                    boxSizing: 'border-box',
                    ...line,
                  }}
                >
                  <span className={ROLE_DOT[s.role]} style={{ ...dot8, flexShrink: 0 }} />
                  <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                    {s.name}
                  </span>
                  <span
                    className={
                      free
                        ? 'text-typo-caption-md-500 text-primary'
                        : s.queue.length > 2
                          ? 'text-typo-caption-md-500 text-red'
                          : 'text-typo-caption-md-400 text-ms-gray-600'
                    }
                    style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {free
                      ? '비어있음'
                      : rn(s.queue[0]) +
                        taskAt(board, s.queue[0]) +
                        (s.queue.length > 1 ? ' · 대기 ' + (s.queue.length - 1) + '건' : '')}
                  </span>
                  <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
                    {inQ < 0 ? (
                      <Button
                        variant="outlined"
                        color="blue"
                        size="sm"
                        onClick={() =>
                          void run(
                            () => api.assign(s.staffId, id),
                            s.name + ' → ' + rn(id) + (n ? ' (대기 ' + n + '건 뒤)' : ''),
                          )
                        }
                      >
                        배정
                      </Button>
                    ) : (
                      <span className="text-typo-caption-md-500 text-primary">
                        {inQ === 0 ? '방에 있음' : '배정됨 · ' + inQ + '건 뒤'}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </>
    );
  }

  if (isPlace) {
    const sleep = isSleep(id);
    const free = canPlace(board, id);
    const cands = free
      ? board.customers.filter((c) => {
          if (c.done) return false;
          const s = c.order[c.step];
          return sleep ? !!(s && s.kind === 'sleep' && !isSleep(c.room)) : c.room === 'lounge';
        })
      : [];
    const away = board.customers.find((c) => !c.done && c.prev === id);
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span className="text-typo-caption-md-600 text-ms-gray-700">
          {sleep ? '수면 시술 고객 넣기' : '라운지 대기 고객 넣기'}
        </span>
        {cands.map((c) => (
          <div
            key={c.scheduleId}
            className="border-ms-gray-200"
            style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', ...line }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span className="text-typo-body-600 text-ms-gray-800">{c.name}</span>
                <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {c.room === 'lounge' ? '라운지 대기 ' + fmtElapsed(c.since, now) : rn(c.room)}
                </span>
              </div>
              <span className="text-typo-caption-md-400 text-ms-gray-700">{c.order.map((s) => s.label).join(' → ')}</span>
            </div>
            <Button variant="solid" color="blue" size="sm" onClick={() => void doPlace(c.scheduleId, id)}>
              넣기
            </Button>
          </div>
        ))}
        {!cands.length && (
          <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '4px 0' }}>
            {away
              ? away.name + ' 님이 수면 시술 후 돌아올 방이에요'
              : sleep
                ? '수면 시술을 기다리는 고객이 없어요'
                : '라운지에 대기 중인 고객이 없어요'}
          </span>
        )}
      </div>
    );
  }

  if (isLounge) {
    const picked = pick && cs.some((c) => c.scheduleId === pick) ? pick : null;
    const freeRooms = LAYOUT.filter((r) => /^(c\d|t\d)/.test(r.id) && canPlace(board, r.id));
    body = (
      <>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">대기 고객 · 선택 후 관리실 배정</span>
          {cs.map((c) => (
            <div
              key={c.scheduleId}
              onClick={() => setPick(c.scheduleId)}
              className={pickCls(pick === c.scheduleId)}
              style={{
                borderWidth: 1,
                borderStyle: 'solid',
                borderRadius: 8,
                padding: '10px 12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                <span className="text-typo-body-600 text-ms-gray-800">{c.name}</span>
                <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  대기 {fmtElapsed(c.since, now)}
                </span>
              </div>
              <span className="text-typo-caption-md-400 text-ms-gray-700">{c.order.map((s) => s.label).join(' → ')}</span>
            </div>
          ))}
          {!cs.length && <span className="text-typo-body-400 text-ms-gray-500">라운지에 대기 중인 고객이 없어요</span>}
        </div>
        {picked && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700">{nameOf(picked)} 님 배정할 관리실</span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))', gap: 6 }}>
              {freeRooms.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => {
                    setPick(null);
                    void doPlace(picked, r.id);
                  }}
                  className="cc-free-room bg-ms-white border-ms-gray-300 text-ms-gray-800"
                  style={{
                    borderWidth: 1,
                    borderStyle: 'solid',
                    borderRadius: 8,
                    padding: '8px 10px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    gap: 2,
                    cursor: 'pointer',
                    font: 'inherit',
                    textAlign: 'left',
                  }}
                >
                  <span className="text-typo-caption-md-600">{rn(r.id)}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">
                    {capOf(r.id) > 1 ? custIn(board, r.id).length + '/2명' : '비어있음'}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <Modal isOpen onBackdropClick={onClose}>
      <div
        style={{
          width: 'min(600px, calc(100vw - 64px))',
          maxHeight: 'min(780px, calc(100vh - 96px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
          overflow: 'auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span className="text-typo-title-sm-600 text-ms-gray-800">{rn(id)}</span>
            {st && (
              <Badge variant={STATUS[st.key].variant} size="sm" dot>
                {STATUS[st.key].name}
              </Badge>
            )}
            <span className="text-typo-body-500 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {isOcc ? fmtElapsed(cs[0].since, now) : ''}
            </span>
          </div>
          <Button variant="text" color="gray" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>
        {body}
      </div>
    </Modal>
  );
}

