'use client';

import { useCallback, useState } from 'react';
import { Badge, Button } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { roomName } from '@/lib/board';
import { useLive } from '@/lib/hooks';
import { fmtMinSec } from '@/lib/time';
import type { MemoSection, PatientDetail } from '@/lib/types';
import { STAFF_STATUS, card, isForeign, natName, type MySt } from './common';
import { InterpretModal } from './InterpretModal';

type MemoKey = 'order' | 'consult' | 'reception';
// 메모 칸 기본 펼침 — 의사 ②③ · 코디 ④ (① 은 항상 펼침)
const MEMO_OPEN: Record<'doctor' | 'codi', Record<MemoKey, boolean>> = {
  doctor: { order: true, consult: true, reception: false },
  codi: { order: false, consult: false, reception: true },
};
const ST_LABEL: Record<MySt, string> = { now: '진행 중인 환자', next: '다음 환자', done: '완료한 환자' };

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

// 환자 상세(§5.5) — 시안 detailVals. 순서: 상단 카드 → 환자 메모 → 환자 차트 → 시술 이력 → 오늘 고객 동선
export function PatientView({
  scheduleId,
  staffId,
  role,
  mySt,
  now,
  wide,
  width,
  onChanged,
  onPin,
}: {
  scheduleId: string;
  staffId: string;
  role: 'doctor' | 'codi';
  mySt: MySt | null;
  now: number;
  wide: boolean;
  width: number;
  onChanged: () => Promise<void>;
  onPin: (scheduleId: string) => void;
}) {
  const load = useCallback(() => api.getPatient(scheduleId), [scheduleId]);
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

  const here = p.board;
  const status = here ? STAFF_STATUS[here.state] : null;
  const foreign = isForeign(p.nationality);
  const showAct = role === 'doctor' && (mySt === 'next' || mySt === 'now');
  // KR 만 [통역] 숨김(§7.2) — 국적을 모르는 현장 접수는 보이고 기본 언어 en
  const showInterp = p.nationality !== 'KR';
  const label = role === 'doctor' && mySt ? ST_LABEL[mySt] : here ? '내원 중인 환자' : '귀가 · 도착 전 환자';
  const labelCls =
    role === 'doctor' && mySt === 'next'
      ? 'text-typo-caption-md-600 text-purple'
      : role === 'doctor' && mySt === 'now'
        ? 'text-typo-caption-md-600 text-primary'
        : 'text-typo-caption-md-600 text-ms-gray-600';
  const timer = here
    ? (here.state === 'treat' || here.state === 'consult' ? '경과 ' : '대기 ') + fmtMinSec(here.since, now)
    : p.leaveTime
      ? p.leaveTime + ' 귀가'
      : p.reservationTime + ' 예약';

  // [진료 시작] / [진료 완료] — 결과 상태는 back(§5.3)
  const act = async () => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    // 진료한 환자를 계속 보게 경로에 고정한다(기본 선택 「다음」이 바뀌어도 화면이 다른 환자로 넘어가지 않게)
    onPin(p.scheduleId);
    try {
      if (mySt === 'now') await api.finishCare(staffId, p.scheduleId);
      else await api.startCare(staffId, p.scheduleId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '처리하지 못했어요');
    }
    await Promise.all([onChanged(), live.reload()]);
    setBusy(false);
  };

  const isOpen = (k: MemoKey) => memoOpen[k] ?? MEMO_OPEN[role][k];
  const sections: { k: MemoKey; title: string; sec: MemoSection; peek: string | null }[] = [];
  if (p.order && p.order.lines.length)
    sections.push({ k: 'order', title: '오늘 오더', sec: p.order, peek: p.order.anesthesia?.replace(/^\((.*)\)$/, '$1').trim() || null });
  if (p.consult && p.consult.lines.length) sections.push({ k: 'consult', title: '상담 요약', sec: p.consult, peek: null });
  if (p.reception && p.reception.lines.length) sections.push({ k: 'reception', title: '접수 메모', sec: p.reception, peek: null });

  const doneN = p.route.filter((s) => s.status === 'done').length;
  const liveN = p.route.filter((s) => s.status !== 'canceled').length;
  const staffLine = [p.counselor ? '상담실장 ' + p.counselor : '', p.doctors.length ? '원장 ' + p.doctors.join(' · ') : '']
    .filter(Boolean)
    .join(' · ');
  const chart = p.chart.filter((r) => r.value);

  return (
    <>
      <div
        className="bg-ms-white"
        style={{ borderRadius: 12, padding: '18px 16px', display: 'flex', flexDirection: 'column', gap: 14, ...card }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className={labelCls}>{label}</span>
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
            {[p.sex, p.age !== null ? p.age + '세' : '', p.firstVisit ? '첫 방문' : '재방문'].filter(Boolean).join(' · ')}
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
            <Badge variant={status ? status.variant : 'neutral'} size="sm" dot={status ? status.dot : false}>
              {status ? status.name : p.leaveTime ? '귀가' : '도착 전'}
            </Badge>
            <span className="text-typo-body-500 text-ms-gray-800">
              <b className="text-primary" style={{ fontWeight: 600 }}>
                {here ? roomName(here.room) : '-'}
              </b>{' '}
              · {here ? here.label : p.leaveTime ? p.leaveTime + ' 귀가' : '아직 접수 전'}
            </span>
          </div>
          {staffLine && <span className="text-typo-caption-md-400 text-ms-gray-700">{staffLine}</span>}
        </div>

        {(showInterp || showAct) && (
          <div
            data-fill-buttons="true"
            style={{
              display: 'grid',
              gridTemplateColumns: showInterp && showAct ? 'minmax(0,1fr) minmax(0,1fr)' : 'minmax(0,1fr)',
              gap: 8,
            }}
          >
            {showInterp && (
              <Button variant="outlined" color="blue" size="lg" style={{ width: '100%' }} onClick={() => setInterp(true)}>
                통역
              </Button>
            )}
            {showAct && (
              <Button variant="solid" color="blue" size="lg" style={{ width: '100%' }} isLoading={busy} onClick={() => void act()}>
                {mySt === 'now' ? '진료 완료' : '진료 시작'}
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
        style={{
          width: '100%',
          boxSizing: 'border-box',
          borderRadius: 12,
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          ...card,
        }}
      >
        <span className="text-typo-heading-sm-500 text-ms-gray-800">환자 메모</span>
        {p.cautions.length > 0 && (
          <div className="bg-red-100" style={{ borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-typo-caption-md-600 text-red">⚠ 주의</span>
            {p.cautions.map((cu, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <span className="text-typo-body-500 text-ms-gray-800" style={{ overflowWrap: 'anywhere', wordBreak: 'keep-all' }}>
                  {cu.text}
                </span>
                <span className="text-typo-caption-md-400 text-ms-gray-600">{cu.source}</span>
              </div>
            ))}
          </div>
        )}
        {sections.map(({ k, title, sec, peek }) => {
          const o = isOpen(k);
          return (
            <div
              key={k}
              className="border-ms-gray-200"
              style={{ ...topLine, paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}
            >
              <button
                type="button"
                onClick={() => setMemoOpen((s) => ({ ...s, [k]: !o }))}
                className="cc-btn"
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, width: '100%' }}
              >
                <span style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                  <span className="text-typo-body-600 text-ms-gray-800">{title}</span>
                  <span className="text-typo-caption-md-400 text-ms-gray-600">{sec.source}</span>
                </span>
                <span
                  className="text-typo-caption-md-500 text-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: 2, whiteSpace: 'nowrap' }}
                >
                  {o ? '접기' : '펼치기'}
                  <Chevron open={o} />
                </span>
              </button>
              {!o && peek && (
                <span className="text-typo-caption-md-500 text-ms-gray-700" style={{ overflowWrap: 'anywhere' }}>
                  마취 · {peek}
                </span>
              )}
              {o && (
                <span
                  className="text-typo-body-400 text-ms-gray-800"
                  style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'keep-all' }}
                >
                  {sec.lines.join('\n')}
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div
        className="bg-ms-white"
        style={{
          width: '100%',
          boxSizing: 'border-box',
          borderRadius: 12,
          display: 'flex',
          flexDirection: 'column',
          ...card,
          overflow: 'hidden',
        }}
      >
        <button
          type="button"
          onClick={() => setChartOpen((v) => !v)}
          className="cc-btn"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            padding: 16,
            width: '100%',
            boxSizing: 'border-box',
          }}
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
                style={{
                  display: 'grid',
                  gridTemplateColumns: '84px minmax(0,1fr)',
                  gap: 10,
                  alignItems: 'baseline',
                  padding: '9px 0',
                  ...topLine,
                }}
              >
                <span className="text-typo-caption-md-400 text-ms-gray-600">{r.label}</span>
                <span
                  className="text-typo-body-500 text-ms-gray-800"
                  style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'keep-all' }}
                >
                  {r.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div
        className="bg-ms-white"
        style={{ borderRadius: 12, padding: '16px 16px 6px', display: 'flex', flexDirection: 'column', ...card }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingBottom: 6 }}>
          <span className="text-typo-heading-sm-500 text-ms-gray-800">시술 이력</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">{p.firstVisit ? '이 병원 첫 방문' : '재방문'}</span>
        </div>
        {p.history.map((h, i) => (
          <div
            key={i}
            className="border-ms-gray-200"
            style={{
              display: 'grid',
              gridTemplateColumns: '84px minmax(0,1fr)',
              gap: 10,
              alignItems: 'baseline',
              padding: '10px 0',
              ...topLine,
            }}
          >
            <span className="text-typo-caption-md-400 text-ms-gray-600">{h.label}</span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
              <span className="text-typo-body-500 text-ms-gray-800" style={{ overflowWrap: 'anywhere', wordBreak: 'keep-all' }}>
                {h.value}
              </span>
              <span className="text-typo-caption-md-400 text-ms-gray-600">{h.source}</span>
            </span>
          </div>
        ))}
      </div>

      <div className="border-ms-gray-300" style={{ borderTopWidth: 1, borderTopStyle: 'dashed', margin: '4px 4px 0' }} />

      <div
        className="bg-ms-white"
        style={{ borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 12, ...card }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className="text-typo-heading-sm-500 text-ms-gray-800">오늘 고객 동선</span>
          <span className="text-typo-caption-md-400 text-ms-gray-600">
            {doneN} / {liveN} 완료
          </span>
        </div>
        {p.route.map((s, i) => {
          const nowS = s.status === 'now';
          const past = s.status === 'done';
          const cx = s.status === 'canceled';
          const meta = [
            s.staff,
            cx ? '취소' : past ? '완료 ' + (s.completedAt ?? '') : nowS ? '진행 중 · ' + (s.readyAt ?? '') + '~' : '예정',
          ]
            .filter(Boolean)
            .join(' · ');
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '22px minmax(0,1fr)', gap: 10, alignItems: 'start' }}>
              <span
                className={
                  nowS
                    ? 'bg-primary border-primary text-ms-white'
                    : past || cx
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
                <span
                  className={
                    nowS
                      ? 'text-typo-body-500 text-primary'
                      : cx
                        ? 'text-typo-body-400 text-ms-gray-500'
                        : past
                          ? 'text-typo-body-400 text-ms-gray-600'
                          : 'text-typo-body-400 text-ms-gray-800'
                  }
                  style={{ overflowWrap: 'anywhere' }}
                >
                  {s.room ? (
                    <>
                      <b style={{ fontWeight: 600 }}>{s.room}</b> · {s.task}
                    </>
                  ) : (
                    s.task
                  )}
                </span>
                <span className="text-typo-caption-md-400 text-ms-gray-600">{meta}</span>
                {s.memo && (
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
