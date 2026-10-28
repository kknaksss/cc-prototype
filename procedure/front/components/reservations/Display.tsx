'use client';

// 예약 상세 — 띄우기 · 여권 스캔 자리(SPEC-004 §6.17 · §5-3 · 시안 W:276-289 QR 상자 · W:308-342 스캔 단계)
// 단계는 상세 응답 displays[](5초 폴링)로만 그린다. QR = 문진 qrUrl(고객 웹 · SPEC-006 §8.1)만 — 스캔은 기기 버튼만(E2E batch 3 추가) · [링크 복사] · [메신저 전송] 없음(D7-44)
import { useCallback, useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Badge, Button, ConfirmModal, Popover, PopoverContent, PopoverTrigger } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { hm, pad, toMs } from '@/lib/time';
import type { DisplayCreated, DisplayItem, DisplayKind, DisplayTarget, ResvDetail } from '@/lib/types';

// 지금 화면이 만든 요청(QR 은 만들 때 받은 토큰으로만 그린다 — 다시 읽을 수 없음)
interface Active {
  id: number;
  qrToken: string | null;
  expiresAt: string;
  deviceName: string | null;
}

// medikit-patches.css [Button-1] 의 flex-shrink:0 때문에 확인 창 두 버튼이 넘치지 않게(UndoConfirm 과 같음)
const SHRINK: React.CSSProperties = { flexShrink: 1, minWidth: 0 };
const OPEN_STATUS = new Set<DisplayItem['status']>(['pending', 'opened']);
const OPEN = (x: DisplayItem | undefined) => !!x && OPEN_STATUS.has(x.status);
const kindName = (k: DisplayTarget['kind']) => (k === 'tablet' ? '태블릿' : k === 'phone' ? '폰' : '기기');

// 이 예약 · 종류의 가장 최근 요청
function latest(d: ResvDetail, kind: DisplayKind): DisplayItem | undefined {
  return (d.displays ?? []).filter((x) => x.kind === kind).sort((a, b) => b.id - a.id)[0];
}

// 남은 시간 mm:ss — 0 이면 만료
function useRemain(expiresAt: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  const end = toMs(expiresAt);
  return end === null ? null : Math.max(0, Math.floor((end - now) / 1000));
}
const mmss = (s: number) => pad(Math.floor(s / 60)) + ':' + pad(s % 60);

function useTargets() {
  const [targets, setTargets] = useState<DisplayTarget[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api
      .displayTargets()
      .then((x) => {
        setTargets(x);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '기기 목록을 불러오지 못했어요'));
  }, []);
  return { targets, error, load };
}

function QrImage({ text, size }: { text: string; size: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    QRCode.toDataURL(text, { margin: 0, width: size * 2, errorCorrectionLevel: 'M' })
      .then((u) => live && setSrc(u))
      .catch(() => live && setSrc(null));
    return () => {
      live = false;
    };
  }, [text, size]);
  return (
    <span
      role="img"
      aria-label="고객 입력 QR"
      className="bg-ms-white"
      style={{ width: size + 16, height: size + 16, flexShrink: 0, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      {src && (
        // eslint-disable-next-line @next/next/no-img-element -- data URL QR
        <img src={src} alt="" width={size} height={size} />
      )}
    </span>
  );
}

function Dot({ on }: { on: boolean }) {
  return <span className={on ? 'bg-success' : 'bg-ms-gray-400'} title={on ? '접속 중' : '접속 안 함'} style={{ width: 8, height: 8, borderRadius: 4, flexShrink: 0, display: 'inline-block' }} />;
}

// 기기 고르기 목록(이름 · 폰/태블릿 · 접속 중 점)
function TargetList({ targets, error, onPick }: { targets: DisplayTarget[] | null; error: string | null; onPick: (t: DisplayTarget) => void }) {
  if (error) return <span className="text-typo-body-400 text-red" style={{ padding: 12 }}>{error}</span>;
  if (!targets) return <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>불러오는 중…</span>;
  if (!targets.length)
    return (
      <span className="text-typo-body-400 text-ms-gray-500" style={{ padding: 12 }}>
        코디 계정으로 로그인한 기기가 없어요
      </span>
    );
  return (
    <>
      {targets.map((t) => (
        <button
          key={t.deviceId}
          type="button"
          onClick={() => onPick(t)}
          className="bg-ms-white border-ms-white hover:bg-ms-gray-100"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', minHeight: 44, borderWidth: 1, borderStyle: 'solid', borderRadius: 8, cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}
        >
          <Dot on={t.online} />
          <span className="text-typo-body-600 text-ms-gray-800" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {t.name}
          </span>
          <span className="text-typo-body-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
            {kindName(t.kind)}
            {t.online ? ' · 접속 중' : t.lastSeenAt ? ' · ' + hm(t.lastSeenAt) : ''}
          </span>
        </button>
      ))}
    </>
  );
}

// ── 「고객 기본 정보」 머리 [QR로 고객 입력 요청] + QR 상자(SPEC-006 §8.1 · S4§6.17 자리) — 머리 버튼(toggle)과 상자(box)를 따로 돌려준다.
// QR = qrUrl(https://…/q#<토큰> · 고객 휴대폰 카메라로) · 단계 = displays[] 5초 폴링: pending(QR · 남은 시간) → opened 「고객이 입력 중」(QR 숨김) →
// done 「제출됨」 · expired [다시 만들기] · canceled = 상자 닫힘. 새로고침해도 displays[].qrUrl 로 다시 그린다
const Q_TTL_MS = 10 * 60 * 1000; // 여는 시한(PROC_DISPLAY_TTL_MIN 기본) — displays[] 에 expiresAt 이 없을 때 남은 시간 계산용

interface QReq {
  id: number;
  status: DisplayItem['status'];
  qrUrl: string | null;
  expiresAt: string | null;
  openedAt: string | null;
  closedAt: string | null;
  deviceName: string | null;
}

export function useQuestionnaireRequest({ d, onError }: { d: ResvDetail; onError: (e: unknown) => void }) {
  const [made, setMade] = useState<(DisplayCreated & { deviceName: string | null }) | null>(null);
  const [want, setWant] = useState(false); // [QR로 고객 입력 요청]을 눌러 상자를 연 채
  const [hiddenId, setHiddenId] = useState<number | null>(null); // [QR 닫기]로 접은 요청(요청은 살아 있음)
  const [busy, setBusy] = useState(false);
  const [pickOpen, setPickOpen] = useState(false);
  const { targets, error, load } = useTargets();

  const items = (d.displays ?? []).filter((x) => x.kind === 'questionnaire').sort((a, b) => b.id - a.id);
  const last = items[0];
  // 지금 상자의 요청 — 이 화면이 방금 만든 것(폴링 전) 또는 상세의 가장 최근 것
  const req: QReq | null =
    made && (!last || made.id >= last.id)
      ? (() => {
          const it = items.find((x) => x.id === made.id);
          return {
            id: made.id,
            status: it?.status ?? 'pending',
            qrUrl: it ? (it.qrUrl ?? null) : (made.qrUrl ?? null),
            expiresAt: made.expiresAt,
            openedAt: it?.openedAt ?? null,
            closedAt: it?.closedAt ?? null,
            deviceName: it?.deviceName ?? made.deviceName,
          };
        })()
      : last
        ? {
            id: last.id,
            status: last.status,
            qrUrl: last.qrUrl ?? null,
            expiresAt: new Date((toMs(last.createdAt) ?? 0) + Q_TTL_MS).toISOString(),
            openedAt: last.openedAt ?? null,
            closedAt: last.closedAt,
            deviceName: last.deviceName,
          }
        : null;
  const remain = useRemain(req?.status === 'pending' ? req.expiresAt : null);
  const expired = req?.status === 'expired' || (req?.status === 'pending' && remain === 0);
  const live = !!req && OPEN_STATUS.has(req.status) && !expired;
  const doneToday = items.find((x) => x.status === 'done'); // 오늘 이미 제출(displays[] = 오늘 것)
  // 이 화면에서 살아 있는 채 본 요청 — 그 뒤 done · expired 가 돼도 상자에 「제출됨」 · 「시간이 지났어요」를 남긴다(이전 렌더 값 저장 꼴)
  const [seenId, setSeenId] = useState<number | null>(null);
  if (live && req && seenId !== req.id) setSeenId(req.id);
  // 상자 = 눌러서 열었거나 · 살아 있는(또는 살아 있는 채 본) 요청이 접히지 않았을 때 · canceled = 닫힘
  const open = req ? req.status !== 'canceled' && hiddenId !== req.id && (want || live || seenId === req.id) : want;

  const make = useCallback(
    async (t?: DisplayTarget) => {
      setBusy(true);
      try {
        const r = await api.createDisplay(d.reservationId, 'questionnaire', t?.deviceId);
        setMade({ ...r, deviceName: t?.name ?? null });
        setWant(true);
      } catch (e) {
        onError(e);
      } finally {
        setBusy(false);
      }
    },
    [d.reservationId, onError],
  );

  const toggle = () => {
    if (open) {
      setWant(false);
      if (req) setHiddenId(req.id);
      return;
    }
    setWant(true);
    setHiddenId(null);
    if (!live) void make();
  };

  const close = async () => {
    if (!req) return;
    setBusy(true);
    try {
      if (live) await api.closeDisplay(req.id, 'canceled'); // 고객 폰 링크 = 「새 QR …」 화면
      setWant(false);
      setHiddenId(req.id);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const doneLine = doneToday && (
    <span className="text-typo-body-500 text-primary" style={{ whiteSpace: 'nowrap' }}>
      오늘 이미 제출함 · {hm(doneToday.closedAt)}
    </span>
  );

  // 단계 글
  const step = !req
    ? busy
      ? '만드는 중…'
      : '요청을 만들지 못했어요'
    : expired
      ? '시간이 지났어요'
      : req.status === 'opened'
        ? '고객이 입력 중' + (req.openedAt ? ' · ' + hm(req.openedAt) : '')
        : req.status === 'done'
          ? '제출됨 · ' + hm(req.closedAt)
          : '고객 휴대폰 카메라로 찍어 주세요' + (remain !== null ? ' · 남은 시간 ' + mmss(remain) : '');
  const badge: { v: 'primary' | 'warning' | 'neutral' | 'purple'; t: string } | null = !req
    ? null
    : expired
      ? { v: 'neutral', t: '만료' }
      : req.status === 'opened'
        ? { v: 'purple', t: '입력 중' }
        : req.status === 'done'
          ? { v: 'primary', t: '제출됨' }
          : { v: 'warning', t: '대기' };
  const showQr = !!req && req.status === 'pending' && !expired && !!req.qrUrl;

  return {
    toggle: (
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {!open && live && badge && (
          <Badge variant={badge.v} size="sm">
            문진 {badge.t}
          </Badge>
        )}
        {!open && doneLine}
        <button type="button" onClick={toggle} className="text-typo-body-500 text-primary" style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', whiteSpace: 'nowrap' }}>
          {open ? 'QR 닫기' : 'QR로 고객 입력 요청'}
        </button>
      </span>
    ),
    box: open ? (
      <div className="bg-ms-gray-100" style={{ padding: 14, borderRadius: 8, display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        {showQr ? (
          <QrImage text={req.qrUrl!} size={104} />
        ) : (
          <span className="bg-ms-white text-typo-body-500 text-ms-gray-500" style={{ width: 120, height: 120, flexShrink: 0, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: 8, boxSizing: 'border-box' }}>
            {busy && !req ? '만드는 중…' : expired ? '만료됨' : req?.status === 'opened' ? '입력 중' : req?.status === 'done' ? '제출됨' : 'QR 없음'}
          </span>
        )}
        <div style={{ flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {doneLine}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-body-600 text-ms-gray-800">고객이 직접 입력 (QR)</span>
            {badge && (
              <Badge variant={badge.v} size="sm">
                {badge.t}
              </Badge>
            )}
          </div>
          <span className="text-typo-body-400 text-ms-gray-600">{step}</span>
          <span className="text-typo-caption-md-400 text-ms-gray-500">QR 은 10분 동안 열 수 있어요 · 고객이 연 뒤 60분 안에 제출</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <Popover
              open={pickOpen}
              onOpenChange={(v) => {
                setPickOpen(v);
                if (v) load();
              }}
            >
              <PopoverTrigger asChild>
                <Button variant="solid" color="blue" size="sm" disabled={busy}>
                  {req?.deviceName && live ? req.deviceName + '에 표시 중' : '태블릿에 띄우기'}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" side="bottom" avoidCollisions collisionPadding={12} className="p-0" style={{ width: 320 }}>
                <div className="border-ms-gray-200" style={{ padding: '12px 16px', borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
                  <span className="text-typo-heading-md-500 text-ms-gray-800">띄울 기기</span>
                </div>
                <div style={{ maxHeight: 260, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 2, padding: 4 }}>
                  <TargetList
                    targets={targets}
                    error={error}
                    onPick={(t) => {
                      setPickOpen(false);
                      void make(t);
                    }}
                  />
                </div>
              </PopoverContent>
            </Popover>
            {(!req || !live) && (
              <Button variant="outlined" color="blue" size="sm" disabled={busy} onClick={() => void make()}>
                다시 만들기
              </Button>
            )}
            <Button variant="outlined" color="gray" size="sm" disabled={busy} onClick={() => void close()}>
              닫기
            </Button>
          </div>
        </div>
      </div>
    ) : null,
  };
}

// 신분증 사진 썸네일 — fetch + Bearer → blob URL · 닫으면 revoke(§6.17 r2)
function IdPhoto({ photoId }: { photoId: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [big, setBig] = useState(false);
  useEffect(() => {
    let live = true;
    let made: string | null = null;
    api
      .idPhotoUrl(photoId)
      .then((u) => {
        made = u;
        if (live) setUrl(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [photoId]);
  const box = { width: 72, height: 48, flexShrink: 0, borderRadius: 6, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' } as const;
  if (!url)
    return (
      <span className="bg-primary-100 border-primary text-primary text-typo-caption-md-400" style={{ ...box, borderWidth: 1, borderStyle: 'dashed' }}>
        {failed ? '사진 없음' : '…'}
      </span>
    );
  return (
    <>
      <button type="button" aria-label="여권 사진 크게 보기" onClick={() => setBig(true)} className="border-ms-gray-300" style={{ ...box, padding: 0, borderWidth: 1, borderStyle: 'solid', cursor: 'zoom-in', background: 'transparent' }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- blob URL(인증 받은 사진) */}
        <img src={url} alt="여권 사진" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      </button>
      {big && (
        <div
          onClick={(e) => {
            e.stopPropagation();
            setBig(false);
          }}
          style={{ position: 'fixed', inset: 0, zIndex: 60, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, cursor: 'zoom-out' }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- blob URL */}
          <img src={url} alt="여권 사진" style={{ maxWidth: 'min(900px, 90vw)', maxHeight: '85vh', borderRadius: 8, background: '#fff' }} />
        </div>
      )}
    </>
  );
}

// ── 「신분 확인」 [스캔할 기기] 단계(§6.17 · W:308-342): idle(기기 버튼만 — QR 칸 뺌 · E2E batch 3 추가) → wait → done(썸네일 · [삭제])
export function ScanSteps({ d, onError, onChanged }: { d: ResvDetail; onError: (e: unknown) => void; onChanged: (toast: string) => void }) {
  const id = d.customer.identity;
  const pre = d.flow === null;
  const [made, setActive] = useState<Active | null>(null);
  const [rescanOf, setRescanOf] = useState<string | null>(null); // [다시 스캔]을 누른 때의 신분 확인 시각 — 새 스캔이 들어오면 저절로 풀림
  const [busy, setBusy] = useState(false);
  const [askDelete, setAskDelete] = useState(false);
  const { targets, error, load } = useTargets();
  const last = latest(d, 'scan');
  const mine = made ? (d.displays ?? []).find((x) => x.id === made.id) : undefined;
  // 내가 만든 요청이 끝나면(done · canceled · expired) 상세 값으로 돌아간다
  const active = made && (!mine || OPEN(mine)) ? made : null;
  // 이 화면이 만든 요청이 없으면 상세의 열린 요청(다른 탭 · 다시 연 상세)을 이어 그린다
  const cur: Active | null = active ?? (OPEN(last) && last ? { id: last.id, qrToken: null, expiresAt: '', deviceName: last.deviceName } : null);
  const curItem = active ? mine : last;
  const scanned = (id.method === 'app_scan' || id.method === 'app_manual') && id.status === 'confirmed';
  const rescan = scanned && rescanOf === (id.checkedAt ?? '');

  const phase: 'idle' | 'wait' | 'done' = cur && (!curItem || OPEN(curItem))
    ? 'wait'
    : scanned && !rescan
      ? 'done'
      : 'idle';

  useEffect(() => {
    if (phase === 'idle') load();
  }, [phase, load]);

  const start = async (t: DisplayTarget) => {
    setBusy(true);
    try {
      const r = await api.createDisplay(d.reservationId, 'scan', t.deviceId);
      setActive({ id: r.id, qrToken: r.qrToken, expiresAt: r.expiresAt, deviceName: t.name });
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  const cancel = async () => {
    if (!cur) return;
    setBusy(true);
    try {
      await api.closeDisplay(cur.id, 'canceled');
      setActive(null);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  // [삭제] — ccc 사진 · 신분 확인(→ 미확인) · KOS 이미지(E2E batch 3 #1) · 자동 입력된 고객 값은 그대로
  const remove = async () => {
    if (!id.photoId) return;
    setAskDelete(false);
    setBusy(true);
    try {
      const r = await api.deleteIdPhoto(id.photoId);
      onChanged('여권 사진을 지웠어요' + (r.kos === 'deleted' ? ' · KOS 사진도 지움' : r.kos === 'not_found' ? ' · KOS 에는 이미 없었어요' : ' · KOS 로 올라가지 않은 사진'));
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  if (phase === 'idle') {
    const devs = targets ?? [];
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <span className="text-typo-body-400 text-ms-gray-500" style={{ marginRight: 4 }}>
          스캔할 기기
        </span>
        {devs.map((t) => (
          <Button key={t.deviceId} variant="outlined" color="blue" size="sm" disabled={busy} onClick={() => void start(t)} leftIcon={<Dot on={t.online} />}>
            {t.name}
          </Button>
        ))}
        {error && <span className="text-typo-body-400 text-red">{error}</span>}
        {targets && !devs.length && <span className="text-typo-body-400 text-ms-gray-500">연결된 기기가 없어요</span>}
        {rescan && scanned && (
          <button type="button" onClick={() => setRescanOf(null)} className="text-typo-body-500 text-ms-gray-600" style={{ border: 'none', background: 'transparent', cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
            그대로 두기
          </button>
        )}
      </div>
    );
  }

  if (phase === 'wait') {
    const dev = curItem?.deviceName ?? cur?.deviceName;
    const text = curItem?.status === 'opened' ? (dev ? dev + '에서 스캔 중' : '스캔 중') + ' · 촬영 대기 중…' : (dev ? dev + '에 보냈어요' : 'QR 대기 중') + ' · 여는 중…';
    return (
      <div className="bg-primary-100 border-primary" style={{ padding: '12px 14px', borderRadius: 8, borderWidth: 1, borderStyle: 'solid', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="text-typo-body-600 text-primary" style={{ flex: 1, minWidth: 0 }}>
          {text}
        </span>
        <Button variant="outlined" color="gray" size="sm" disabled={busy} onClick={() => void cancel()}>
          취소
        </Button>
      </div>
    );
  }

  // done — 썸네일 + 「{기기}에서 수신 · HH:MM · 자동 입력됨(확인 후 수정 가능)」
  const how = id.method === 'app_manual' ? '손으로 입력' : '자동 입력됨 (확인 후 수정 가능)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      {id.photoId ? (
        <IdPhoto key={id.photoId} photoId={id.photoId} />
      ) : (
        <span className="bg-primary-100 border-primary text-primary text-typo-body-500" style={{ width: 72, height: 48, flexShrink: 0, borderWidth: 1, borderStyle: 'dashed', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          여권
        </span>
      )}
      <span className="text-typo-body-400 text-ms-gray-600" style={{ flex: 1, minWidth: 0 }}>
        {(id.device ? id.device + '에서 ' : '') + '수신' + (id.checkedAt ? ' · ' + hm(id.checkedAt) : '') + ' · ' + how}
      </span>
      {id.photoKos === 'failed' && (
        <Badge variant="warning" size="sm">
          KOS 사진 실패
        </Badge>
      )}
      {id.photoId && (
        <Button variant="outlined" color="red" size="sm" disabled={busy} onClick={() => setAskDelete(true)}>
          {busy ? '지우는 중…' : '삭제'}
        </Button>
      )}
      {askDelete && (
        <ConfirmModal
          isOpen
          title="여권 사진을 지울까요?"
          description="ccc · KOS 의 사진을 지우고 신분 확인을 미확인으로 돌려요. 자동 입력된 고객 정보(여권번호 등)는 그대로 남아요."
          variant="caution"
          onBackdropClick={() => setAskDelete(false)}
          leftButton={{ label: '취소', onClick: () => setAskDelete(false), style: SHRINK }}
          rightButton={{ label: '삭제', onClick: () => void remove(), style: SHRINK }}
        />
      )}
      {pre && (
        <button type="button" onClick={() => setRescanOf(id.checkedAt ?? '')} className="text-typo-body-500 text-ms-gray-600" style={{ border: 'none', background: 'transparent', cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
          다시 스캔
        </button>
      )}
    </div>
  );
}
