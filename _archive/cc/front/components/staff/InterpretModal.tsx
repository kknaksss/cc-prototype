'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@medisolve-ai/medikit';
import { InterpretSession, type Caption, type InterpErrorKind, type InterpState } from '@/lib/interpret';
import { LANGS, LANG_NAME, defaultLang, isTraditional, natName } from './common';

// 시안 IP_STATE
const IP_STATE: Record<InterpState, { text: string; cls: string; dot: string; hint: string; mic: string }> = {
  connecting: {
    text: '연결 중',
    cls: 'text-typo-body-600 text-ms-gray-700',
    dot: 'bg-ms-gray-500',
    hint: '마이크와 통역 서버를 연결하고 있어요',
    mic: 'bg-ms-gray-100 border-ms-gray-300',
  },
  listening: {
    text: '듣는 중',
    cls: 'text-typo-body-600 text-primary',
    dot: 'bg-primary',
    hint: '양쪽 말을 모두 들어요 · 누가 말했는지는 자동으로 구분해요 · 누르면 멈춤',
    mic: 'bg-primary border-primary ip-pulse',
  },
  paused: {
    text: '멈춤',
    cls: 'text-typo-body-600 text-ms-gray-700',
    dot: 'bg-ms-gray-500',
    hint: '누르면 다시 들어요',
    mic: 'bg-ms-white border-primary',
  },
  error: {
    text: '오류',
    cls: 'text-typo-body-600 text-red',
    dot: 'bg-red',
    hint: '마이크 권한을 허용한 뒤 다시 시도를 눌러 주세요',
    mic: 'bg-red-100 border-red',
  },
};

// 통역 모달(SPEC §7) — 폰: 아래에서 올라오는 시트 · 넓은 화면: 가운데 창
export function InterpretModal({
  scheduleId,
  name,
  nationality,
  wide,
  width,
  onClose,
}: {
  scheduleId: string;
  name: string;
  nationality: string;
  wide: boolean;
  width: number;
  onClose: () => void;
}) {
  const autoLang = defaultLang(nationality);
  const [lang, setLang] = useState(autoLang);
  const [langOpen, setLangOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<InterpState>('connecting');
  const [err, setErr] = useState<{ kind: InterpErrorKind; message: string } | null>(null);
  const [caps, setCaps] = useState<Caption[]>([]);
  // 번역 음성 재생 중 — 이 동안 마이크는 보내지 않는다(반이중). 상태는 「듣는 중」 그대로, 아이콘만 「재생 중」
  const [playing, setPlaying] = useState(false);
  const session = useRef<InterpretSession | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 모달 열기 = 연결 · 듣기 시작. 언어를 바꾸거나 다시 시도하면 새 연결
  useEffect(() => {
    const s = new InterpretSession(
      { scheduleId, lang, traditional: isTraditional(nationality, lang) },
      {
        onState: setState,
        onPlayback: setPlaying,
        onError: (kind, message) => setErr({ kind, message }),
        onCaption: (c) =>
          setCaps((prev) => {
            const i = prev.findIndex((x) => x.key === c.key);
            if (i < 0) return [...prev, c];
            const next = prev.slice();
            next[i] = c;
            return next;
          }),
      },
    );
    session.current = s;
    void s.start();
    return () => {
      s.close();
      if (session.current === s) session.current = null;
    };
  }, [scheduleId, nationality, lang, attempt]);

  // 새 말풍선 · 갱신 때 아래로
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [caps]);

  const restart = () => {
    setErr(null);
    setState('connecting');
    setPlaying(false);
    setAttempt((n) => n + 1);
  };
  const pick = (code: string) => {
    setLangOpen(false);
    if (code === lang) return;
    setErr(null);
    setState('connecting');
    setPlaying(false);
    setLang(code);
  };

  const st = IP_STATE[state];
  const isConn = state === 'connecting';
  const isErr = state === 'error';
  const micErr = err?.kind === 'mic';
  const empty = caps.length === 0;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 50,
        background: 'rgba(0,0,0,0.4)',
        display: 'flex',
        alignItems: wide ? 'center' : 'flex-end',
        justifyContent: 'center',
      }}
    >
      <div
        className="bg-ms-white"
        style={{
          width: '100%',
          maxWidth: wide ? 560 : width,
          height: wide ? 'min(720px, calc(100vh - 80px))' : 'calc(100% - 24px)',
          borderRadius: wide ? 16 : '16px 16px 0 0',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 10px 30px rgba(0,0,0,0.18)',
        }}
      >
        <div
          className="border-ms-gray-200"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            padding: '12px 12px 12px 16px',
            borderBottomWidth: 1,
            borderBottomStyle: 'solid',
          }}
        >
          <button
            type="button"
            onClick={() => setLangOpen((v) => !v)}
            className="cc-btn"
            style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}
          >
            <span
              className="text-typo-heading-md-500 text-ms-gray-800"
              style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}
            >
              통역 · <span className="text-primary">{LANG_NAME[lang]}</span>
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#2498bd"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ transform: `rotate(${langOpen ? '180deg' : '0deg'})` }}
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </span>
            <span
              className="text-typo-caption-md-400 text-ms-gray-600"
              style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {name} 님 · {nationality ? natName(nationality) + ' · ' : ''}
              {lang === autoLang ? '국적으로 자동 선택 · 눌러서 변경' : '직접 고른 언어 · 눌러서 변경'}
            </span>
          </button>
          <Button variant="outlined" color="gray" size="md" onClick={onClose}>
            닫기
          </Button>
        </div>

        {langOpen && (
          <div
            className="bg-ms-white border-ms-gray-200"
            style={{
              padding: '10px 16px 14px',
              display: 'flex',
              flexWrap: 'wrap',
              gap: 8,
              borderBottomWidth: 1,
              borderBottomStyle: 'solid',
            }}
          >
            {LANGS.map(([code, label]) => (
              <button
                key={code}
                type="button"
                onClick={() => pick(code)}
                className={
                  'cc-btn ' +
                  (code === lang
                    ? 'bg-primary-100 border-primary text-typo-body-600 text-primary'
                    : 'bg-ms-white border-ms-gray-300 text-typo-body-500 text-ms-gray-700')
                }
                style={{ padding: '7px 12px', borderRadius: 999, borderWidth: 1, borderStyle: 'solid', whiteSpace: 'nowrap' }}
              >
                {code === autoLang ? label + ' · 자동' : label}
              </button>
            ))}
          </div>
        )}

        {isErr && (
          <div
            className="bg-red-100"
            style={{ margin: '12px 16px 0', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            <span className="text-typo-caption-md-600 text-red">
              {micErr ? '마이크를 쓸 수 없어요' : '통역 서버에 연결하지 못했어요'}
            </span>
            <span className="text-typo-body-400 text-ms-gray-800" style={{ wordBreak: 'keep-all' }}>
              {err?.message}
            </span>
            <div>
              <Button variant="outlined" color="red" size="sm" onClick={restart}>
                다시 시도
              </Button>
            </div>
          </div>
        )}

        <div
          ref={listRef}
          className="bg-ms-gray-100"
          style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          {empty && (
            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                textAlign: 'center',
                padding: '24px 12px',
              }}
            >
              <span className="text-typo-body-500 text-ms-gray-700">
                {isConn ? '연결하는 중이에요' : isErr ? '듣지 못하고 있어요' : '아직 대화가 없어요'}
              </span>
              <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ wordBreak: 'keep-all' }}>
                {isConn
                  ? '잠시 뒤 바로 들을 수 있어요. 폰을 환자와 나 사이에 두세요.'
                  : isErr
                    ? micErr
                      ? '마이크 권한을 허용하면 바로 시작해요.'
                      : '다시 시도를 누르면 다시 연결해요.'
                    : '듣기를 켜고 말하면 여기에 원문과 번역이 쌓여요.'}
              </span>
            </div>
          )}
          {caps.map((c) => {
            const me = c.side === 'me';
            const partial = !c.final;
            return (
              <div key={c.key} style={{ display: 'flex', flexDirection: 'column', alignItems: me ? 'flex-end' : 'flex-start', gap: 3 }}>
                <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ padding: '0 4px' }}>
                  {me ? '나' : name + ' 님'}
                </span>
                <div
                  className={me ? 'bg-primary text-ms-white' : 'bg-ms-white text-ms-gray-800'}
                  style={{
                    maxWidth: '82%',
                    borderRadius: me ? '14px 4px 14px 14px' : '4px 14px 14px 14px',
                    padding: '10px 13px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 5,
                    boxSizing: 'border-box',
                    opacity: me && partial ? 0.75 : 1,
                  }}
                >
                  <span
                    className={(me ? 'text-ms-white' : partial ? 'text-ms-gray-600' : 'text-ms-gray-800') + ' text-typo-heading-md-500'}
                    style={{ wordBreak: 'keep-all', textWrap: 'pretty' }}
                  >
                    {partial ? c.original + ' …' : c.original}
                  </span>
                  <span
                    className={(me ? 'text-ms-white' : 'text-ms-gray-600') + ' text-typo-caption-md-400'}
                    style={{ wordBreak: 'keep-all', textWrap: 'pretty' }}
                  >
                    {c.translation || (partial ? '번역 중…' : '')}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        <div
          className="bg-ms-white border-ms-gray-200"
          style={{
            padding: '14px 16px 20px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 8,
            borderTopWidth: 1,
            borderTopStyle: 'solid',
          }}
        >
          <button
            type="button"
            aria-label={state === 'listening' ? (playing ? '재생 중 · 멈춤' : '멈춤') : state === 'paused' ? '다시 듣기' : st.text}
            data-playing={state === 'listening' && playing ? 'true' : 'false'}
            onClick={() => session.current?.toggle()}
            className={'cc-btn ' + st.mic}
            style={{
              width: 68,
              height: 68,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderWidth: 2,
              borderStyle: 'solid',
              boxSizing: 'border-box',
            }}
          >
            {state === 'listening' && !playing && (
              <svg width="26" height="26" viewBox="0 0 24 24" fill="#ffffff">
                <rect x="6" y="5" width="4" height="14" rx="1.2" />
                <rect x="14" y="5" width="4" height="14" rx="1.2" />
              </svg>
            )}
            {state === 'listening' && playing && (
              <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, color: '#ffffff' }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 5L6 9H3v6h3l5 4V5z" />
                  <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
                </svg>
                <span style={{ fontSize: 10, fontWeight: 600, lineHeight: 1 }}>재생 중</span>
              </span>
            )}
            {state === 'paused' && (
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#2498bd" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            )}
            {isConn && (
              <svg className="ip-spin" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#9f9f9f" strokeWidth="2.4" strokeLinecap="round">
                <path d="M12 3a9 9 0 1 0 9 9" />
              </svg>
            )}
            {isErr && (
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ff4e51" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="3" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3M3 3l18 18" />
              </svg>
            )}
          </button>
          <span className={st.cls} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className={st.dot} style={{ width: 8, height: 8, borderRadius: '50%' }} />
            {st.text}
          </span>
          <span className="text-typo-caption-md-400 text-ms-gray-600" style={{ textAlign: 'center', wordBreak: 'keep-all' }}>
            {isErr && !micErr ? '다시 시도를 눌러 주세요' : st.hint}
          </span>
        </div>
      </div>
    </div>
  );
}
