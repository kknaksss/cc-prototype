'use client';

import { useCallback, useState } from 'react';
import { Badge, Button } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { RTITLE, SSTATE, STATUS, boxKey, hhmm, roomName } from '@/lib/board';
import { useLive } from '@/lib/hooks';
import { Bold, BoldLines, visibleLines } from '@/lib/memo';
import { fmtMinSec } from '@/lib/time';
import type { MemoSection, PatientDetail, Role, StaffAccount } from '@/lib/types';
import { PayChip } from '@/components/desk/RoomPanel';
import { card, isForeign, natName } from './common';
import { InterpretModal } from './InterpretModal';

type MemoKey = 'order' | 'consult' | 'reception';
// 메모 기본 펼침 — 배정형 ②③ · 순회형 ④ (① 은 항상 펼침, 시안 r4 MEMO_OPEN)
const MEMO_OPEN: Record<'assigned' | 'rounds', Record<MemoKey, boolean>> = {
  assigned: { order: true, consult: true, reception: false },
  rounds: { order: false, consult: false, reception: true },
};

const Chevron = ({ open }: { open: boolean }) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    style={{ transform: `rotate(${open ? '180deg' : '0deg'})` }}
  >
    <path d="M6 9l6 6 6-6" />
  </svg>
);
const topLine = { borderTopWidth: 1, borderTopStyle: 'solid' } as const;
const clock = (v: string | number | null) => (typeof v === 'number' ? hhmm(v) : (v ?? ''));

// 환자 상세(§3.4) — 상단 카드 → 환자 메모 → 환자 차트 → 시술 이력 → 오늘 고객 동선
export function PatientView({
  scheduleId,
  staffId,
  frame,
  roleOf,
  now,
  wide,
  width,
  onChanged,
  onPin,
}: {
  scheduleId: string;
  staffId: string;
  frame: 'assigned' | 'rounds';
  roleOf: (staffId: string | null) => StaffAccount['role'] | undefined;
  now: number;
  wide: boolean;
  width: number;
  onChanged: () => Promise<void>;
  onPin: (scheduleId: string) => void;
}) {
  // staffId 를 주면 내 버튼(myActions)이 온다
  const load = useCallback(() => api.getPatient(scheduleId, staffId), [scheduleId, staffId]);
  const live = useLive<PatientDetail>(load);
  const [memoOpen, setMemoOpen] = useState<Partial<Record<MemoKey, boolean>>>({});
  const [chartOpen, setChartOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [interp, setInterp] = useState(false);
  const p = live.data;

  if (!p) {
    return (
      <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 4 }}>
        {live.error ?? '불러오는 중…'}
      </span>
    );
  }

  const gone = p.flowStep === 'COMPLETED';
  const k = boxKey(p.status);
  const need = !!p.status?.need && !gone;
  const foreign = isForeign(p.nationality);
  // 배정형만 — 나에게 배정된 단계가 있을 때 [상담/시술 시작 · 종료]. 순회형은 [통역]만
  const mine = frame === 'assigned' ? p.myActions[0] : undefined;
  const mineStep = mine ? p.route.find((s) => s.stepId === mine.stepId) : undefined;
  const showInterp = p.nationality !== 'KR';
  const label = gone ? '귀가한 고객' : need ? '손 필요 · ' + p.status?.label : '내원 중인 고객';
  const timer = gone
    ? clock(p.leaveTime) + ' 귀가'
    : (p.status?.key === 'consult' || p.status?.key === 'treat' ? '진행 ' : '대기 ') + fmtMinSec(p.since, now);

  const act = async () => {
    if (busy || !mine) return;
    setBusy(true);
    setErr(null);
    // 진행한 고객을 계속 보게 경로에 고정(기본 선택이 바뀌어도 넘어가지 않게)
    onPin(p.scheduleId);
    try {
      if (mine.action === 'start') await api.startStep(staffId, mine.stepId);
      else await api.finishStep(staffId, mine.stepId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '처리하지 못했어요');
    }
    await Promise.all([onChanged(), live.reload()]);
    setBusy(false);
  };

  // 메모 공개 — 상담 단계 「완료」 뒤(상담 단계가 없으면 처음부터). back 의 memoRevealed 가 정본
  const consultPending = p.route.some((s) => s.kind === 'consult' && s.state !== 'done' && s.state !== 'skipped');
  const locked = !p.memoRevealed && consultPending;
  const isOpen = (key: MemoKey) => memoOpen[key] ?? MEMO_OPEN[frame][key];
  const sections: { key: MemoKey; title: string; sec: MemoSection | null; peek: string | null; locked: boolean }[] = [];
  if (p.order || locked)
    sections.push({
      key: 'order',
      title: '오늘 오더',
      sec: p.order,
      peek: p.order?.anesthesia?.replace(/^\((.*)\)$/, '$1').trim() || null,
      locked: locked && !p.order,
    });
  if (p.consult || locked) sections.push({ key: 'consult', title: '상담 요약', sec: p.consult, peek: null, locked: locked && !p.consult });
  if (p.reception && visibleLines(p.reception.lines).length)
    sections.push({ key: 'reception', title: '접수 메모', sec: p.reception, peek: null, locked: false });

  const live2 = p.route.filter((s) => s.state !== 'skipped');
  const staffLine = [p.counselor ? '상담사 ' + p.counselor : '', p.doctors.length ? '원장 ' + p.doctors.join(' · ') : '']
    .filter(Boolean)
    .join(' · ');
  const chart = p.chart.filter((r) => r.value);

  return (
    <>
      <div className="bg-ms-white" style={{ borderRadius: 12, padding: '18px 16px', display: 'flex', flexDirection: 'column', gap: 14, ...card }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className={need ? 'text-typo-caption-md-600 text-red' : 'text-typo-caption-md-600 text-ms-gray-600'}>{label}</span>
          <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {timer}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-headline-md-600 text-ms-gray-800" style={{ overflowWrap: 'anywhere' }}>
              {p.name}
            </span>
            {foreign && (
              <span
                className="bg-ms-gray-200 text-typo-caption-md-500 text-ms-gray-700"
                style={{ padding: '2px 7px', borderRadius: 4, whiteSpace: 'nowrap' }}
              >
                {natName(p.nationality) + ' ' + p.nationality}
              </span>
            )}
          </div>
          <span className="text-typo-body-400 text-ms-gray-600">
            {[p.sex, p.age !== null ? p.age + '세' : '', p.isNew ? '첫 방문' : '재내원'].filter(Boolean).join(' · ')}
          </span>
        </div>

        <div
          className="bg-ms-gray-100 border-ms-gray-200"
          style={{ borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 8, borderWidth: 1, borderStyle: 'solid' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-body-600 text-ms-gray-800" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {p.reservationTime} 예약
            </span>
            {p.outTime && (
              <span
                className="bg-yellow-100 text-typo-caption-md-600 text-ms-gray-800"
                style={{ padding: '3px 8px', borderRadius: 4, whiteSpace: 'nowrap' }}
              >
                아웃 {p.outTime}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Badge variant={gone ? 'neutral' : STATUS[k].variant} size="sm" dot>
              {gone ? '귀가' : STATUS[k].name}
            </Badge>
            <span className="text-typo-body-500 text-ms-gray-800">
              <b className="text-primary" style={{ fontWeight: 600 }}>
                {gone || !p.location ? '-' : roomName(p.location)}
              </b>{' '}
              · {gone ? '오늘 동선 끝' : p.status?.label}
            </span>
          </div>
          {staffLine && <span className="text-typo-caption-md-400 text-ms-gray-700">{staffLine}</span>}
        </div>

        {mine && mineStep && (
          <span className="text-typo-caption-md-600 text-primary">
            내 단계 · {mineStep.label} · {SSTATE[mineStep.state].name}
          </span>
        )}
        {(showInterp || mine) && (
          <div
            data-fill-buttons="true"
            style={{
              display: 'grid',
              gridTemplateColumns: showInterp && mine ? 'minmax(0,1fr) minmax(0,1fr)' : 'minmax(0,1fr)',
              gap: 8,
            }}
          >
            {showInterp && (
              <Button variant="outlined" color="blue" size="lg" style={{ width: '100%' }} onClick={() => setInterp(true)}>
                통역
              </Button>
            )}
            {mine && (
              <Button variant="solid" color="blue" size="lg" style={{ width: '100%' }} isLoading={busy} onClick={() => void act()}>
                {mine.label}
              </Button>
            )}
          </div>
        )}
        {err && <span className="text-typo-caption-md-500 text-red">{err}</span>}
      </div>

      {interp && showInterp && (
        <InterpretModal
          scheduleId={p.scheduleId}
          name={p.name}
          nationality={p.nationality}
          wide={wide}
          width={width}
          onClose={() => setInterp(false)}
        />
      )}

      <div
        className="bg-ms-white"
        style={{ width: '100%', boxSizing: 'border-box', borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 12, ...card }}
      >
        <span className="text-typo-heading-sm-500 text-ms-gray-800">환자 메모</span>
        {p.cautions.length > 0 && (
          <div className="bg-red-100" style={{ borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-red">⚠ 주의</span>
            {p.cautions.map((cu, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span className="text-typo-body-400 text-ms-gray-800" style={{ overflowWrap: 'anywhere', wordBreak: 'keep-all' }}>
                  <Bold text={cu.text} />
                </span>
                <span className="text-typo-caption-md-400 text-ms-gray-600">{cu.source}</span>
              </div>
            ))}
          </div>
        )}
        {locked && (
          <span className="text-typo-caption-md-400 text-ms-gray-600">오더 · 상담 메모에서 오는 ⚠ 주의는 상담이 끝나면 함께 열려요</span>
        )}
        {sections.map(({ key, title, sec, peek, locked: lk }) => {
          const o = !lk && isOpen(key);
          return (
            <div key={key} className="border-ms-gray-200" style={{ ...topLine, paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <button
                type="button"
                onClick={() => {
                  if (!lk) setMemoOpen((s) => ({ ...s, [key]: !o }));
                }}
                className="cc-btn"
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, width: '100%' }}
              >
                <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                  <span className="text-typo-body-600 text-ms-gray-800">{title}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">
                    {sec?.source ?? (key === 'order' ? '오더 메모' : '상담 메모')}
                  </span>
                </span>
                {!lk && (
                  <span
                    className="text-typo-caption-md-500 text-primary"
                    style={{ display: 'flex', alignItems: 'center', gap: 2, whiteSpace: 'nowrap' }}
                  >
                    {o ? '접기' : '펼치기'}
                    <Chevron open={o} />
                  </span>
                )}
              </button>
              {lk && (
                <span className="bg-ms-gray-100 text-typo-caption-md-500 text-ms-gray-600" style={{ borderRadius: 6, padding: '8px 10px' }}>
                  상담 후 공개 — 상담 단계가 끝나면 열려요
                </span>
              )}
              {!lk && !o && peek && (
                <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ overflowWrap: 'anywhere' }}>
                  마취 · {peek}
                </span>
              )}
              {o && sec && (
                <span
                  className="text-typo-body-400 text-ms-gray-800"
                  style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'keep-all' }}
                >
                  <BoldLines lines={sec.lines} />
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div
        className="bg-ms-white"
        style={{ width: '100%', boxSizing: 'border-box', borderRadius: 12, display: 'flex', flexDirection: 'column', ...card, overflow: 'hidden' }}
      >
        <button
          type="button"
          onClick={() => setChartOpen((v) => !v)}
          className="cc-btn"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: 16, width: '100%', boxSizing: 'border-box' }}
        >
          <span className="text-typo-heading-sm-500 text-ms-gray-800">환자 차트</span>
          <span className="text-typo-caption-md-500 text-primary" style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            {chartOpen ? '접기' : '펼치기'}
            <Chevron open={chartOpen} />
          </span>
        </button>
        {chartOpen && (
          <div style={{ padding: '0 16px 10px', display: 'flex', flexDirection: 'column' }}>
            {chart.map((r) => (
              <div
                key={r.label}
                className="border-ms-gray-200"
                style={{ display: 'grid', gridTemplateColumns: '84px minmax(0,1fr)', gap: 10, alignItems: 'baseline', padding: '9px 0', ...topLine }}
              >
                <span className="text-typo-caption-md-400 text-ms-gray-600">{r.label}</span>
                <span className="text-typo-body-500 text-ms-gray-800" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'keep-all' }}>
                  {r.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-ms-white" style={{ borderRadius: 12, padding: '16px 16px 6px', display: 'flex', flexDirection: 'column', ...card }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingBottom: 6 }}>
          <span className="text-typo-heading-sm-500 text-ms-gray-800">시술 이력</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">{p.isNew ? '첫 방문' : '재내원'}</span>
        </div>
        {p.history.map((h, i) => (
          <div
            key={i}
            className="border-ms-gray-200"
            style={{ display: 'grid', gridTemplateColumns: '84px minmax(0,1fr)', gap: 10, alignItems: 'baseline', padding: '10px 0', ...topLine }}
          >
            <span className="text-typo-caption-md-400 text-ms-gray-600">{h.label}</span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
              <span className="text-typo-body-500 text-ms-gray-800" style={{ overflowWrap: 'anywhere', wordBreak: 'keep-all' }}>
                {h.value}
              </span>
              {h.source && <span className="text-typo-caption-md-400 text-ms-gray-600">{h.source}</span>}
            </span>
          </div>
        ))}
        {locked && (
          <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: '4px 0 10px' }}>
            타 병원 이력은 상담 후 공개
          </span>
        )}
      </div>

      <div className="border-ms-gray-300" style={{ borderTopWidth: 1, borderTopStyle: 'dashed', margin: '4px 4px 0' }} />

      <div className="bg-ms-white" style={{ borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 12, ...card }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className="text-typo-heading-sm-500 text-ms-gray-800">오늘 고객 동선</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {live2.filter((s) => s.state === 'done').length} / {live2.length} 완료
          </span>
        </div>
        {p.route.map((s, i) => {
          const nowS = s.state === 'in_progress';
          const past = s.state === 'done' || s.state === 'skipped';
          const role = roleOf(s.assigneeId);
          const t =
            s.state === 'done'
              ? '완료 ' + hhmm(s.endedAt)
              : nowS
                ? '진행 중 · ' + hhmm(s.startedAt) + '~'
                : s.state === 'assigned'
                  ? '대기 · 배정 ' + hhmm(s.assignedAt)
                  : SSTATE[s.state].name;
          const who = s.assigneeName ? (role && role !== '데스크' ? RTITLE[role as Role] + ' ' : '') + s.assigneeName : '';
          return (
            <div key={s.stepId} style={{ display: 'grid', gridTemplateColumns: '22px minmax(0,1fr)', gap: 10, alignItems: 'start' }}>
              <span
                className={
                  nowS
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
                  fontSize: 12,
                  fontWeight: 600,
                  boxSizing: 'border-box',
                  borderWidth: 1,
                  borderStyle: 'solid',
                }}
              >
                {i + 1}
              </span>
              <span style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span
                    className={
                      nowS
                        ? 'text-typo-body-500 text-primary'
                        : s.state === 'skipped'
                          ? 'text-typo-body-400 text-ms-gray-500'
                          : past
                            ? 'text-typo-body-400 text-ms-gray-600'
                            : 'text-typo-body-400 text-ms-gray-800'
                    }
                    style={{ overflowWrap: 'anywhere' }}
                  >
                    {s.label}
                  </span>
                  {s.paymentRequired && <PayChip />}
                </span>
                <span className="text-typo-caption-md-400 text-ms-gray-600">{[who, t].filter(Boolean).join(' · ')}</span>
                {s.state === 'done' && s.memo && (
                  <span
                    className="bg-ms-gray-100 text-typo-caption-md-500 text-ms-gray-700"
                    style={{ alignSelf: 'flex-start', padding: '2px 6px', borderRadius: 4, overflowWrap: 'anywhere' }}
                  >
                    담당자 메모 · {s.memo}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}
