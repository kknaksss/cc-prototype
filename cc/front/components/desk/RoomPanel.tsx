'use client';

import { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Modal } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import {
  KIND,
  KIND_ROLES,
  ROLE_COLOR,
  RTITLE,
  SSTATE,
  STATUS,
  boxKey,
  canPlace,
  capOf,
  checkBox,
  custIn,
  hhmm,
  isSleep,
  pickCls,
  roomName,
  won,
} from '@/lib/board';
import { useLive } from '@/lib/hooks';
import { BoldLines } from '@/lib/memo';
import { fmtElapsed } from '@/lib/time';
import type { Board, BoardCustomer, MutationResult, PatientDetail, ProcedureCandidate, Step } from '@/lib/types';
import { natName } from '@/components/staff/common';
import { workText } from './Aside';

type Run = (fn: () => Promise<MutationResult>, text: string | null) => Promise<boolean>;

const line = { borderBottomWidth: 1, borderBottomStyle: 'solid' } as const;
const box18 = {
  width: 18,
  height: 18,
  borderRadius: 4,
  borderWidth: 1,
  borderStyle: 'solid',
  boxSizing: 'border-box',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 12,
  fontWeight: 700,
} as const;
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
  run,
}: {
  board: Board;
  now: number;
  id: string;
  onClose: () => void;
  onSwitch: (room: string) => void;
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
          width: 'min(640px, calc(100vw - 64px))',
          maxHeight: 'min(820px, calc(100vh - 96px))',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
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
          <CustomerPanel key={occ.scheduleId} board={board} now={now} c={occ} run={run} onClose={onClose} onSwitch={onSwitch} />
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
}: {
  board: Board;
  now: number;
  c: BoardCustomer;
  run: Run;
  onClose: () => void;
  onSwitch: (room: string) => void;
}) {
  const rn = (r: string | null) => roomName(r, board.rooms);
  const load = useCallback(() => api.getPatient(c.scheduleId), [c.scheduleId]);
  const p = useLive<PatientDetail>(load).data;
  const [picking, setPicking] = useState<string | null>(null);
  const [consultOpen, setConsultOpen] = useState(false);
  const [add, setAdd] = useState(false);
  const [addSel, setAddSel] = useState<number[]>([]);
  const [cands, setCands] = useState<ProcedureCandidate[]>([]);
  const [sleep, setSleep] = useState(false);
  const [ask, setAsk] = useState(false);

  // 시술 후보 — 열 때마다(동선이 바뀌면 후보도 바뀐다)
  useEffect(() => {
    if (!add) return;
    let alive = true;
    api
      .getProcedureCandidates(c.scheduleId)
      .then((x) => alive && setCands(x.filter((y) => y.kind === 'procedure')))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [add, c.scheduleId, c.steps.length]);

  const steps = c.steps;
  const running = steps.some((s) => s.state === 'in_progress');
  const firstM = steps.findIndex(movable);
  let lastM = -1;
  steps.forEach((s, i) => {
    if (movable(s)) lastM = i;
  });
  const roleOf = (staffId: string | null) => board.staff.find((s) => s.staffId === staffId)?.role;
  const cstep = steps.find((s) => s.kind === 'consult' && s.state === 'done');
  const payCount = steps.filter((s) => s.paymentRequired).length;
  const meta = [p?.sex, p && p.age !== null ? p.age + '세' : '', natName(c.nationality)].filter(Boolean).join(' · ');
  const need = !!c.status?.need;

  const move = (i: number, dir: number) => {
    const j = i + dir;
    if (!steps[j] || !movable(steps[i]) || !movable(steps[j])) return;
    const ids = steps.map((s) => s.stepId);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    void run(() => api.reorder(c.scheduleId, ids), '순서 바꿈 · ' + c.name);
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
  const left = steps.filter(movable);

  return (
    <>
      <div className="bg-ms-gray-100" style={{ borderRadius: 10, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="text-typo-heading-md-500 text-ms-gray-800">{c.name}</span>
          <span
            className={
              c.isNew
                ? 'bg-primary-100 text-primary text-typo-caption-md-600'
                : 'bg-ms-gray-200 text-ms-gray-700 text-typo-caption-md-600'
            }
            style={{ padding: '1px 6px', borderRadius: 4 }}
          >
            {c.isNew ? '첫 방문' : '재내원'}
          </span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">{meta}</span>
        </div>
        <span className={need ? 'text-typo-body-600 text-red' : 'text-typo-body-500 text-ms-gray-800'}>{c.status?.label}</span>
        {c.prevRoom && (
          <span className="text-typo-caption-md-500 text-primary">원래 방 {rn(c.prevRoom)} 은 비워 두지 않고 계속 잡아 둬요</span>
        )}
      </div>

      {cstep && (
        <div
          className="border-ms-gray-200"
          style={{ borderRadius: 10, borderWidth: 1, borderStyle: 'solid', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="bg-purple-100 text-purple text-typo-caption-md-600" style={{ padding: '1px 6px', borderRadius: 4 }}>
              상담 완료
            </span>
            <span className="text-typo-body-500 text-ms-gray-800">
              {(cstep.assigneeName ? '상담사 ' + cstep.assigneeName + ' · ' : '') + hhmm(cstep.endedAt) + ' 완료'}
            </span>
            <div style={{ marginLeft: 'auto' }}>
              <Button variant="text" color="blue" size="sm" onClick={() => setConsultOpen((v) => !v)}>
                {consultOpen ? '접기' : '상담 내용 보기'}
              </Button>
            </div>
          </div>
          {consultOpen &&
            [
              p?.consult ? { title: '상담 요약', sec: p.consult } : null,
              p?.order ? { title: '오늘 오더', sec: p.order } : null,
            ]
              .filter((x): x is { title: string; sec: { lines: string[]; source: string } } => !!x)
              .map((x) => (
                <div
                  key={x.title}
                  className="bg-ms-gray-100"
                  style={{ borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}
                >
                  <span className="text-typo-caption-md-600 text-ms-gray-700">
                    {x.title} <span className="text-typo-caption-md-400 text-ms-gray-500">· {x.sec.source}</span>
                  </span>
                  <span
                    className="text-typo-body-400 text-ms-gray-800"
                    style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'keep-all' }}
                  >
                    <BoldLines lines={x.sec.lines} />
                  </span>
                </div>
              ))}
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
          <span className="text-typo-caption-md-400 text-ms-gray-600">(시술 {payCount}건)</span>
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

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, paddingBottom: 4 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">고객 동선 · 단계마다 배정</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {running ? '진행 중인 단계가 있어 순서를 바꿀 수 없어요' : '예정 · 대기 단계는 ↑↓ 로 순서를 바꿔요'}
          </span>
        </div>
        {steps.map((s, i) => {
          const ss = SSTATE[s.state];
          const role = roleOf(s.assigneeId);
          const roles = KIND_ROLES[s.kind];
          return (
            <div
              key={s.stepId}
              data-step={s.stepId}
              className="border-ms-gray-200"
              style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '9px 0', ...line }}
            >
              <div style={{ display: 'grid', gridTemplateColumns: '22px minmax(0,1fr) auto', gap: 8, alignItems: 'center' }}>
                <StepNum n={i + 1} state={s.state} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
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
                    <span className="text-typo-caption-md-400 text-ms-gray-500">
                      {KIND[s.kind] + (s.kosSequence ? ' · KOS 순번 ' + s.kosSequence : '')}
                    </span>
                    {s.paymentRequired && <PayChip />}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    {s.assigneeName ? (
                      <>
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: role ? ROLE_COLOR[role] : '' }} />
                        <span className="text-typo-caption-md-500 text-ms-gray-800">
                          {(role ? RTITLE[role] + ' ' : '') + s.assigneeName}
                        </span>
                      </>
                    ) : (
                      <span className="text-typo-caption-md-400 text-ms-gray-500">미배정</span>
                    )}
                    <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {timeOf(s)}
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Badge variant={ss.variant} size="sm" dot={ss.dot}>
                    {ss.name}
                  </Badge>
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
                  {s.state === 'planned' && (
                    <Button
                      variant="outlined"
                      color="blue"
                      size="sm"
                      onClick={() => setPicking(picking === s.stepId ? null : s.stepId)}
                    >
                      배정
                    </Button>
                  )}
                  {s.state === 'assigned' && (
                    <Button
                      variant="text"
                      color="gray"
                      size="sm"
                      onClick={() => void run(() => api.unassign(s.stepId), '배정 해제 · ' + c.name)}
                    >
                      해제
                    </Button>
                  )}
                </div>
              </div>
              {picking === s.stepId && s.state === 'planned' && (
                <div className="bg-ms-gray-100" style={{ marginLeft: 30, borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column' }}>
                  <span className="text-typo-caption-md-600 text-ms-gray-700" style={{ paddingBottom: 4 }}>
                    {KIND[s.kind] + '에 배정할 ' + roles.join(' · ')}
                  </span>
                  {board.staff
                    .filter((x) => roles.includes(x.role))
                    .map((x) => {
                      const cur = x.work.find((w) => w.state === 'in_progress');
                      const next = x.work.filter((w) => w.state === 'assigned');
                      const work = cur
                        ? '지금 ' + workText(board, cur)
                        : next.length
                          ? '대기 ' + next.length + '건 · ' + rn(next[0].location)
                          : '비어있음';
                      return (
                        <div
                          key={x.staffId}
                          data-staff={x.staffId}
                          className="border-ms-gray-200"
                          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 0', borderTopWidth: 1, borderTopStyle: 'solid' }}
                        >
                          <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: ROLE_COLOR[x.role] }} />
                          <span className="text-typo-body-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                            {x.name}
                          </span>
                          <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                            {x.role}
                          </span>
                          <span
                            className={
                              cur || next.length ? 'text-typo-caption-md-400 text-ms-gray-600' : 'text-typo-caption-md-500 text-primary'
                            }
                            style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          >
                            {work}
                          </span>
                          <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
                            <Button
                              variant="solid"
                              color="blue"
                              size="sm"
                              onClick={() => {
                                setPicking(null);
                                void run(() => api.assign(s.stepId, x.staffId), x.name + ' 배정 · ' + c.name);
                              }}
                            >
                              배정
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Button
          variant="outlined"
          color="blue"
          size="sm"
          onClick={() => {
            setAdd((v) => !v);
            setAddSel([]);
            setSleep(false);
            setAsk(false);
          }}
        >
          시술 추가
        </Button>
        {!isSleep(c.location) && (
          <Button
            variant="outlined"
            color="gray"
            size="sm"
            onClick={() => {
              setSleep((v) => !v);
              setAdd(false);
              setAsk(false);
            }}
          >
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
          <Button
            variant="outlined"
            color="red"
            size="sm"
            onClick={() => {
              setAsk((v) => !v);
              setAdd(false);
              setSleep(false);
            }}
          >
            귀가
          </Button>
        </div>
      </div>

      {add && (
        <div className="bg-ms-gray-100" style={{ borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="text-typo-caption-md-600 text-ms-gray-700">
            시술 후보 — 오늘 결제 시술권 · 보유 시술권 (고르면 동선 뒤에 붙어요)
          </span>
          {cands.map((x, i) => {
            const on = addSel.includes(i);
            return (
              <div
                key={i}
                onClick={() => setAddSel(on ? addSel.filter((k) => k !== i) : [...addSel, i])}
                className={pickCls(on)}
                style={{
                  borderWidth: 1,
                  borderStyle: 'solid',
                  borderRadius: 8,
                  padding: '9px 12px',
                  display: 'grid',
                  gridTemplateColumns: '18px minmax(0,1fr)',
                  gap: 10,
                  alignItems: 'center',
                  cursor: 'pointer',
                }}
              >
                <span className={checkBox(on)} style={box18}>
                  ✓
                </span>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <span className="text-typo-body-500">{x.label}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">
                    {(x.source === 'ticket' ? '보유 시술권' : '오늘 결제 시술권') + (x.kosSequence ? ' · 순번 ' + x.kosSequence : '')}
                  </span>
                </div>
              </div>
            );
          })}
          {!cands.length && <span className="text-typo-body-400 text-ms-gray-500">더 붙일 시술 후보가 없어요</span>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
            <Button variant="text" color="gray" size="sm" onClick={() => setAdd(false)}>
              닫기
            </Button>
            <Button
              variant="solid"
              color="blue"
              size="sm"
              disabled={!addSel.length}
              onClick={() => {
                const items = cands
                  .filter((_, i) => addSel.includes(i))
                  .map((x) => ({ kind: x.kind, label: x.label, ticketId: x.ticketId, kosSequence: x.kosSequence }));
                if (!items.length) return;
                setAdd(false);
                setAddSel([]);
                void run(() => api.addProcedures(c.scheduleId, items), '시술 ' + items.length + '개 추가 · ' + c.name);
              }}
            >
              {addSel.length ? addSel.length + '개 추가' : '추가'}
            </Button>
          </div>
        </div>
      )}

      {sleep && !isSleep(c.location) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="text-typo-caption-md-600 text-primary">수면시술실로 이동</span>
          {sleepRooms.map((r) => (
            <Button
              key={r.id}
              variant="outlined"
              color="blue"
              size="sm"
              onClick={() => {
                // 시안: 옮긴 뒤 그 수면시술실 패널을 연다
                void run(() => api.moveSleep(c.scheduleId, r.id), c.name + ' → ' + r.name).then((ok) => ok && onSwitch(r.id));
              }}
            >
              {r.name}
            </Button>
          ))}
          {!sleepRooms.length && <span className="text-typo-caption-md-400 text-ms-gray-600">빈 수면시술실 없음</span>}
        </div>
      )}

      {ask && (
        <div className="bg-red-100" style={{ borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-body-600 text-ms-gray-800">{c.name} 님을 귀가 처리할까요?</span>
          <span className="text-typo-body-400 text-ms-gray-800" style={{ wordBreak: 'keep-all' }}>
            {running
              ? '진행 중인 단계가 있어요. 그 직원이 종료한 뒤 귀가 처리할 수 있어요.'
              : left.length
                ? '남은 단계 ' +
                  left.length +
                  '개(' +
                  left.map((s) => s.label).join(' · ') +
                  ')는 「진행 안 함」으로 남겨요 — 시술권은 차감하지 않아요. 방은 비워요.'
                : '모든 단계가 끝났어요. 방을 비워요.'}
          </span>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
            <Button variant="text" color="gray" size="sm" onClick={() => setAsk(false)}>
              취소
            </Button>
            <Button
              variant="solid"
              color="red"
              size="sm"
              disabled={running}
              onClick={() => {
                onClose();
                void run(() => api.discharge(c.scheduleId), c.name + ' 귀가');
              }}
            >
              귀가 처리
            </Button>
          </div>
        </div>
      )}
    </>
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
        {sleep ? '수면 시술 고객 넣기(원래 방은 계속 잡아 둬요)' : '접수대기실 고객 넣기'}
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
          {away
            ? away.name + ' 님이 수면 시술 후 돌아올 방이에요'
            : sleep
              ? '옮길 고객이 없어요'
              : '접수대기실에 접수한 고객이 없어요'}
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
        <span className="text-typo-caption-md-600 text-ms-gray-700">접수한 고객 · 선택 후 관리실 배정</span>
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
        {!cs.length && <span className="text-typo-body-400 text-ms-gray-500">접수대기실에 접수한 고객이 없어요</span>}
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
