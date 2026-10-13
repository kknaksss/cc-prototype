'use client';

import { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Modal } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import {
  KIND_ROLES,
  ROLE_COLOR,
  RTITLE,
  SSTATE,
  STATUS,
  boxKey,
  canPlace,
  capOf,
  custIn,
  hhmm,
  isSleep,
  pickCls,
  roomName,
  won,
} from '@/lib/board';
import { useLive } from '@/lib/hooks';
import { Bundles, FlagChips, MemoList, historyBlocks, hlOf, todayBlocks } from '@/lib/memo';
import { fmtElapsed } from '@/lib/time';
import type { Board, BoardCustomer, MutationResult, PatientDetail, ProcedureCandidate, Step } from '@/lib/types';
import { natName } from '@/components/staff/common';
import { VisitChip } from './Aside';

type Run = (fn: () => Promise<MutationResult>, text: string | null) => Promise<boolean>;

const line = { borderBottomWidth: 1, borderBottomStyle: 'solid' } as const;
const arrowBtn = {
  width: 28,
  height: 28,
  borderRadius: 6,
  borderWidth: 1,
  borderStyle: 'solid',
  background: '#fff',
  cursor: 'pointer',
  font: 'inherit',
  fontSize: 13,
} as const;
const movable = (s: Step) => s.state === 'planned' || s.state === 'assigned';

// 방 패널(§3.2) — 고객이 있으면 고객 중심, 비어 있으면 접수대기실 고객 넣기
export function RoomPanel({
  board,
  now,
  id,
  onClose,
  onSwitch,
  onDischarge,
  run,
}: {
  board: Board;
  now: number;
  id: string;
  onClose: () => void;
  onSwitch: (room: string) => void;
  onDischarge: (c: BoardCustomer) => void;
  run: Run;
}) {
  const rn = (r: string | null) => roomName(r, board.rooms);
  const cs = custIn(board, id);
  const isLounge = id === 'reception';
  const occ = !isLounge && cs.length > 0 ? cs[0] : null;
  const k = occ ? boxKey(occ.status) : null;

  return (
    <Modal isOpen onBackdropClick={onClose}>
      <div
        style={{
          width: occ ? 'min(1100px, calc(100vw - 64px))' : 'min(560px, calc(100vw - 64px))',
          maxHeight: 'min(880px, calc(100vh - 72px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          overflow: 'auto',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span className="text-typo-title-sm-600 text-ms-gray-800">{rn(id)}</span>
            {k && (
              <Badge variant={STATUS[k].variant} size="sm" dot>
                {STATUS[k].name}
              </Badge>
            )}
            <span className="text-typo-body-500 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {occ ? fmtElapsed(occ.since, now) : ''}
            </span>
          </div>
          <Button variant="text" color="gray" size="sm" onClick={onClose}>
            닫기
          </Button>
        </div>
        {occ ? (
          <CustomerPanel
            key={occ.scheduleId}
            board={board}
            now={now}
            c={occ}
            run={run}
            onClose={onClose}
            onSwitch={onSwitch}
            onDischarge={onDischarge}
          />
        ) : isLounge ? (
          <LoungePanel board={board} now={now} run={run} onClose={onClose} />
        ) : (
          <PlacePanel board={board} now={now} id={id} run={run} />
        )}
      </div>
    </Modal>
  );
}

function CustomerPanel({
  board,
  now,
  c,
  run,
  onClose,
  onSwitch,
  onDischarge,
}: {
  board: Board;
  now: number;
  c: BoardCustomer;
  run: Run;
  onClose: () => void;
  onSwitch: (room: string) => void;
  onDischarge: (c: BoardCustomer) => void;
}) {
  const rn = (r: string | null) => roomName(r, board.rooms);
  const load = useCallback(() => api.getPatient(c.scheduleId), [c.scheduleId]);
  const p = useLive<PatientDetail>(load).data;
  const [picking, setPicking] = useState<string | null>(null);
  const [cands, setCands] = useState<ProcedureCandidate[]>([]);
  const [sleep, setSleep] = useState(false);

  // 오늘 시술 후보 — 동선 · 결제가 바뀔 때마다 다시
  useEffect(() => {
    let alive = true;
    api
      .getProcedureCandidates(c.scheduleId)
      .then((x) => alive && setCands(x.filter((y) => y.left > 0)))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [c.scheduleId, board.version]);

  const steps = c.steps;
  const running = steps.some((s) => s.state === 'in_progress');
  const firstM = steps.findIndex(movable);
  let lastM = -1;
  steps.forEach((s, i) => {
    if (movable(s)) lastM = i;
  });
  const roleOf = (staffId: string | null) => board.staff.find((s) => s.staffId === staffId)?.role;
  const who = (staffId: string | null, name: string | null) => {
    const role = roleOf(staffId);
    return name ? (role ? RTITLE[role] + ' ' : '') + name : '';
  };
  const meta = [p?.sex, p && p.age !== null ? p.age + '세' : '', natName(c.nationality), p ? p.reservationTime + ' 예약' : '']
    .filter(Boolean)
    .join(' · ');
  const need = !!c.status?.need;
  const hl = hlOf(board.riskWords, board.staff);
  const mentioned = c.mentionedStaffIds.map((id) => board.staff.find((s) => s.staffId === id)).filter((s): s is Board['staff'][number] => !!s);
  const cstep = steps.find((s) => s.kind === 'consult' && s.state === 'done');

  const move = (i: number, dir: number) => {
    const j = i + dir;
    if (!steps[j] || !movable(steps[i]) || !movable(steps[j])) return;
    const ids = steps.map((s) => s.stepId);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    void run(() => api.reorder(c.scheduleId, ids), '순서 바꿈 · ' + c.name);
  };
  // 셀렉터 — 사람을 고르면 배정, 「미배정」을 고르면 해제(§0-b 7 · #12)
  const setAssignee = (s: Step, staffId: string | null, name: string) => {
    setPicking(null);
    if ((s.assigneeId ?? null) === staffId) return;
    if (!staffId) void run(() => api.unassign(s.stepId), '배정 해제 · ' + s.label);
    else void run(() => api.assign(s.stepId, staffId), name + ' 배정 · ' + s.label);
  };
  const timeOf = (s: Step) =>
    s.state === 'done'
      ? hhmm(s.startedAt) + '–' + hhmm(s.endedAt)
      : s.state === 'in_progress'
        ? hhmm(s.startedAt) + '~ · ' + fmtElapsed(s.startedAt, now)
        : s.state === 'assigned'
          ? '배정 ' + hhmm(s.assignedAt)
          : '';
  const sleepRooms = board.rooms.filter((r) => isSleep(r.id) && canPlace(board, r.id));

  return (
    <>
      <div
        className="bg-ms-gray-100"
        style={{
          borderRadius: 10,
          padding: '12px 14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px 16px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="text-typo-heading-md-500 text-ms-gray-800">{c.name}</span>
          <VisitChip isNew={c.isNew} />
          <span className="text-typo-caption-md-400 text-ms-gray-600">{meta}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className={need ? 'text-typo-body-600 text-red' : 'text-typo-body-500 text-ms-gray-800'}>{c.status?.label}</span>
          {c.prevRoom && <span className="text-typo-caption-md-500 text-primary">원래 방 {rn(c.prevRoom)}</span>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.1fr) minmax(0,1fr)', gap: 16, alignItems: 'start' }}>
        {/* 왼쪽 — 동선 · 작업 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
          {p && <FlagChips riskHits={p.riskHits} mentioned={mentioned} />}
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, paddingBottom: 4 }}>
              <span className="text-typo-caption-md-600 text-ms-gray-700">고객 동선</span>
              <span className="text-typo-caption-md-400 text-ms-gray-600">
                {steps.filter((s) => s.state === 'done').length} / {steps.filter((s) => s.state !== 'skipped').length} 완료
              </span>
            </div>
            {steps.map((s, i) => {
              const ss = SSTATE[s.state];
              const role = roleOf(s.assigneeId);
              const roles = KIND_ROLES[s.kind];
              const locked = !movable(s);
              const pool = board.staff.filter((x) => roles.includes(x.role));
              const top = pool.filter((x) => c.mentionedStaffIds.includes(x.staffId));
              const groups: { group: string; list: typeof pool }[] = [];
              if (top.length) groups.push({ group: '지정', list: top });
              roles.forEach((r) => {
                const rest = pool.filter((x) => x.role === r && !top.includes(x));
                if (rest.length) groups.push({ group: r, list: rest });
              });
              return (
                <div
                  key={s.stepId}
                  data-step={s.stepId}
                  className="border-ms-gray-200"
                  style={{
                    position: 'relative',
                    display: 'grid',
                    gridTemplateColumns: '22px minmax(0,1fr) auto',
                    gap: 8,
                    alignItems: 'center',
                    padding: '8px 0',
                    ...line,
                  }}
                >
                  <StepNum n={i + 1} state={s.state} />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      <span
                        className={
                          s.state === 'skipped'
                            ? 'text-typo-body-400 text-ms-gray-500'
                            : s.state === 'in_progress'
                              ? 'text-typo-body-600 text-primary'
                              : 'text-typo-body-500 text-ms-gray-800'
                        }
                        style={{ overflowWrap: 'anywhere' }}
                      >
                        {s.label}
                      </span>
                      {s.paymentRequired && <PayChip />}
                    </div>
                    <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {timeOf(s)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Badge variant={ss.variant} size="sm" dot={ss.dot}>
                      {ss.name}
                    </Badge>
                    {locked ? (
                      <span style={{ width: 132, boxSizing: 'border-box', padding: '0 8px', display: 'flex', alignItems: 'center', gap: 6 }}>
                        {s.assigneeName && (
                          <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: role ? ROLE_COLOR[role] : '' }} />
                        )}
                        <span
                          className="text-typo-caption-md-500 text-ms-gray-700"
                          style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                        >
                          {who(s.assigneeId, s.assigneeName) || '-'}
                        </span>
                      </span>
                    ) : (
                      <button
                        type="button"
                        data-picker={s.stepId}
                        onClick={() => setPicking(picking === s.stepId ? null : s.stepId)}
                        className={s.assigneeName ? 'border-primary text-ms-gray-800' : 'border-ms-gray-400 text-ms-gray-600'}
                        style={{
                          height: 30,
                          width: 132,
                          boxSizing: 'border-box',
                          borderRadius: 6,
                          borderWidth: 1,
                          borderStyle: 'solid',
                          padding: '0 8px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          background: '#fff',
                          cursor: 'pointer',
                          font: 'inherit',
                        }}
                      >
                        {s.assigneeName && (
                          <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: role ? ROLE_COLOR[role] : '' }} />
                        )}
                        <span className="text-typo-caption-md-500" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {who(s.assigneeId, s.assigneeName) || '미배정'}
                        </span>
                        <span className="text-ms-gray-600" style={{ marginLeft: 'auto', fontSize: 10 }}>
                          ▾
                        </span>
                      </button>
                    )}
                    {!running && movable(s) && (
                      <>
                        <button
                          type="button"
                          onClick={() => move(i, -1)}
                          className={i > firstM ? 'border-ms-gray-300 text-ms-gray-800' : 'border-ms-gray-200 text-ms-gray-400'}
                          style={arrowBtn}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          onClick={() => move(i, 1)}
                          className={i < lastM ? 'border-ms-gray-300 text-ms-gray-800' : 'border-ms-gray-200 text-ms-gray-400'}
                          style={arrowBtn}
                        >
                          ↓
                        </button>
                      </>
                    )}
                  </div>
                  {picking === s.stepId && !locked && (
                    <div
                      className="bg-ms-white border-ms-gray-300"
                      style={{
                        position: 'absolute',
                        right: 62,
                        top: 'calc(100% - 6px)',
                        zIndex: 30,
                        width: 268,
                        maxHeight: 340,
                        overflow: 'auto',
                        borderRadius: 10,
                        borderWidth: 1,
                        borderStyle: 'solid',
                        boxShadow: '0 8px 24px rgba(0,0,0,0.14)',
                        padding: '4px 0',
                      }}
                    >
                      <PickOpt name="미배정" on={!s.assigneeId} onPick={() => setAssignee(s, null, '')} />
                      {groups.map((g) => (
                        <div key={g.group}>
                          <span className="text-typo-caption-md-600 text-ms-gray-500" style={{ display: 'block', padding: '8px 12px 2px' }}>
                            {g.group}
                          </span>
                          {g.list.map((x) => {
                            const cur = x.work.find((w) => w.state === 'in_progress');
                            const next = x.work.filter((w) => w.state === 'assigned');
                            const work = cur
                              ? '지금 ' + rn(cur.location) + ' · ' + cur.label
                              : next.length
                                ? '대기 ' + next.length + '건 · ' + rn(next[0].location)
                                : '비어있음';
                            const on = s.assigneeId === x.staffId;
                            return (
                              <PickOpt
                                key={x.staffId}
                                staffId={x.staffId}
                                name={x.name + (roles.length > 1 ? ' ' + RTITLE[x.role] : '')}
                                color={ROLE_COLOR[x.role]}
                                mention={c.mentionedStaffIds.includes(x.staffId)}
                                work={work}
                                busy={!!cur && !on}
                                on={on}
                                onPick={() => setAssignee(s, x.staffId, x.name)}
                              />
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {cands.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span className="text-typo-caption-md-600 text-ms-gray-700">오늘 시술 후보</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {cands.map((x) => (
                  <button
                    key={x.bundleId}
                    type="button"
                    data-cand={x.bundleId}
                    onClick={() => void run(() => api.addProcedures(c.scheduleId, [x.bundleId]), x.name + ' 추가 · ' + c.name)}
                    className="bg-ms-white border-primary text-primary"
                    style={{
                      borderWidth: 1,
                      borderStyle: 'solid',
                      borderRadius: 999,
                      padding: '5px 10px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      cursor: 'pointer',
                      font: 'inherit',
                    }}
                  >
                    <span className="text-typo-caption-md-600" style={{ whiteSpace: 'nowrap' }}>
                      + {x.name}
                    </span>
                    {x.kind === 'procedure' && (
                      <span className="text-typo-caption-md-500 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {x.left}/{x.total}
                      </span>
                    )}
                    {x.paymentRequired && (
                      <span className="bg-red-100 text-red text-typo-caption-md-600" style={{ padding: '0 5px', borderRadius: 4, whiteSpace: 'nowrap' }}>
                        수납필요
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {c.unpaidAmount > 0 && (
            <div
              className="bg-yellow-100 border-ms-gray-400"
              style={{
                borderRadius: 10,
                borderWidth: 1,
                borderStyle: 'solid',
                padding: '10px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                flexWrap: 'wrap',
              }}
            >
              <span className="text-typo-caption-md-600 text-ms-gray-700">미결제 금액</span>
              <span className="text-typo-heading-md-500 text-ms-gray-800" style={{ fontVariantNumeric: 'tabular-nums' }}>
                {won(c.unpaidAmount)}
              </span>
              <div style={{ marginLeft: 'auto' }}>
                <Button
                  variant="solid"
                  color="blue"
                  size="sm"
                  onClick={() => void run(() => api.paymentComplete(c.scheduleId), '결제 완료 · 시술권 연결')}
                >
                  결제 완료
                </Button>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {!isSleep(c.location) && (
              <Button variant="outlined" color="gray" size="sm" onClick={() => setSleep((v) => !v)}>
                수면시술실로 이동
              </Button>
            )}
            {c.prevRoom && (
              <Button
                variant="outlined"
                color="gray"
                size="sm"
                onClick={() => {
                  onClose();
                  void run(() => api.returnRoom(c.scheduleId), c.name + ' → 원래 방으로');
                }}
              >
                원래 방으로
              </Button>
            )}
            <div style={{ marginLeft: 'auto' }}>
              <Button variant="outlined" color="red" size="sm" onClick={() => onDischarge(c)}>
                귀가
              </Button>
            </div>
          </div>

          {sleep && !isSleep(c.location) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {sleepRooms.map((r) => (
                <Button
                  key={r.id}
                  variant="outlined"
                  color="blue"
                  size="sm"
                  onClick={() => {
                    void run(() => api.moveSleep(c.scheduleId, r.id), c.name + ' → ' + r.name).then((ok) => ok && onSwitch(r.id));
                  }}
                >
                  {r.name}
                </Button>
              ))}
              {!sleepRooms.length && <span className="text-typo-caption-md-400 text-ms-gray-600">빈 수면시술실 없음</span>}
            </div>
          )}
        </div>

        {/* 오른쪽 — 메모(오늘 · 히스토리). 원문 그대로 · 강조만 */}
        <div className="bg-ms-gray-100" style={{ borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
          <span className="text-typo-heading-sm-500 text-ms-gray-800">메모</span>
          <span className="text-typo-caption-md-600 text-ms-gray-700">오늘</span>
          {p && <MemoList blocks={todayBlocks(p, { consultAt: cstep ? hhmm(cstep.endedAt) : undefined })} hl={hl} />}
          <span className="text-typo-caption-md-600 text-ms-gray-700" style={{ paddingTop: 8 }}>
            히스토리
          </span>
          {p && <MemoList blocks={historyBlocks(p)} hl={hl} />}
          {p && <Bundles tickets={p.tickets} />}
        </div>
      </div>
    </>
  );
}

function PickOpt({
  name,
  on,
  onPick,
  staffId,
  color,
  mention,
  work,
  busy,
}: {
  name: string;
  on: boolean;
  onPick: () => void;
  staffId?: string;
  color?: string;
  mention?: boolean;
  work?: string;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      data-opt={staffId ?? 'none'}
      onClick={onPick}
      style={{
        width: '100%',
        display: 'grid',
        gridTemplateColumns: '8px minmax(0,1fr) 14px',
        gap: 8,
        alignItems: 'center',
        padding: '7px 12px',
        border: 0,
        background: on ? 'var(--ms-primary-100, #e8f5fa)' : 'transparent',
        cursor: 'pointer',
        font: 'inherit',
        textAlign: 'left',
        opacity: busy ? 0.55 : 1,
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color ?? 'transparent' }} />
      <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="text-typo-body-500 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
            {name}
          </span>
          {mention && (
            <span className="bg-primary-100 text-primary text-typo-caption-md-600" style={{ padding: '0 5px', borderRadius: 4, whiteSpace: 'nowrap' }}>
              지정
            </span>
          )}
        </span>
        {work && (
          <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {work}
          </span>
        )}
      </span>
      <span className="text-primary" style={{ fontSize: 12, fontWeight: 700 }}>
        {on ? '✓' : ''}
      </span>
    </button>
  );
}

// 귀가 확인 모달(§0-b 8) — 남은 단계는 「진행 안 함」
export function DischargeModal({
  board,
  c,
  onCancel,
  onConfirm,
}: {
  board: Board;
  c: BoardCustomer;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const left = c.steps.filter(movable);
  const run = c.steps.find((s) => s.state === 'in_progress');
  const roleOf = (id: string | null) => board.staff.find((s) => s.staffId === id)?.role;
  const who = (s: Step) => {
    const r = roleOf(s.assigneeId);
    return s.assigneeName ? (r ? RTITLE[r] + ' ' : '') + s.assigneeName : '미배정';
  };
  return (
    <Modal isOpen onBackdropClick={onCancel}>
      <div style={{ width: 'min(440px, calc(100vw - 64px))', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="text-typo-title-sm-600 text-ms-gray-800">{c.name} 님 귀가</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">{roomName(c.location, board.rooms)}</span>
        </div>
        {left.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="text-typo-caption-md-600 text-ms-gray-700" style={{ paddingBottom: 4 }}>
              남은 단계
            </span>
            {left.map((s) => (
              <div
                key={s.stepId}
                className="border-ms-gray-200"
                style={{
                  display: 'grid',
                  gridTemplateColumns: '22px minmax(0,1fr) auto',
                  gap: 8,
                  alignItems: 'center',
                  padding: '8px 0',
                  borderTopWidth: 1,
                  borderTopStyle: 'solid',
                }}
              >
                <StepNum n={c.steps.indexOf(s) + 1} state="skipped" />
                <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                  <span className="text-typo-body-500 text-ms-gray-800">{s.label}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">{who(s)}</span>
                </span>
                <Badge variant="neutral" size="sm">
                  진행 안 함
                </Badge>
              </div>
            ))}
          </div>
        ) : (
          <span className="text-typo-body-400 text-ms-gray-700">남은 단계 없음</span>
        )}
        {run && (
          <div className="bg-red-100" style={{ borderRadius: 8, padding: '10px 12px' }}>
            <span className="text-typo-body-500 text-red">
              진행 중 · {run.label} · {who(run)}
            </span>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="outlined" color="gray" onClick={onCancel}>
            취소
          </Button>
          <Button variant="solid" color="red" disabled={!!run} onClick={onConfirm}>
            귀가 처리
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function PlacePanel({ board, now, id, run }: { board: Board; now: number; id: string; run: Run }) {
  const sleep = isSleep(id);
  const free = canPlace(board, id);
  const away = board.customers.find((c) => c.location && c.prevRoom === id);
  // 수면시술실 빈 칸 = 관리실에 있는 고객을 옮김(원래 방은 잡아 둠) · 관리실 빈 칸 = 접수대기실 고객
  const cands = free
    ? board.customers.filter((c) =>
        sleep ? c.location && c.location !== 'reception' && !isSleep(c.location) : c.location === 'reception',
      )
    : [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span className="text-typo-caption-md-600 text-ms-gray-700">
        {sleep ? '수면 시술 고객 넣기' : '접수대기실 고객 넣기'}
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
                {c.location === 'reception'
                  ? '접수대기실 ' + fmtElapsed(c.receptionAt ?? c.since, now)
                  : roomName(c.location, board.rooms)}
              </span>
            </div>
            <span className="text-typo-caption-md-400 text-ms-gray-700">{c.steps.map((s) => s.label).join(' → ')}</span>
          </div>
          <Button
            variant="solid"
            color="blue"
            size="sm"
            onClick={() =>
              void run(
                () => (sleep ? api.moveSleep(c.scheduleId, id) : api.place(c.scheduleId, id)),
                c.name + ' → ' + roomName(id, board.rooms),
              )
            }
          >
            넣기
          </Button>
        </div>
      ))}
      {!cands.length && (
        <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '4px 0' }}>
          {away ? away.name + ' · 복귀 예정' : sleep ? '옮길 고객 없음' : '접수대기실 고객 없음'}
        </span>
      )}
    </div>
  );
}

function LoungePanel({ board, now, run, onClose }: { board: Board; now: number; run: Run; onClose: () => void }) {
  const [pick, setPick] = useState<string | null>(null);
  const cs = custIn(board, 'reception');
  const picked = cs.find((c) => c.scheduleId === pick);
  const freeRooms = board.rooms.filter((r) => /^(c\d|t\d)/.test(r.id) && canPlace(board, r.id));
  return (
    <>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span className="text-typo-caption-md-600 text-ms-gray-700">접수한 고객</span>
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
                대기 {fmtElapsed(c.receptionAt ?? c.since, now)}
              </span>
            </div>
            <span className="text-typo-caption-md-400 text-ms-gray-700">{c.steps.map((s) => s.label).join(' → ')}</span>
          </div>
        ))}
        {!cs.length && <span className="text-typo-body-400 text-ms-gray-500">접수대기실 고객 없음</span>}
      </div>
      {picked && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">{picked.name} 님 배정할 관리실</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))', gap: 6 }}>
            {freeRooms.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => {
                  onClose();
                  void run(() => api.place(picked.scheduleId, r.id), picked.name + ' → ' + r.name);
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
                <span className="text-typo-caption-md-600">{r.name}</span>
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

export function PayChip() {
  return (
    <span className="bg-red-100 text-red text-typo-caption-md-600" style={{ padding: '1px 6px', borderRadius: 4, whiteSpace: 'nowrap' }}>
      수납필요
    </span>
  );
}

function StepNum({ n, state }: { n: number; state: Step['state'] }) {
  const now = state === 'in_progress';
  const past = state === 'done' || state === 'skipped';
  return (
    <span
      className={
        now
          ? 'bg-primary border-primary text-ms-white'
          : past
            ? 'bg-ms-gray-100 border-ms-gray-300 text-ms-gray-500'
            : 'bg-ms-white border-primary text-primary'
      }
      style={{
        width: 22,
        height: 22,
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
      {n}
    </span>
  );
}
