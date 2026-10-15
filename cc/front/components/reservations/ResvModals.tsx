'use client';

import { useState } from 'react';
import { Button, Modal } from '@medisolve-ai/medikit';
import type { ResvRequest } from '@/lib/types';
import { type Chain, type Seg, changedCount, dayLabel, previewRows, stamp } from './resv';

// 시안 seg — 이전 값 취소선(회색) → 새 값 굵은 파랑
export function Segs({ segs }: { segs: Seg[] }) {
  return (
    <>
      {segs.map((s, i) => (
        <span
          key={i}
          style={
            s.k === 'old'
              ? { textDecoration: 'line-through', color: '#9f9f9f' }
              : s.k === 'new'
                ? { fontWeight: 700, color: '#1d7f9e' }
                : undefined
          }
        >
          {s.t}
        </span>
      ))}
    </>
  );
}

// 시안 모달 틀 — medikit Modal 에 시안 크기(16px 모서리 · 폭 · 화면 안 최대 높이)
function Frame({ width, onClose, children }: { width: number; onClose: () => void; children: React.ReactNode }) {
  return (
    <Modal isOpen onBackdropClick={onClose} className="p-0 rounded-[16px] shadow-[0_16px_48px_rgba(0,0,0,0.2)]">
      <div
        style={{
          width,
          maxWidth: 'calc(100vw - 32px)',
          maxHeight: 'calc(100vh - 48px)',
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {children}
      </div>
    </Modal>
  );
}

function Head({ title, sub, onClose, pad }: { title: string; sub?: string; onClose: () => void; pad: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, padding: pad }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className="text-typo-title-sm-600 text-ms-gray-800">{title}</span>
        {sub && <span className="text-typo-body-400 text-ms-gray-600">{sub}</span>}
      </div>
      <button type="button" className="cc-btn" onClick={onClose} aria-label="닫기" style={{ padding: 4 }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8a8a8a" strokeWidth="2" strokeLinecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  );
}

// ① KOS 등록 · 수정 미리보기 — 수정은 바뀐 항목 강조
export function PreviewModal({
  r,
  now,
  busy,
  onClose,
  onSubmit,
}: {
  r: ResvRequest;
  now: number;
  busy: boolean;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const mod = r.status === 'modify_requested';
  const rows = previewRows(r, now);
  const close = () => {
    if (!busy) onClose();
  };
  return (
    <Frame width={640} onClose={close}>
      <Head
        title={mod ? 'KOS 수정 미리보기' : 'KOS 등록 미리보기'}
        sub={mod ? '바뀐 항목 ' + changedCount(r) + '개' : undefined}
        onClose={close}
        pad="22px 24px 6px"
      />
      <div style={{ padding: '14px 24px 4px' }}>
        <div className="border-ms-gray-200" style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 12, overflow: 'hidden' }}>
          {rows.map((f, i) => (
            <div
              key={f.label}
              className={(i === 0 ? 'border-ms-white' : 'border-ms-gray-200') + (f.segs.some((s) => s.k) ? ' bg-primary-100' : '')}
              style={{
                display: 'grid',
                gridTemplateColumns: '120px minmax(0,1fr)',
                gap: 12,
                padding: '11px 16px',
                borderTopWidth: 1,
                borderTopStyle: 'solid',
                alignItems: 'start',
              }}
            >
              <span className="text-typo-body-500 text-ms-gray-600">{f.label}</span>
              <span
                className="text-typo-body-500 text-ms-gray-800"
                style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontVariantNumeric: 'tabular-nums' }}
              >
                <Segs segs={f.segs} />
              </span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '18px 24px 22px' }}>
        <Button variant="outlined" color="gray" size="lg" onClick={close}>
          취소
        </Button>
        {/* kos api 연동 필요 — 등록: KOS 예약 생성 · 수정: KOS 예약 변경. back 은 상태만 바꾸고 snapshot 을 남긴다(D-18) */}
        <Button variant="solid" color="blue" size="lg" isLoading={busy} onClick={() => !busy && onSubmit()}>
          {mod ? '수정하기' : '등록하기'}
        </Button>
      </div>
    </Frame>
  );
}

// ② 스크린샷 보기 — snapshot 을 KOS 예약 카드 모양으로(값은 back 가짜 풀)
export function ShotModal({ c, r, onClose }: { c: Chain; r: ResvRequest; onClose: () => void }) {
  const k = r.snapshot;
  if (!k) return null;
  const idx = c.rows.indexOf(r) + 1;
  const chips = [
    { t: k.nat, fg: '#333', bg: '#f5f5f5', bd: '#ddd' },
    { t: k.sex, fg: '#333', bg: '#f5f5f5', bd: '#ddd' },
    k.isNew ? { t: k.visitType, fg: '#e08a00', bg: '#fff7e6', bd: '#ffd591' } : { t: k.visitType, fg: '#333', bg: '#f5f5f5', bd: '#ddd' },
    { t: '유입 · ' + k.source, fg: '#333', bg: '#f5f5f5', bd: '#ddd' },
  ];
  const label = { color: '#666' };
  return (
    <Frame width={520} onClose={onClose}>
      <Head
        title={(c.rows.length > 1 ? '예약 ' + idx + ' · ' : '') + 'KOS 등록 화면'}
        sub={stamp(k.at) + ' ' + (k.kind === 'modify' ? 'KOS 수정' : 'KOS 등록') + (r.status === 'superseded' ? ' · 이력 보관' : '')}
        onClose={onClose}
        pad="22px 24px 10px"
      />
      {/* 스크린샷 자리 — 지금은 HTML 로 그린다. 원본 캡처는 사용자가 준다(D-12 · OQ-402) */}
      <div className="bg-ms-gray-100" style={{ margin: '6px 24px 24px', borderRadius: 12, padding: 20, display: 'flex', justifyContent: 'center' }}>
        <div
          style={{
            width: 330,
            maxWidth: '100%',
            background: '#fff',
            borderRadius: 12,
            boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            overflow: 'hidden',
            fontSize: 13,
            color: '#222',
          }}
        >
          <div style={{ background: '#d84b93', color: '#fff', fontWeight: 700, fontSize: 14, padding: '9px 14px' }}>예약</div>
          <div style={{ padding: '14px 16px 12px', borderBottom: '1px solid #eee', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 16, fontWeight: 700 }}>{k.name}</span>
              <span style={{ color: '#777' }}>{k.reading}</span>
              <span style={{ color: '#ccc' }}>|</span>
              <span style={{ color: '#777' }}>{k.chart}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '72px 1fr', alignItems: 'center', gap: 8 }}>
              <span style={label}>현재위치</span>
              <span style={{ border: '1px solid #ddd', borderRadius: 6, padding: '5px 10px', display: 'flex', justifyContent: 'space-between' }}>
                {k.floor}
                <span style={{ color: '#aaa' }}>⌄</span>
              </span>
            </div>
          </div>
          <div
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid #eee',
              display: 'grid',
              gridTemplateColumns: '72px 1fr',
              rowGap: 8,
              columnGap: 8,
            }}
          >
            <span style={label}>생년월일</span>
            <span>{k.birth}</span>
            <span style={label}>최근방문일</span>
            <span>{k.lastVisit}</span>
            <span style={label}>연락처</span>
            <span>{k.phone}</span>
            <span style={{ ...label, gridColumn: '1 / span 2', paddingTop: 4 }}>주요 정보</span>
            <div style={{ gridColumn: '1 / span 2', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {chips.map((x) => (
                <span key={x.t} style={{ border: '1px solid ' + x.bd, color: x.fg, background: x.bg, borderRadius: 5, padding: '2px 8px' }}>
                  {x.t}
                </span>
              ))}
            </div>
          </div>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #eee', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={label}>예약 일정</span>
            <span
              style={{
                background: '#eef3fd',
                borderLeft: '3px solid #3b7be8',
                borderRadius: 4,
                padding: '7px 10px',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {k.time + ' ~ ' + k.endTime + '  ·  ' + dayLabel(k.date)} <b style={{ marginLeft: 6 }}>{k.zone}</b>
            </span>
            <span style={{ ...label, paddingTop: 4 }}>희망 시술</span>
            <span>{k.proc}</span>
          </div>
          <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={label}>예약 메모</span>
            <span style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{k.memo}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, padding: '4px 16px 14px' }}>
            <span style={{ border: '1px solid #ccc', borderRadius: 6, padding: '5px 10px', color: '#444' }}>예약 이동하기</span>
            <span style={{ background: '#3b7be8', borderRadius: 6, padding: '5px 10px', color: '#fff' }}>고객차트 보기</span>
          </div>
        </div>
      </div>
    </Frame>
  );
}

// ③ 변경 요청하기 — 사유는 텍스트(D-13), 비면 막힘
export function ChangeModal({
  r,
  busy,
  onClose,
  onSubmit,
}: {
  r: ResvRequest;
  busy: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const [text, setText] = useState('');
  const blank = !text.trim();
  const c = r.customer;
  return (
    <Frame width={560} onClose={onClose}>
      <Head title="변경 요청하기" onClose={onClose} pad="22px 24px 6px" />
      <div style={{ padding: '14px 24px 0', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="bg-ms-gray-100" style={{ borderRadius: 10, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span className="text-typo-body-600 text-ms-gray-800">
            {c.name} <span className="text-typo-caption-md-400 text-ms-gray-600">{c.nat + ' · ' + (c.isNew ? '첫내원' : '재내원')}</span>
          </span>
          <span className="text-typo-body-500 text-ms-gray-800" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {dayLabel(r.date) + ' ' + r.time} · {r.proc + ' · 통역 ' + r.lang}
          </span>
        </div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span className="text-typo-body-600 text-ms-gray-800">사유</span>
          <textarea
            className="rv-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="예) 그 시간은 원장 상담이 마감됐어요. 같은 날 14:00 이후로 가능해요"
          />
        </label>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, padding: '18px 24px 22px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button variant="outlined" color="gray" size="lg" onClick={onClose}>
            취소
          </Button>
          {/* 링키 연동 필요 — 변경 요청 · 사유를 본사(링키)로 보낸다. 데모는 줄 상태만 바꾼다 */}
          <Button
            variant="solid"
            color={blank ? 'gray' : 'blue'}
            size="lg"
            disabled={blank || busy}
            isLoading={busy}
            onClick={() => !blank && !busy && onSubmit(text)}
          >
            변경 요청 보내기
          </Button>
        </div>
      </div>
    </Frame>
  );
}
