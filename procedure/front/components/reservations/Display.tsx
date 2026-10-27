'use client';

// 예약 상세 — 띄우기 · 여권 스캔 자리(SPEC-004 §6.17 · §5-3 · 시안 W:276-289 QR 상자 · W:308-342 스캔 단계)
// 단계는 상세 응답 displays[](5초 폴링)로만 그린다. QR 내용 = 앱 스킴 ccc://display?t= · [링크 복사] · [메신저 전송] 없음(D7-44)
import { useCallback, useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Badge, Button, Popover, PopoverContent, PopoverTrigger } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { hm, pad, toMs } from '@/lib/time';
import type { DisplayItem, DisplayKind, DisplayTarget, ResvDetail } from '@/lib/types';

// 지금 화면이 만든 요청(QR 은 만들 때 받은 토큰으로만 그린다 — 다시 읽을 수 없음)
interface Active {
  id: number;
  qrToken: string | null;
  expiresAt: string;
  deviceName: string | null;
}

const OPEN = (x: DisplayItem | undefined) => !!x && (x.status === 'pending' || x.status === 'opened');
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

// 요청 단계 글(웹 상세 · 5초 폴링)
function stepText(x: DisplayItem | undefined, deviceName: string | null): string {
  const dev = x?.deviceName ?? deviceName;
  switch (x?.status) {
    case 'opened':
      return (dev ? dev + '에서 ' : '') + '열림 · 고객 입력 중';
    case 'done':
      return '제출됨 · ' + hm(x.closedAt);
    case 'canceled':
      return '닫힘';
    case 'expired':
      return '만료됨';
    default:
      return dev ? dev + '에 표시 중 · 대기' : 'QR 대기 중';
  }
}
const stepBadge = (x: DisplayItem | undefined): { v: 'primary' | 'warning' | 'neutral' | 'purple'; t: string } =>
  x?.status === 'done'
    ? { v: 'primary', t: '제출됨' }
    : x?.status === 'opened'
      ? { v: 'purple', t: '열림' }
      : x?.status === 'canceled' || x?.status === 'expired'
        ? { v: 'neutral', t: x.status === 'expired' ? '만료' : '닫힘' }
        : { v: 'warning', t: '대기' };

// ── 「고객 기본 정보」 머리 [QR로 고객 입력 요청] + QR 상자(§6.17 · W:276-289) — 머리 버튼(toggle)과 상자(box)를 따로 돌려준다
export function useQuestionnaireRequest({ d, onError }: { d: ResvDetail; onError: (e: unknown) => void }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<Active | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickOpen, setPickOpen] = useState(false);
  const { targets, error, load } = useTargets();
  const remain = useRemain(active?.qrToken ? active.expiresAt : null);
  const last = latest(d, 'questionnaire');
  const mine = active ? (d.displays ?? []).find((x) => x.id === active.id) : undefined;

  const make = useCallback(
    async (t?: DisplayTarget) => {
      setBusy(true);
      try {
        const r = await api.createDisplay(d.reservationId, 'questionnaire', t?.deviceId);
        setActive({ id: r.id, qrToken: r.qrToken, expiresAt: r.expiresAt, deviceName: t?.name ?? null });
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
      setOpen(false);
      return;
    }
    setOpen(true);
    if (!active || !OPEN(mine)) void make();
  };

  const close = async () => {
    if (!active) return;
    setBusy(true);
    try {
      if (!mine || OPEN(mine)) await api.closeDisplay(active.id, 'canceled');
      setActive(null);
      setOpen(false);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const expired = mine?.status === 'expired' || (mine?.status === 'pending' && remain === 0);
  const b = stepBadge(open ? mine : last);

  return {
    toggle: (
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {!open && last && last.status !== 'canceled' && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Badge variant={b.v} size="sm">
              문진 {b.t}
            </Badge>
            <span className="text-typo-body-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
              {stepText(last, null)}
            </span>
          </span>
        )}
        <button type="button" onClick={toggle} className="text-typo-body-500 text-primary" style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', whiteSpace: 'nowrap' }}>
          {open ? 'QR 닫기' : 'QR로 고객 입력 요청'}
        </button>
      </span>
    ),
    box: open ? (
      <div className="bg-ms-gray-100" style={{ padding: 14, borderRadius: 8, display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        {active?.qrToken && !expired && mine?.status !== 'done' ? (
          <QrImage text={api.displayQrText(active.qrToken)} size={104} />
        ) : (
          <span className="bg-ms-white text-typo-body-400 text-ms-gray-500" style={{ width: 120, height: 120, flexShrink: 0, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
            {busy ? '만드는 중…' : mine?.status === 'done' ? '제출됨' : expired ? '만료됨' : 'QR 없음'}
          </span>
        )}
        <div style={{ flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="text-typo-body-600 text-ms-gray-800">고객이 직접 입력 (QR)</span>
            {active && (
              <Badge variant={b.v} size="sm">
                {b.t}
              </Badge>
            )}
          </div>
          <span className="text-typo-body-400 text-ms-gray-600">
            {active
              ? stepText(mine ?? { id: active.id, kind: 'questionnaire', status: 'pending', deviceName: active.deviceName, createdAt: '', closedAt: null }, active.deviceName)
              : '요청을 만들지 못했어요'}
            {active?.qrToken && remain !== null && !expired && (!mine || mine.status === 'pending') ? ' · 남은 시간 ' + mmss(remain) : ''}
          </span>
          <span className="text-typo-caption-md-400 text-ms-gray-500">코디 폰 앱 [QR 읽기]로 찍으면 문진이 열려요 · 10분 동안만 유효해요</span>
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
                  {active?.deviceName && (!mine || OPEN(mine)) ? active.deviceName + '에 표시 중' : '태블릿에 띄우기'}
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
            {(expired || mine?.status === 'done' || mine?.status === 'canceled' || !active) && (
              <Button variant="outlined" color="blue" size="sm" disabled={busy} onClick={() => void make()}>
                새 QR
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

// ── 「신분 확인」 [스캔할 기기] 단계(§6.17 · W:308-342): idle → qr | wait → done
export function ScanSteps({ d, onError }: { d: ResvDetail; onError: (e: unknown) => void }) {
  const id = d.customer.identity;
  const pre = d.flow === null;
  const [made, setActive] = useState<Active | null>(null);
  const [rescanOf, setRescanOf] = useState<string | null>(null); // [다시 스캔]을 누른 때의 신분 확인 시각 — 새 스캔이 들어오면 저절로 풀림
  const [busy, setBusy] = useState(false);
  const { targets, error, load } = useTargets();
  const last = latest(d, 'scan');
  const mine = made ? (d.displays ?? []).find((x) => x.id === made.id) : undefined;
  // 내가 만든 요청이 끝나면(done · canceled · expired) 상세 값으로 돌아간다
  const active = made && (!mine || OPEN(mine)) ? made : null;
  // 이 화면이 만든 요청이 없으면 상세의 열린 요청(다른 탭 · 다시 연 상세)을 이어 그린다
  const cur: Active | null = active ?? (OPEN(last) && last ? { id: last.id, qrToken: null, expiresAt: '', deviceName: last.deviceName } : null);
  const curItem = active ? mine : last;
  const remain = useRemain(active?.qrToken ? active.expiresAt : null);
  const scanned = (id.method === 'app_scan' || id.method === 'app_manual') && id.status === 'confirmed';
  const rescan = scanned && rescanOf === (id.checkedAt ?? '');

  const phase: 'idle' | 'qr' | 'wait' | 'done' = cur && (!curItem || OPEN(curItem))
    ? cur.qrToken && !(curItem?.deviceName ?? cur.deviceName) && curItem?.status !== 'opened'
      ? 'qr'
      : 'wait'
    : scanned && !rescan
      ? 'done'
      : 'idle';

  useEffect(() => {
    if (phase === 'idle') load();
  }, [phase, load]);

  const start = async (t?: DisplayTarget) => {
    setBusy(true);
    try {
      const r = await api.createDisplay(d.reservationId, 'scan', t?.deviceId);
      setActive({ id: r.id, qrToken: r.qrToken, expiresAt: r.expiresAt, deviceName: t?.name ?? null });
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
        <Button variant="outlined" color="gray" size="sm" disabled={busy} onClick={() => void start()}>
          QR
        </Button>
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

  if (phase === 'qr' && cur?.qrToken) {
    const expired = remain === 0;
    return (
      <div className="bg-ms-gray-100" style={{ padding: 12, borderRadius: 8, display: 'flex', alignItems: 'center', gap: 14 }}>
        {expired ? (
          <span className="bg-ms-white text-typo-body-400 text-ms-gray-500" style={{ width: 104, height: 104, flexShrink: 0, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            만료됨
          </span>
        ) : (
          <QrImage text={api.displayQrText(cur.qrToken)} size={88} />
        )}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="text-typo-body-600 text-ms-gray-800">{targets?.length ? 'QR로 다른 기기 연결' : '연결된 기기가 없어요 · QR로 스캐너 열기'}</span>
          <span className="text-typo-body-400 text-ms-gray-600">
            코디 폰 앱 [QR 읽기]로 찍으면 스캐너가 열리고, 찍은 결과가 여기로 들어옵니다. 링크는 10분 동안만 유효합니다.
            {remain !== null && !expired ? ' · 남은 시간 ' + mmss(remain) : ''}
          </span>
          <div style={{ display: 'flex', gap: 6 }}>
            {expired && (
              <Button variant="outlined" color="blue" size="sm" disabled={busy} onClick={() => void start()}>
                새 QR
              </Button>
            )}
            <Button variant="outlined" color="gray" size="sm" disabled={busy} onClick={() => void cancel()}>
              취소
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === 'wait' || phase === 'qr') {
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
      {pre && (
        <button type="button" onClick={() => setRescanOf(id.checkedAt ?? '')} className="text-typo-body-500 text-ms-gray-600" style={{ border: 'none', background: 'transparent', cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
          다시 스캔
        </button>
      )}
    </div>
  );
}
