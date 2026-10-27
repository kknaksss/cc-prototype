'use client';

// 예약 상세 모달(SPEC-005 §5.6 ~ §5.14 · §6.6 · 시안 M:245-571)
// 버튼 켜짐은 back 의 can.* · receiveMode · roomLocked 로만 그린다(§5 머리 · §5.14). 다시 부르기 = 열 때 · 조작 직후 + 2초 뒤(addendum-1 W1) ·
// 스케줄 표 폴링에서 그 예약 상태가 바뀌었을 때(§6.7) · 열려 있는 동안 5초마다(KOS 수납 반영 — E2E #17)
// 진행 경로 = 접수 때 고르는 ccc 값(기본 상담 필요 · [접수 완료] 요청에 실음 — E2E #13) · 접수 신분 조건 없음(E2E #12)
import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge, Button, Popover, PopoverContent, PopoverTrigger, type BadgeVariant } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { clearSession } from '@/lib/session';
import { hm, pad } from '@/lib/time';
import type { Personal, PreviousVisit, ReceiveRoute, ResvBoard, ResvDetail, ResvState } from '@/lib/types';
import { Flag, NATION_OPTIONS, genderIcon, headOf, moneyOf, nationName } from './view';
import { DsDate, DsSelect, snsOptions } from './controls';

const SETTLE_MS = 2000;
const POLL_MS = 5000; // 열려 있는 동안 다시 부름(E2E #17 — 코디 기본값 5초)
const KST = 9 * 3600 * 1000;
const kstDay = (ms: number) => {
  const d = new Date(ms + KST);
  return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
};

const GENDER_OPTS = [
  { value: 'MALE', label: '남성' },
  { value: 'FEMALE', label: '여성' },
  { value: 'GENDER_UNSPECIFIED', label: '선택 안 함' },
];
const NATION_OPTS = NATION_OPTIONS.map((n) => ({ value: n.code, label: n.name + ' (' + n.code + ')' }));
const isClosedMain = (m: ResvState['main']) => m === 'canceled' || m === 'noshow';

// [접수 완료] 단계 이름(§5.6 error.step)
const STEP_NAME: Record<string, string> = {
  recept: '접수',
  add_task: '「방 배정」 작업 추가',
  read_sequence: '작업 확인',
  assign_room: '방 지정',
  flow_step: '끝 단계',
};

// 고객 기본 정보 칸(§6.6 — 시안 칸 순서 + 여권 영문 성 · 이름). 값은 KOS get-visitor 그대로 · 고친 칸만 보낸다(§5.13)
type EditKey =
  | 'name'
  | 'phoneticName'
  | 'gender'
  | 'dateOfBirth'
  | 'registrationNumber'
  | 'passportNumber'
  | 'nationality'
  | 'phoneCc'
  | 'phoneNo'
  | 'email'
  | 'snsType'
  | 'snsId'
  | 'address'
  | 'passportSurname'
  | 'passportGivenNames';

function valueOf(p: Personal, k: EditKey): string {
  switch (k) {
    case 'phoneCc':
      return p.phone?.countryCode ?? '';
    case 'phoneNo':
      return p.phone?.number ?? '';
    case 'snsType':
      return p.sns?.type ?? '';
    case 'snsId':
      return p.sns?.accountId ?? '';
    case 'address':
      return p.address?.address ?? '';
    default:
      return p[k] ?? '';
  }
}

// 고친 칸 → PUT personal 본문(보낸 키만 바뀐다 — 묶음 칸은 지금 값과 합쳐 보낸다)
function personalPatch(p: Personal, edits: Partial<Record<EditKey, string>>): Partial<Personal> {
  const out: Partial<Personal> = {};
  const v = (k: EditKey) => edits[k] ?? valueOf(p, k);
  for (const k of Object.keys(edits) as EditKey[]) {
    if (k === 'phoneCc' || k === 'phoneNo') out.phone = { countryCode: v('phoneCc'), number: v('phoneNo') };
    else if (k === 'snsType' || k === 'snsId') out.sns = { type: v('snsType') || null, accountId: v('snsId') }; // 종류 빈 값 = null(리뷰 r2 W3)
    else if (k === 'address') out.address = { address: v('address'), detailed: p.address?.detailed ?? null, zipCode: p.address?.zipCode ?? null };
    else out[k] = v(k);
  }
  return out;
}

export function DetailModal({
  reservationId,
  board,
  onClose,
  onChanged,
  onError,
  onReceived,
}: {
  reservationId: number;
  board: ResvBoard | null;
  onClose: () => void;
  onChanged: (toast?: string) => void;
  onError: (e: unknown) => void;
  onReceived?: (state: ResvState) => void; // 접수 성공 → 표 카드 낙관 표시(E2E #14)
}) {
  const [d, setD] = useState<ResvDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [gone, setGone] = useState(false); // KOS 에서 사라진 예약(404) — 폴링 멈춤(E2E b2 #2)
  const goneRef = useRef(false);
  const [busy, setBusy] = useState<string | null>(null);

  // 화면 칸 — 고친 것만 들고 있다(다시 부르기가 입력을 덮지 않게)
  const [edits, setEdits] = useState<Partial<Record<EditKey, string>>>({});
  const [unlock, setUnlock] = useState(false);
  const [memo, setMemo] = useState<string | null>(null);
  const [remark, setRemark] = useState<string | null>(null);
  const [roomPick, setRoomPick] = useState<number | null>(null);
  const [roomOpen, setRoomOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [consOpen, setConsOpen] = useState(false);
  const [consPick, setConsPick] = useState<number | null>(null);
  const [closedVisits, setClosedVisits] = useState<number[]>([]); // 이전 방문 = 기본 전부 펼침 · 접은 것만(E2E b2 #7)
  const [receiveError, setReceiveError] = useState<string | null>(null);
  const [route, setRoute] = useState<ReceiveRoute>('consultation');

  const seq = useRef(0);
  const load = useCallback(() => {
    const n = ++seq.current;
    api
      .reservationDetail(reservationId)
      .then((x) => {
        if (n !== seq.current) return;
        setD(x);
        setLoadError(null);
      })
      .catch((e: unknown) => {
        if (n !== seq.current) return;
        if (e instanceof api.ApiError && e.status === 401) {
          clearSession();
          return;
        }
        if (e instanceof api.ApiError && e.status === 404) {
          goneRef.current = true;
          setGone(true);
          return;
        }
        setLoadError(e instanceof Error ? e.message : '예약을 불러오지 못했어요');
      });
  }, [reservationId]);

  // 5초 폴링 — 조작 요청 중에는 건너뜀(§6.7 · 리뷰 r2 W4: 조작 직후 다시 부르기와 겹쳐 중간 상태가 보이지 않게)
  const busyRef = useRef<string | null>(null);
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);
  useEffect(() => {
    load();
    const t = setInterval(() => {
      if (busyRef.current === null && !goneRef.current) load();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  // 조작 뒤 — 바로 1번 + 2초 뒤 1번(addendum-1 W1 · §4.3)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const reloadSoon = useCallback(() => {
    load();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, SETTLE_MS);
  }, [load]);

  // 스케줄 표 폴링에서 그 예약의 상태가 바뀌면 다시 부른다(§6.7)
  const card = board?.cards.find((c) => c.reservationId === reservationId);
  const sig = card ? card.state.main + '/' + (card.state.sub ?? '') : '';
  const lastSig = useRef(sig);
  useEffect(() => {
    if (!sig || sig === lastSig.current) return;
    lastSig.current = sig;
    if (!goneRef.current) load();
  }, [sig, load]);

  // Esc 로 닫기
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      // 팝오버(상담사 · DS 드롭다운 · 달력)가 열려 있으면 Esc 는 그것만 닫는다
      if (e.key === 'Escape' && !document.querySelector('[data-radix-popper-content-wrapper]')) onClose();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [onClose]);

  // 조작 공통 — 「…중」 → 성공이면 토스트 + 상세 · 표 다시 부름 / 실패 = back message 토스트
  const run = async (key: string, fn: () => Promise<unknown>, toast: string, after?: () => void) => {
    setBusy(key);
    try {
      await fn();
      after?.();
      onChanged(toast);
      reloadSoon();
      return true;
    } catch (e) {
      onError(e);
      return false;
    } finally {
      setBusy(null);
    }
  };

  const head = d ? headOf(d.state) : null;

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.32)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="예약 상세"
        className="bg-ms-white shadow-pop-over-more"
        style={{ width: 'min(1440px, 92vw)', maxWidth: '100%', height: '88vh', maxHeight: '100%', borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
      >
        <div className={head?.cls ?? 'bg-ms-gray-100 text-ms-gray-800'} style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', ...head?.style }}>
          <span className="text-typo-heading-md-600">{head?.title ?? '예약 상세'}</span>
          <button type="button" aria-label="닫기" onClick={onClose} style={{ border: 'none', background: 'transparent', color: 'inherit', fontSize: 20, lineHeight: 1, cursor: 'pointer' }}>
            ×
          </button>
        </div>

        {gone ? (
          <div style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="text-typo-body-500 text-ms-gray-800">KOS 에서 사라진 예약이에요</span>
            <Button variant="outlined" color="gray" size="sm" onClick={onClose}>
              닫기
            </Button>
          </div>
        ) : !d ? (
          <div style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className={'text-typo-body-400 ' + (loadError ? 'text-red' : 'text-ms-gray-500')}>{loadError ?? '불러오는 중…'}</span>
            {loadError && (
              <Button variant="outlined" color="gray" size="sm" onClick={load}>
                다시
              </Button>
            )}
          </div>
        ) : (
          <Body
            d={d}
            busy={busy}
            run={run}
            onError={onError}
            onClose={onClose}
            reload={load}
            state={{ edits, setEdits, unlock, setUnlock, memo, setMemo, remark, setRemark, roomPick, setRoomPick, roomOpen, setRoomOpen, cancelOpen, setCancelOpen, consOpen, setConsOpen, consPick, setConsPick, closedVisits, setClosedVisits, receiveError, setReceiveError, route, setRoute, setBusy }}
            onChanged={onChanged}
            reloadSoon={reloadSoon}
            optimistic={(x) => {
              seq.current++; // 앞서 나간 읽기가 낙관 표시를 덮지 않게
              setD(x);
              onReceived?.(x.state);
            }}
          />
        )}
      </div>
    </div>
  );
}

interface UiState {
  edits: Partial<Record<EditKey, string>>;
  setEdits: React.Dispatch<React.SetStateAction<Partial<Record<EditKey, string>>>>;
  unlock: boolean;
  setUnlock: (v: boolean) => void;
  memo: string | null;
  setMemo: (v: string | null) => void;
  remark: string | null;
  setRemark: (v: string | null) => void;
  roomPick: number | null;
  setRoomPick: (v: number | null) => void;
  roomOpen: boolean;
  setRoomOpen: (v: boolean) => void;
  cancelOpen: boolean;
  setCancelOpen: (v: boolean) => void;
  consOpen: boolean;
  setConsOpen: (v: boolean) => void;
  consPick: number | null;
  setConsPick: (v: number | null) => void;
  closedVisits: number[];
  setClosedVisits: (v: number[]) => void;
  receiveError: string | null;
  setReceiveError: (v: string | null) => void;
  route: ReceiveRoute;
  setRoute: (v: ReceiveRoute) => void;
  setBusy: (v: string | null) => void;
}

function Body({
  d,
  busy,
  run,
  onError,
  onClose,
  reload,
  state: s,
  onChanged,
  reloadSoon,
  optimistic,
}: {
  d: ResvDetail;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, toast: string, after?: () => void) => Promise<boolean>;
  onError: (e: unknown) => void;
  onClose: () => void;
  reload: () => void;
  state: UiState;
  onChanged: (toast?: string) => void;
  reloadSoon: () => void;
  optimistic: (d: ResvDetail) => void;
}) {
  const c = d.customer;
  const g = genderIcon(c.gender);
  const nation = nationName(c.nationality);
  const pre = d.flow === null; // 접수 전 = 이전 방문 · 접수 뒤 = 내원 현황
  const id = d.customer.identity;

  // 시술실 — 고른 방(없으면 응답의 selected)
  const selectedRoom = d.rooms.find((r) => r.selected)?.roomId ?? null;
  const roomId = d.roomLocked ? selectedRoom : (s.roomPick ?? selectedRoom);
  const roomTitle = d.rooms.find((r) => r.roomId === roomId)?.title ?? null;
  const freeRooms = d.rooms.filter((r) => !r.busy).length;

  // [접수 완료] 꺼짐 이유(§6.6) — 방만 고르면 켜짐 · 신분 조건 없음(E2E #12)
  const receiveWhy = d.can.receive && roomId === null ? '시술실을 고르세요' : '';
  const canReceive = d.can.receive && roomId !== null && busy === null;

  const receive = async () => {
    if (roomId === null) return;
    s.setReceiveError(null);
    s.setBusy('receive');
    try {
      await api.receive(d.reservationId, roomId, s.route);
      s.setRoomPick(null);
      optimistic(receivedView(d, s.route, roomId, roomTitle));
      onChanged('접수 완료 · ' + (roomTitle ?? ''));
      reloadSoon();
    } catch (e) {
      // 단계에서 멈춤(§5.6) — 모달 안에 남겨 두고 토스트도
      if (e instanceof api.ApiError) {
        const step = e.extra.step ? (STEP_NAME[e.extra.step] ?? e.extra.step) + ' 단계에서 멈췄어요 · ' : '';
        if (e.status !== 401) s.setReceiveError(step + e.message);
      }
      onError(e);
      reload();
    } finally {
      s.setBusy(null);
    }
  };

  const showRoute = d.state.main === 'reserved' || d.state.main === 'noshow' || d.receiveMode !== null;
  const showReceiveBtn = d.receiveMode !== null || d.state.main === 'reserved' || d.state.main === 'noshow' || d.state.main === 'canceled';
  const receiveLabel = busy === 'receive' ? '접수 중…' : d.state.main === 'canceled' ? '취소됨' : d.receiveMode === null && !pre ? '접수됨' : '접수 완료';

  return (
    <>
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* ── 왼쪽 */}
        <div style={{ flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
          <div className="border-ms-gray-200" style={{ flexShrink: 0, padding: '14px 20px', display: 'flex', flexDirection: 'column', gap: 6, borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {g && (
                <span className={g.cls} style={{ fontSize: 16, fontWeight: 700 }}>
                  {g.icon}
                </span>
              )}
              <span className="text-typo-title-md-600 text-ms-gray-800" style={{ whiteSpace: 'nowrap' }}>
                {c.name}
              </span>
              {c.phoneticName && (
                <span className="text-typo-heading-sm-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                  {c.phoneticName}
                </span>
              )}
              <Badge variant={c.isNew ? 'purple' : 'neutral'} size="sm">
                {c.isNew ? '초진' : '재진'}
              </Badge>
              <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
                {[d.zoneTitle, d.groupTitle].filter(Boolean).join(' / ')}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <Flag code={c.nationality} />
              <span className="text-typo-body-400 text-ms-gray-600" style={{ whiteSpace: 'nowrap' }}>
                {[nation, g?.label, c.age != null ? '만 ' + c.age + '세' : null, c.chartNumber ? 'No.' + c.chartNumber : null].filter(Boolean).join(' · ')}
              </span>
            </div>
          </div>

          <PersonalBlock d={d} s={s} busy={busy} run={run} reload={reload} />

          {/* 신분 확인 · 유입 채널 */}
          <div className="border-ms-gray-200" style={{ flexShrink: 0, padding: '12px 20px', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 16, borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className="text-typo-heading-sm-600 text-ms-gray-800">신분 확인</span>
                <span className="text-typo-body-400 text-ms-gray-500">{id.kind === 'foreign' ? '여권' : '신분증'}</span>
                <Badge variant={id.status === 'confirmed' ? 'primary' : 'warning'} size="sm">
                  {id.status === 'confirmed' ? '확인 완료' : '미확인'}
                </Badge>
              </div>
              {/* ccc 「확인 완료」 표시(표시만 — §5.12 ② · 접수 조건 아님 — E2E #12) */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {id.status === 'confirmed' && (
                  <span className="text-typo-body-400 text-ms-gray-600">
                    확인 완료
                    {id.checkedBy ? ' · ' + id.checkedBy : ''}
                    {id.checkedAt ? ' · ' + checkedText(id.checkedAt) : ''}
                  </span>
                )}
                {d.can.confirmIdentity && id.status !== 'confirmed' && (
                  <Button variant="outlined" color="blue" size="sm" disabled={busy !== null} onClick={() => void run('id', () => api.setIdentity(c.customerId, 'confirmed'), '저장했어요')}>
                    {busy === 'id' ? '저장 중…' : '확인 완료'}
                  </Button>
                )}
                {d.can.unconfirmIdentity && id.status === 'confirmed' && (
                  <Button variant="outlined" color="gray" size="sm" disabled={busy !== null} onClick={() => void run('id', () => api.setIdentity(c.customerId, 'unconfirmed'), '저장했어요')}>
                    {busy === 'id' ? '저장 중…' : '미확인으로'}
                  </Button>
                )}
              </div>
            </div>
            <div className="border-ms-gray-200" style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, paddingLeft: 16, borderLeftWidth: 1, borderLeftStyle: 'solid' }}>
              <span className="text-typo-heading-sm-600 text-ms-gray-800">유입 채널</span>
              <span className="text-typo-body-400 text-ms-gray-800">
                {d.reservation.funnel ? [d.reservation.funnel.name, d.reservation.funnel.detail].filter(Boolean).join(' · ') || '-' : '-'}
              </span>
            </div>
          </div>

          {/* 예약 메모 */}
          <div style={{ flex: 1, minHeight: 150, padding: '12px 20px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span className="text-typo-heading-sm-600 text-ms-gray-800">예약 메모</span>
              {d.can.editMemo && (
                <Button
                  variant="outlined"
                  color="blue"
                  size="sm"
                  disabled={s.memo === null || s.memo === (d.reservation.memo ?? '') || busy !== null}
                  onClick={() => void run('memo', () => api.saveReservationMemo(d.reservationId, s.memo ?? ''), '저장했어요', () => s.setMemo(null))}
                >
                  {busy === 'memo' ? '저장 중…' : '저장'}
                </Button>
              )}
            </div>
            <textarea
              value={s.memo ?? d.reservation.memo ?? ''}
              onChange={(e) => s.setMemo(e.target.value)}
              readOnly={!d.can.editMemo}
              placeholder="날짜/지점/희망 시술/통역/특이사항"
              className={(d.can.editMemo ? 'bg-ms-white' : 'bg-ms-gray-100') + ' border-ms-gray-300 text-typo-heading-sm-400 text-ms-gray-800'}
              style={{ flex: 1, minHeight: 90, padding: '10px 12px', borderWidth: 1, borderStyle: 'solid', borderRadius: 6, resize: 'none', overflow: 'auto', fontFamily: 'inherit', boxSizing: 'border-box', width: '100%' }}
            />
          </div>
        </div>

        {/* ── 오른쪽 */}
        <div className="border-ms-gray-200" style={{ flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column', borderLeftWidth: 1, borderLeftStyle: 'solid', overflowY: 'auto' }}>
          <Health d={d} />
          <div className="border-ms-gray-200" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 6, borderBottomWidth: 1, borderBottomStyle: 'solid', flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span className="text-typo-heading-sm-600 text-ms-gray-800">주의사항</span>
              {d.can.editRemark && (
                <Button
                  variant="outlined"
                  color="blue"
                  size="sm"
                  disabled={s.remark === null || s.remark === (c.remark ?? '') || busy !== null}
                  onClick={() => void run('remark', () => api.saveRemark(c.customerId, s.remark ?? ''), '저장했어요', () => s.setRemark(null))}
                >
                  {busy === 'remark' ? '저장 중…' : '저장'}
                </Button>
              )}
            </div>
            <textarea
              value={s.remark ?? c.remark ?? ''}
              onChange={(e) => s.setRemark(e.target.value)}
              readOnly={!d.can.editRemark}
              placeholder="고객 공통 메모 (모든 방문에 표시)"
              className="bg-ms-white border-ms-gray-300 text-typo-heading-sm-400 text-ms-gray-800"
              style={{ height: 110, padding: '10px 12px', borderWidth: 1, borderStyle: 'solid', borderRadius: 6, resize: 'none', overflow: 'auto', fontFamily: 'inherit', boxSizing: 'border-box', width: '100%' }}
            />
          </div>
          <div style={{ flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {pre ? <Visits visits={d.previousVisits} closed={s.closedVisits} onClosed={s.setClosedVisits} /> : <FlowBlock d={d} s={s} busy={busy} run={run} onClose={onClose} />}
          </div>
        </div>
      </div>

      {/* ── 바닥 줄 */}
      <div className="border-ms-gray-200" style={{ position: 'relative', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 8, borderTopWidth: 1, borderTopStyle: 'solid', flexWrap: 'wrap' }}>
        {d.can.cancel && (
          <div style={{ position: 'relative' }}>
            <button
              type="button"
              onClick={() => s.setCancelOpen(!s.cancelOpen)}
              disabled={busy !== null}
              className="bg-ms-white border-red text-red text-typo-body-500"
              style={{ height: 40, padding: '0 14px', borderWidth: 1, borderStyle: 'solid', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap' }}
            >
              {busy === 'cancel' ? '취소 중…' : '예약 취소'}
            </button>
            {s.cancelOpen && (
              <div
                className="bg-ms-white border-ms-gray-200"
                style={{ position: 'absolute', left: 0, bottom: 48, zIndex: 3, borderWidth: 1, borderStyle: 'solid', borderRadius: 10, boxShadow: '0 8px 28px rgba(0,0,0,0.14)', padding: 10, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 160 }}
              >
                {(
                  [
                    ['CANCELED', '예약 취소'],
                    ['NO_SHOW', '예약 부도'],
                  ] as const
                ).map(([reason, label]) => (
                  <Button
                    key={reason}
                    variant="outlined"
                    color="red"
                    size="sm"
                    onClick={() => {
                      s.setCancelOpen(false);
                      void run('cancel', () => api.cancelReservation(d.reservationId, reason), label);
                    }}
                  >
                    {label}
                  </Button>
                ))}
                <Button variant="text" color="gray" size="sm" onClick={() => s.setCancelOpen(false)}>
                  닫기
                </Button>
              </div>
            )}
          </div>
        )}
        <span style={{ flex: 1 }} />
        {(receiveWhy || s.receiveError) && showReceiveBtn && (
          <span className="text-typo-body-500 text-red" style={{ maxWidth: 420 }}>
            {s.receiveError ?? receiveWhy}
          </span>
        )}
        {showRoute && <RouteRadio on={d.can.editRoute && busy === null} value={s.route} onChange={s.setRoute} />}
        {d.receiveMode !== null && (
          <>
            <button
              type="button"
              onClick={() => !d.roomLocked && s.setRoomOpen(!s.roomOpen)}
              aria-expanded={s.roomOpen}
              title={d.roomLocked ? '이미 배정된 방이에요' : undefined}
              className={
                (roomId === null ? 'border-red text-red' : d.roomLocked ? 'border-ms-gray-300 text-ms-gray-600 bg-ms-gray-100' : 'border-primary text-primary') + (d.roomLocked ? '' : ' bg-ms-white')
              }
              style={{ height: 40, padding: '0 14px', borderWidth: 1, borderStyle: 'solid', borderRadius: 8, cursor: d.roomLocked ? 'default' : 'pointer', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'inherit' }}
            >
              <span className="text-typo-body-500">{roomTitle ? '시술실 · ' + roomTitle : '시술실 선택'}</span>
              {!d.roomLocked && <span style={{ fontSize: 11 }}>▴</span>}
            </button>
            {s.roomOpen && !d.roomLocked && (
              <div
                className="bg-ms-white border-ms-gray-200"
                style={{ position: 'absolute', right: 20, bottom: 60, zIndex: 3, width: 'min(420px, calc(100% - 40px))', borderWidth: 1, borderStyle: 'solid', borderRadius: 10, boxShadow: '0 8px 28px rgba(0,0,0,0.14)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
              >
                <div className="border-ms-gray-200" style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, padding: '12px 16px', borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
                  <span className="text-typo-heading-md-500 text-ms-gray-800">시술실 배정</span>
                  <span className="text-typo-body-400 text-ms-gray-500">
                    {d.zoneTitle ?? ''} · 빈 방 {freeRooms}개
                  </span>
                </div>
                {/* 시안 M:1826-1832 · M:552-560 — 빈 방 먼저 정렬 + column-reverse = 사용 중(회색) 위 · 빈 방 아래 · 한 열 · [이름 64][사용자][상태] */}
                <div style={{ maxHeight: 320, overflow: 'auto', display: 'flex', flexDirection: 'column-reverse', padding: 6 }}>
                  {[...d.rooms]
                    .sort((a, b) => Number(a.busy) - Number(b.busy))
                    .map((r) => {
                      const on = r.roomId === roomId;
                      return (
                        <button
                          key={r.roomId}
                          type="button"
                          disabled={r.busy}
                          onClick={() => {
                            s.setRoomPick(r.roomId);
                            s.setRoomOpen(false);
                          }}
                          className={on ? 'bg-primary-100 border-primary' : r.busy ? 'bg-ms-gray-100 border-ms-gray-100' : 'bg-ms-white border-ms-white'}
                          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', minHeight: 44, boxSizing: 'border-box', borderWidth: 1, borderStyle: 'solid', borderRadius: 8, cursor: r.busy ? 'not-allowed' : 'pointer', textAlign: 'left', fontFamily: 'inherit' }}
                        >
                          <span className="text-typo-body-600 text-ms-gray-800" style={{ minWidth: 64, flexShrink: 0, whiteSpace: 'nowrap' }}>
                            {r.title}
                          </span>
                          {/* 시안의 사용 중 고객 이름 칸 — 응답에 값이 없어 비움 */}
                          <span className="text-typo-body-400 text-ms-gray-600" style={{ minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} />
                          <span className={r.busy ? 'text-typo-body-400 text-ms-gray-500' : 'text-typo-body-500 text-primary'} style={{ whiteSpace: 'nowrap' }}>
                            {r.busy ? '사용 중' : on ? '선택됨' : '비어있음'}
                          </span>
                        </button>
                      );
                    })}
                  {!d.rooms.length && <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 8 }}>이 구역 방이 없어요</span>}
                </div>
              </div>
            )}
          </>
        )}
        {showReceiveBtn ? (
          <Button variant="solid" color="blue" disabled={!canReceive} onClick={() => void receive()}>
            {receiveLabel}
          </Button>
        ) : (
          <Button variant="outlined" color="gray" onClick={onClose}>
            닫기
          </Button>
        )}
      </div>
    </>
  );
}

// 확인 완료 시각 — 오늘이 아니면 「M/D」 붙임(§5.12)
function checkedText(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const day = kstDay(t);
  if (day === kstDay(Date.now())) return hm(t);
  const [, m, dd] = day.split('-').map(Number);
  return m + '/' + dd + ' ' + hm(t);
}

// ── 고객 기본 정보(§5.13 · §6.6)
function PersonalBlock({
  d,
  s,
  busy,
  run,
  reload,
}: {
  d: ResvDetail;
  s: UiState;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, toast: string, after?: () => void) => Promise<boolean>;
  reload: () => void;
}) {
  const p = d.customer.personal;
  const kr = (p?.nationality ?? d.customer.nationality) === 'KR';
  // 접수 뒤에는 회색 읽기 전용 + [수정] 하나로 풀기(시안 M:2067 · 기본값)
  const locked = !d.can.editPersonal || (d.flow !== null && !s.unlock);
  const fields: { k: EditKey; label: string; span?: number; type?: 'date' | 'gender' | 'nation' | 'sns' }[] = [
    { k: 'name', label: kr ? '이름' : '이름 (여권 영문)' },
    { k: 'phoneticName', label: '한글 발음' },
    { k: 'gender', label: '성별', type: 'gender' },
    { k: 'dateOfBirth', label: '생년월일', type: 'date' },
    kr ? { k: 'registrationNumber', label: '주민등록번호' } : { k: 'passportNumber', label: '여권번호' },
    { k: 'nationality', label: '국적', type: 'nation' },
    { k: 'phoneCc', label: '휴대폰 국가번호' },
    { k: 'phoneNo', label: '휴대폰 번호' },
    { k: 'email', label: '이메일' },
    { k: 'snsType', label: 'SNS 종류', type: 'sns' },
    { k: 'snsId', label: 'SNS 아이디', span: 2 },
    { k: 'passportSurname', label: '여권 영문 성' },
    { k: 'passportGivenNames', label: '여권 영문 이름', span: 2 },
    { k: 'address', label: kr ? '주소' : '주소 (자국)', span: 3 },
  ];
  const val = (k: EditKey) => s.edits[k] ?? (p ? valueOf(p, k) : '');
  const filled = fields.filter((f) => val(f.k).trim()).length;
  const dirty = Object.entries(s.edits).some(([k, v]) => p && v !== valueOf(p, k as EditKey));

  const save = () => {
    if (!p) return;
    const changed = Object.fromEntries(Object.entries(s.edits).filter(([k, v]) => v !== valueOf(p, k as EditKey))) as Partial<Record<EditKey, string>>;
    void run('personal', () => api.savePersonal(d.customer.customerId, personalPatch(p, changed)), '저장했어요', () => {
      s.setEdits({});
      s.setUnlock(false);
    });
  };

  return (
    <div className="border-ms-gray-200" style={{ flexShrink: 0, padding: '12px 20px', display: 'flex', flexDirection: 'column', gap: 8, borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="text-typo-heading-sm-600 text-ms-gray-800">고객 기본 정보</span>
          {p && (
            <span className={'text-typo-body-500 ' + (filled === fields.length ? 'text-primary' : 'text-ms-gray-500')} style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
              {filled === fields.length ? '모두 입력됨' : filled + ' / ' + fields.length + ' 입력'}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {p && d.can.editPersonal && d.flow !== null && !s.unlock && (
            <Button variant="outlined" color="gray" size="sm" onClick={() => s.setUnlock(true)}>
              수정
            </Button>
          )}
          {p && !locked && (
            <Button variant="outlined" color="blue" size="sm" disabled={!dirty || busy !== null} onClick={save}>
              {busy === 'personal' ? '저장 중…' : '저장'}
            </Button>
          )}
        </div>
      </div>
      {!p ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="text-typo-body-400 text-red" title={d.customer.personalError ?? undefined}>
            KOS 에서 고객 정보를 읽지 못했어요
          </span>
          <Button variant="outlined" color="gray" size="sm" onClick={reload}>
            다시
          </Button>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: '6px 12px' }}>
          {fields.map((f) => {
            const v = val(f.k);
            const cls = (locked ? 'bg-ms-gray-100 border-ms-gray-200' : v.trim() ? 'bg-ms-white border-ms-gray-300' : 'bg-yellow-100 border-yellow-500') + ' text-typo-heading-sm-400 text-ms-gray-800';
            const style: React.CSSProperties = { height: 34, padding: '0 10px', borderWidth: 1, borderStyle: 'solid', borderRadius: 6, boxSizing: 'border-box', width: '100%', minWidth: 0, fontFamily: 'inherit' };
            const set = (x: string) => s.setEdits((e) => ({ ...e, [f.k]: x }));
            // DS 컨트롤(E2E #2) — 칸 색(읽기 전용 회색 · 빈 칸 노랑)은 입력 칸과 같게
            const tone = locked ? 'bg-ms-gray-100 border-ms-gray-200' : v.trim() ? 'bg-ms-white border-ms-gray-300' : 'bg-yellow-100 border-yellow-500';
            return (
              <div key={f.k} style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, gridColumn: f.span ? `span ${f.span}` : undefined }}>
                <span className="text-typo-body-400 text-ms-gray-500">{f.label}</span>
                {f.type === 'gender' ? (
                  <DsSelect value={v} disabled={locked} onChange={set} options={GENDER_OPTS} none="미입력" className={tone} />
                ) : f.type === 'nation' ? (
                  <DsSelect
                    value={v}
                    disabled={locked}
                    onChange={set}
                    options={v && !NATION_OPTIONS.some((n) => n.code === v) ? [{ value: v, label: v }, ...NATION_OPTS] : NATION_OPTS}
                    none="미입력"
                    search
                    className={tone}
                  />
                ) : f.type === 'sns' ? (
                  <DsSelect
                    value={v}
                    disabled={locked}
                    onChange={set}
                    options={v && !snsOptions().some((o) => o.value === v) ? [{ value: v, label: v }, ...snsOptions()] : snsOptions()}
                    none="미입력"
                    className={tone}
                  />
                ) : f.type === 'date' ? (
                  <DsDate birth value={v} disabled={locked} onChange={set} placeholder="미입력" tone={tone} />
                ) : (
                  <input value={v} readOnly={locked} onChange={(e) => set(e.target.value)} placeholder="미입력" className={cls} style={style} />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── 건강 정보(§5.11)
function Health({ d }: { d: ResvDetail }) {
  const h = d.health;
  return (
    <div className="border-ms-gray-200" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10, borderBottomWidth: 1, borderBottomStyle: 'solid', flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="text-typo-heading-sm-600 text-ms-gray-800">건강 정보</span>
        {h.needCount > 0 && (
          <Badge variant="danger" size="sm">
            확인 필요 {h.needCount}
          </Badge>
        )}
      </div>
      {h.state === 'none' && (
        <div className="bg-ms-gray-100 text-typo-body-400 text-ms-gray-500" style={{ padding: 14, borderRadius: 8, textAlign: 'center' }}>
          아직 입력되지 않았어요 · 고객이 문진을 작성하면 채워집니다
        </div>
      )}
      {h.state === 'error' && (
        <div className="bg-ms-gray-100 text-typo-body-400 text-red" style={{ padding: 14, borderRadius: 8, textAlign: 'center' }}>
          KOS 에서 문진을 읽지 못했어요
        </div>
      )}
      {h.state === 'ok' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '8px 16px' }}>
          {h.items.map((it) => (
            <div key={it.title} style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
              <span className="text-typo-body-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                {it.title}
              </span>
              <span className={'text-typo-body-500 ' + (it.needsCheck ? 'text-red' : it.empty ? 'text-ms-gray-400' : 'text-ms-gray-800')} style={{ textAlign: 'right' }}>
                {it.empty ? '미입력' : (it.answer ?? '') + (it.memo ? ' (' + it.memo + ')' : '')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// KOS 영문 상태 → 한글 표시(값 판정은 back 그대로 — E2E b2 #8). 모르는 값은 원문
const RESV_STATUS_KO: Record<string, string> = { RESERVED: '예약', IN_PROGRESS: '진행 중', COMPLETED: '방문 완료', NO_SHOW: '노쇼', CANCELED: '취소' };
const TASK_STATUS_KO: Record<string, string> = { NOT_STARTED: '시작 전', WAITING: '대기', READY: '진행', DONE: '완료', CANCELED: '취소' };
const resvStatusText = (v: string | null) => (v ? (RESV_STATUS_KO[v] ?? v) : '-');
const taskStatusText = (v: string | null) => (v ? (TASK_STATUS_KO[v] ?? v) : null);

// ── 이전 방문(§5.13) — 최신 순 · 기본 전부 펼침
const RESULT: Record<PreviousVisit['result'], { text: string; variant: BadgeVariant }> = {
  completed: { text: '방문 완료', variant: 'neutral' },
  noshow: { text: '노쇼', variant: 'danger' },
  canceled: { text: '취소', variant: 'neutral' },
  other: { text: '', variant: 'neutral' },
};

function Visits({ visits, closed, onClosed }: { visits: PreviousVisit[]; closed: number[]; onClosed: (v: number[]) => void }) {
  return (
    <>
      <span className="text-typo-heading-sm-600 text-ms-gray-800" style={{ flexShrink: 0 }}>
        이전 방문 <span className="text-ms-gray-500">{visits.length}건</span>
      </span>
      {!visits.length && (
        <div className="bg-ms-gray-100 text-typo-body-400 text-ms-gray-500" style={{ flexShrink: 0, padding: 24, borderRadius: 8, textAlign: 'center' }}>
          이전 방문 내역이 없습니다 (초진)
        </div>
      )}
      {visits.map((v, i) => {
        const on = !closed.includes(i);
        const r = RESULT[v.result];
        const rows = [
          { k: '예약 메모', v: v.reservationMemo },
          { k: '상담 메모', v: v.consultationMemo },
          { k: '시술 내역', v: v.procedures.map((p) => [p.title, taskStatusText(p.status), p.doctors.join(', ')].filter(Boolean).join(' · ')).join('\n') },
        ];
        return (
          <div key={i} className="border-ms-gray-300" style={{ flexShrink: 0, borderWidth: 1, borderStyle: 'solid', borderRadius: 8, overflow: 'hidden' }}>
            <button
              type="button"
              onClick={() => onClosed(on ? [...closed, i] : closed.filter((x) => x !== i))}
              aria-expanded={on}
              className="bg-ms-gray-100 border-ms-gray-200"
              style={{ width: '100%', padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10, borderWidth: 0, borderBottomWidth: on ? 1 : 0, borderBottomStyle: 'solid', cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}
            >
              <span className="text-ms-gray-500" style={{ width: 12, flexShrink: 0, fontSize: 12 }}>
                {on ? '▾' : '▸'}
              </span>
              <span className="text-typo-heading-sm-600 text-ms-gray-800" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                {v.date.replaceAll('-', '.')}
              </span>
              <span className="text-typo-body-400 text-ms-gray-600" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {v.procedures.map((p) => p.title).join(', ')}
              </span>
              <Badge variant={r.variant} size="sm" className={v.result === 'other' ? 'text-ms-gray-500' : undefined}>
                {v.result === 'other' ? resvStatusText(v.resultRaw) : r.text}
              </Badge>
            </button>
            {on && (
              <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
                <span className="text-typo-body-400 text-ms-gray-500">
                  예약 {v.start ? hm(v.start) : '-'} · {[v.zoneTitle, v.groupTitle].filter(Boolean).join(' / ')}
                </span>
                {rows.map((x) => (
                  <div key={x.k} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span className="text-typo-body-500 text-ms-gray-500">{x.k}</span>
                    <div className={'bg-ms-gray-100 text-typo-body-400 ' + (x.v ? 'text-ms-gray-800' : 'text-ms-gray-400')} style={{ padding: '8px 10px', borderRadius: 6, whiteSpace: 'pre-wrap' }}>
                      {x.v || '없음'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

// ── 진행 경로 라디오(E2E #13) — 접수 때 고르는 값 · 바꿔도 API 호출 없음 · [접수 완료] 요청에 실린다. 켜짐 = can.editRoute
function RouteRadio({ on, value, onChange }: { on: boolean; value: ReceiveRoute; onChange: (v: ReceiveRoute) => void }) {
  const opts: { v: ReceiveRoute; name: string }[] = [
    { v: 'consultation', name: '상담 필요' },
    { v: 'direct', name: '바로 시술' },
  ];
  return (
    <div role="radiogroup" aria-label="진행 경로" className="bg-ms-gray-100" style={{ display: 'flex', gap: 2, padding: 3, borderRadius: 8, height: 40, boxSizing: 'border-box' }}>
      {opts.map((o) => {
        const sel = o.v === value;
        return (
          <button
            key={o.name}
            type="button"
            role="radio"
            aria-checked={sel}
            disabled={!on && !sel}
            onClick={() => {
              if (on && !sel) onChange(o.v);
            }}
            className={sel ? 'bg-ms-white text-primary text-typo-body-600' : 'text-ms-gray-600 text-typo-body-500'}
            style={{ border: 'none', padding: '0 12px', borderRadius: 6, cursor: on && !sel ? 'pointer' : 'default', whiteSpace: 'nowrap', fontFamily: 'inherit', background: sel ? undefined : 'transparent', boxShadow: sel ? '0 1px 3px rgba(0,0,0,0.08)' : 'none' }}
          >
            {o.name}
          </button>
        );
      })}
    </div>
  );
}

// 접수 성공 직후 낙관 표시(E2E #14) — 끝 단계(상담 필요 → 상담 대기 · 바로 시술 → 시술 대기) · 방 · 지금 시각. 다시 읽기가 오면 그 값으로 바뀐다
function receivedView(d: ResvDetail, route: ReceiveRoute, roomId: number, roomTitle: string | null): ResvDetail {
  const now = new Date().toISOString();
  const cons = route === 'consultation';
  return {
    ...d,
    state: { main: cons ? 'consultation' : 'procedure', sub: 'waiting' },
    flow: {
      receptionAt: now,
      roomTitle,
      receptionBy: null,
      consultation: cons ? { state: 'waiting', counselor: null, since: now, calledAt: null, calledBy: null } : null,
      stages: { procedure: cons ? 'none' : 'waiting', home: 'none' },
    },
    rooms: d.rooms.map((r) => ({ ...r, selected: r.roomId === roomId })),
    roomLocked: true,
    receiveMode: null,
    can: { ...d.can, receive: false, editRoute: false, cancel: false },
  };
}

// ── 내원 현황(접수 뒤 — §6.6)
function FlowBlock({
  d,
  s,
  busy,
  run,
  onClose,
}: {
  d: ResvDetail;
  s: UiState;
  busy: string | null;
  run: (key: string, fn: () => Promise<unknown>, toast: string, after?: () => void) => Promise<boolean>;
  onClose: () => void;
}) {
  const f = d.flow;
  if (!f) return null;
  const cons = f.consultation;
  const consTitle = !cons
    ? ''
    : cons.state === 'waiting'
      ? '상담 대기'
      : cons.state === 'doing'
        ? '상담 진행 중'
        : cons.state === 'done'
          ? '상담 완료'
          : '상담';
  const consActive = !!cons && (cons.state === 'waiting' || cons.state === 'doing');
  const pick = d.counselors.find((x) => x.staffId === s.consPick) ?? null;
  const noCounselor = !!cons && !cons.counselor;

  const procName = { none: '시술', waiting: '시술 대기', doing: '시술 진행 중', done: '시술 완료' }[f.stages.procedure];
  const homeName = { none: '귀가', waiting: '귀가 대기', done: '귀가 완료' }[f.stages.home];
  const procCur = f.stages.procedure === 'waiting' || f.stages.procedure === 'doing';
  const homeCur = f.stages.home !== 'none';
  const st = d.settlement;
  // [+ 상담 추가](시안 M:415-521 · E2E #15) — 접수 뒤 · 취소 아님. 켜짐 = can.addConsultation(없으면 상담 대기 · 진행 중이 아닐 때)
  const showAddCons = !isClosedMain(d.state.main);
  const addConsOn = (d.can.addConsultation ?? !consActive) && busy === null;

  return (
    <>
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span className="text-typo-heading-sm-600 text-ms-gray-800">내원 현황</span>
        {showAddCons && (
          <Button variant="outlined" color="blue" size="sm" disabled={!addConsOn} onClick={() => void run('addCons', () => api.addConsultation(d.reservationId), '상담 추가')}>
            {busy === 'addCons' ? '추가 중…' : '+ 상담 추가'}
          </Button>
        )}
      </div>
      {/* 단계 카드 = 한 줄 [제목] [상세] …… [HH:MM](E2E b2 #9) */}
      <StageCard name="접수 완료" dot="bg-primary" detail={[f.roomTitle ? f.roomTitle + ' 배정' : null, f.receptionBy ? '데스크 ' + f.receptionBy : null].filter(Boolean).join(' · ') || '-'} at={f.receptionAt} />

      {/* 상담 카드(상담 필요 예약만 — §5.8) */}
      {cons && (
        <StageCard
          name={consTitle}
          dot={consActive ? 'bg-cons' : cons.state === 'done' ? 'bg-ms-gray-400' : 'bg-ms-gray-300'}
          tone={noCounselor && consActive ? 'bg-yellow-100 border-yellow-500' : consActive ? 'bg-primary-100 border-primary' : undefined}
          detail={
            (cons.counselor ? cons.counselor.name : '상담사를 선택하세요') +
            (cons.calledAt ? ' · ' + (cons.counselor?.name ?? '') + ' 실장 호출됨' + (cons.calledBy ? ' · 데스크 ' + cons.calledBy : '') : '')
          }
          at={cons.state === 'doing' ? cons.since : (cons.calledAt ?? cons.since)}
          action={
            consActive && d.counselors.length > 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {/* 상담사 고르기 = 팝오버(portal · 모달 위 · 아래 자리 모자라면 위로 — E2E b2 #4). 고르면 닫히고 [실장 호출] */}
                <Popover open={s.consOpen} onOpenChange={s.setConsOpen}>
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      aria-expanded={s.consOpen}
                      className="bg-ms-white border-ms-gray-300 text-ms-gray-800"
                      style={{ height: 36, padding: '0 12px', borderWidth: 1, borderStyle: 'solid', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'inherit' }}
                    >
                      <span className="text-typo-body-500">{pick ? pick.name : cons.counselor ? '상담사 변경' : '상담사 선택'}</span>
                      <span style={{ fontSize: 11 }}>▾</span>
                    </button>
                  </PopoverTrigger>
                  <PopoverContent align="end" side="bottom" avoidCollisions collisionPadding={12} className="p-0" style={{ width: 320 }}>
                    <div className="border-ms-gray-200" style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, padding: '12px 16px', borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
                      <span className="text-typo-heading-md-500 text-ms-gray-800">상담사 호출</span>
                      <span className="text-typo-body-400 text-ms-gray-500">{f.roomTitle ?? ''}</span>
                    </div>
                    <div style={{ maxHeight: 260, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 2, padding: 4 }}>
                      {d.counselors.map((x) => {
                        const on = s.consPick === x.staffId;
                        return (
                          <div
                            key={x.staffId}
                            role="button"
                            tabIndex={0}
                            onClick={() => {
                              s.setConsPick(x.staffId);
                              s.setConsOpen(false);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                s.setConsPick(x.staffId);
                                s.setConsOpen(false);
                              }
                            }}
                            className={on ? 'bg-primary-100 border-primary' : 'bg-ms-white border-ms-white'}
                            style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', minHeight: 44, boxSizing: 'border-box', borderWidth: 1, borderStyle: 'solid', borderRadius: 8, cursor: 'pointer' }}
                          >
                            <span className="bg-cons-100 text-cons" style={{ width: 28, height: 28, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700 }}>
                              {x.name.slice(0, 1)}
                            </span>
                            <span className="text-typo-body-500 text-ms-gray-800" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {x.name}
                            </span>
                            <span className={'text-typo-caption-md-500 ' + (x.busyRoom ? 'text-cons' : 'text-ms-gray-500')} style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
                              {x.busyRoom ? x.busyRoom + ' 상담 중' : '비어있음'}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </PopoverContent>
                </Popover>
                {pick && (
                  <Button
                    variant="solid"
                    color="blue"
                    size="sm"
                    disabled={!d.can.callCounselor || busy !== null}
                    onClick={() => void run('counselor', () => api.callCounselor(d.reservationId, pick.staffId), pick.name + ' 실장 호출', () => s.setConsPick(null))}
                  >
                    {busy === 'counselor' ? '호출 중…' : pick.name + ' 실장 호출'}
                  </Button>
                )}
              </div>
            ) : null
          }
        />
      )}

      {/* 단계 카드 2 — 시술 · 귀가(2계층 · D-11) */}
      <StageCard name={procName} current={procCur} done={f.stages.procedure === 'done'} />
      <StageCard name={homeName} current={homeCur} done={f.stages.home === 'done'} needPay={!!st && st.paymentRequiredCount > 0}>
        {d.state.main === 'home' && st && (
          <div className="bg-ms-white" style={{ borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 8 }}>
              <PayCell k="전체 금액" v={moneyOf(st.amount, 'total')} />
              <PayCell k="결제 금액" v={moneyOf(st.amount, 'paid')} />
              <PayCell
                k="수납 필요"
                v={st.paymentRequiredCount > 0 ? st.paymentRequiredCount + '건' : '-'}
                red={st.paymentRequiredCount > 0}
                action={
                  st.paymentRequiredCount > 0 ? (
                    st.links ? (
                      <a href={st.links.purchase} target="_blank" rel="noreferrer" className="text-typo-body-600 text-red" style={{ textDecoration: 'underline', whiteSpace: 'nowrap' }}>
                        수납하기 ›
                      </a>
                    ) : (
                      <span className="text-typo-body-600 text-ms-gray-400" title="KOS 웹 주소가 설정되지 않았어요" style={{ whiteSpace: 'nowrap' }}>
                        수납하기 ›
                      </span>
                    )
                  ) : null
                }
              />
            </div>
            <div className="border-ms-gray-200" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingTop: 10, borderTopWidth: 1, borderTopStyle: 'solid' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <span className="text-typo-body-600 text-ms-gray-800">처방전</span>
                <span className="text-typo-body-400 text-ms-gray-500">{st.prescriptionCount > 0 ? '처방전 ' + st.prescriptionCount + '건' : '오늘 처방전 없음'}</span>
              </div>
              {st.prescriptionCount > 0 &&
                (st.links ? (
                  <Button variant="outlined" color="gray" size="sm" onClick={() => window.open(st.links?.prescription, '_blank', 'noopener')}>
                    처방전 출력
                  </Button>
                ) : (
                  <span title="KOS 웹 주소가 설정되지 않았어요">
                    <Button variant="outlined" color="gray" size="sm" disabled>
                      처방전 출력
                    </Button>
                  </span>
                ))}
            </div>
            {d.state.sub !== 'done' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div data-fill-buttons="true" style={{ display: 'grid' }}>
                  {/* 성공 → 모달 닫기 + 토스트(E2E #18) · 수납 필요 문구 없음(E2E #16 — 정산 상자 「수납 필요 N건」만) */}
                  <Button
                    variant="solid"
                    color="blue"
                    disabled={!d.can.discharge || busy !== null}
                    onClick={() => void run('discharge', () => api.discharge(d.reservationId), d.customer.name + ' 귀가 완료', onClose)}
                  >
                    {busy === 'discharge' ? '처리 중…' : '귀가 완료'}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </StageCard>
    </>
  );
}

// 내원 현황 단계 카드 — 한 줄 [점][제목][상세] …… [HH:MM][버튼](E2E b2 #9). 시술 · 귀가는 상세 · 시각 값이 없어 제목만(귀가 정산은 아래 children)
function StageCard({
  name,
  current = false,
  done = false,
  needPay,
  dot,
  tone,
  detail,
  at,
  action,
  children,
}: {
  name: string;
  current?: boolean;
  done?: boolean;
  needPay?: boolean;
  dot?: string; // 점 색(주면 채운 점)
  tone?: string; // 카드 배경 · 테두리
  detail?: string;
  at?: string | null;
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const box = tone ?? (current ? 'border-primary bg-primary-100' : 'border-ms-gray-300 bg-ms-white');
  return (
    <div className={box} style={{ flexShrink: 0, borderWidth: 1, borderStyle: 'solid', borderRadius: 8, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        {dot ? (
          <span className={dot} style={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0 }} />
        ) : (
          <span
            className={current ? 'border-primary bg-primary' : done ? 'border-ms-gray-400 bg-ms-gray-400' : 'border-ms-gray-300 bg-ms-white'}
            style={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0, borderWidth: 2, borderStyle: 'solid', boxSizing: 'border-box' }}
          />
        )}
        <span className={'text-typo-heading-sm-600 ' + (dot || current ? (current ? 'text-primary' : 'text-ms-gray-800') : done ? 'text-ms-gray-600' : 'text-ms-gray-500')} style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
          {name}
        </span>
        {needPay && (
          <Badge variant="danger" size="sm">
            수납 필요
          </Badge>
        )}
        <span className="text-typo-body-400 text-ms-gray-600" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={detail}>
          {detail ?? ''}
        </span>
        {at && (
          <span className="text-typo-body-500 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', flexShrink: 0 }}>
            {hm(at)}
          </span>
        )}
        {action}
      </div>
      {children}
    </div>
  );
}

function PayCell({ k, v, red, action }: { k: string; v: string; red?: boolean; action?: React.ReactNode }) {
  return (
    <div className={red ? 'bg-red-100' : 'bg-ms-gray-100'} style={{ borderRadius: 6, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
        <span className="text-typo-body-400 text-ms-gray-500">{k}</span>
        {action}
      </div>
      <span className={'text-typo-heading-sm-600 ' + (red ? 'text-red' : v === '-' ? 'text-ms-gray-400' : 'text-ms-gray-800')} style={{ fontVariantNumeric: 'tabular-nums' }}>
        {v}
      </span>
    </div>
  );
}
