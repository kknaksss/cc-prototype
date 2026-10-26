'use client';

// 예약 등록 모달(SPEC-005 §5.5 · §6.5 · 시안 M:572-652) — 왼쪽 고객 검색 · 오른쪽 예약 초안(KOS 예약 칸 그대로 — D-16)
// 기존 고객 = 검색 결과 줄을 고름 · 신규 고객 = 이름 + 구분 정보 하나 이상(D-17). 이름 같은 고객 경고(D-18) · 등록 직전 KOS 중복 = 409 duplicated_visitor
import { useEffect, useRef, useState } from 'react';
import { Badge, Button } from '@medisolve-ai/medikit';
import * as api from '@/lib/api';
import { clearSession } from '@/lib/session';
import type { CreateReservation, CustomerHit, CustomerSearch, DuplicateCandidate, NewCustomer, ResvForm } from '@/lib/types';
import { NATION_OPTIONS, dateShort, minToHm, nationName } from './view';

export interface NewDraft {
  date: string;
  groupId: number;
  groupTitle: string;
  start: string; // ISO(+09:00)
  startMin: number;
  endMin: number; // 시작 + 그 칸 간격(§5.5)
  zoneIds: number[]; // 그 칸에서 켜진 구역(columns[].capacities) — 비면 form 의 구역 전부
}

const INPUT: React.CSSProperties = {
  height: 36,
  padding: '0 10px',
  borderWidth: 1,
  borderStyle: 'solid',
  borderRadius: 6,
  boxSizing: 'border-box',
  width: '100%',
  minWidth: 0,
  fontFamily: 'inherit',
};
const INPUT_CLS = 'bg-ms-white border-ms-gray-300 text-typo-heading-sm-400 text-ms-gray-800';
const HIRAGANA = /[ぁ-ゖ]/;
const BIRTH = /^\d{4}-\d{2}-\d{2}$/;

interface Who {
  name: string;
  phoneticName: string;
  gender: '' | 'MALE' | 'FEMALE';
  birth: string;
  nationality: string;
  phoneCc: string;
  phoneNo: string;
  email: string;
  snsType: string;
  snsId: string;
  passport: string;
}
const EMPTY_WHO: Who = { name: '', phoneticName: '', gender: '', birth: '', nationality: '', phoneCc: '', phoneNo: '', email: '', snsType: '', snsId: '', passport: '' };

// 신규 구분 규칙(D-17 · §5.5) — 이름 + (연락처(국가번호 + 번호) · SNS(종류 + ID) · 이메일 · 여권번호 · 생년월일 중 하나 이상)
function identifiable(w: Who): boolean {
  if (!w.name.trim()) return false;
  return (
    (!!w.phoneCc.trim() && !!w.phoneNo.trim()) ||
    (!!w.snsType.trim() && !!w.snsId.trim()) ||
    !!w.email.trim() ||
    !!w.passport.trim() ||
    BIRTH.test(w.birth.trim())
  );
}

function newCustomerOf(w: Who): NewCustomer {
  const c: NewCustomer = { name: w.name.trim() };
  if (w.phoneticName.trim()) c.phoneticName = w.phoneticName.trim();
  if (w.gender) c.gender = w.gender;
  if (BIRTH.test(w.birth.trim())) c.dateOfBirth = w.birth.trim();
  if (w.nationality) c.nationality = w.nationality;
  if (w.phoneCc.trim() && w.phoneNo.trim()) c.phone = { countryCode: w.phoneCc.trim(), number: w.phoneNo.trim() };
  if (w.email.trim()) c.email = w.email.trim();
  if (w.snsType.trim() && w.snsId.trim()) c.sns = { type: w.snsType.trim(), accountId: w.snsId.trim() };
  if (w.passport.trim()) c.passportNumber = w.passport.trim();
  return c;
}

const sameName = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

export function NewReservationModal({ draft, onClose, onDone }: { draft: NewDraft; onClose: () => void; onDone: (toast: string) => void }) {
  const [form, setForm] = useState<ResvForm | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // 고객 검색
  const [q, setQ] = useState({ name: '', phone: '', birth: '', chart: '' });
  const [result, setResult] = useState<CustomerSearch | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  // 고른 기존 고객 · 신규 고객 칸
  const [picked, setPicked] = useState<CustomerHit | null>(null);
  const [who, setWho] = useState<Who>(EMPTY_WHO);
  const [sameNames, setSameNames] = useState<CustomerHit[]>([]);

  // 예약 칸
  const [zoneId, setZoneId] = useState<number | null>(null);
  const [consult, setConsult] = useState(false);
  const [sedation, setSedation] = useState(false);
  const [assignee, setAssignee] = useState<number | null>(null);
  const [doctors, setDoctors] = useState<number[]>([]);
  const [counselor, setCounselor] = useState<number | null>(null);
  const [funnel, setFunnel] = useState<number | null>(null);
  const [funnelDetail, setFunnelDetail] = useState('');
  const [discharge, setDischarge] = useState('');
  const [memo, setMemo] = useState('');

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dup, setDup] = useState<DuplicateCandidate | null>(null);

  const authFail = (e: unknown) => {
    if (e instanceof api.ApiError && e.status === 401) {
      clearSession();
      return true;
    }
    return false;
  };

  // 칸 목록(직원 · 원장 · 상담사 · 유입 · 구역) — 열 때 1번
  useEffect(() => {
    let live = true;
    api
      .reservationForm({ date: draft.date, groupId: draft.groupId, start: draft.start })
      .then((f) => {
        if (!live) return;
        setForm(f);
        setAssignee(f.defaultAssigneeStaffId);
        const avail = f.zones.filter((z) => z.available && (!draft.zoneIds.length || draft.zoneIds.includes(z.zoneId)));
        setZoneId(avail.some((z) => z.zoneId === f.defaultZoneId) ? f.defaultZoneId : (avail[0]?.zoneId ?? f.defaultZoneId));
      })
      .catch((e: unknown) => {
        if (!live || authFail(e)) return;
        setFormError(e instanceof Error ? e.message : '등록 칸을 불러오지 못했어요');
      });
    return () => {
      live = false;
    };
  }, [draft]);

  // 이름 같은 고객 경고(D-18) — 신규 이름을 입력하면 내부 검색(0.4초 뒤)
  const nameSeq = useRef(0);
  useEffect(() => {
    const name = who.name.trim();
    const n = ++nameSeq.current;
    if (picked || !name) return;
    const t = setTimeout(() => {
      api
        .searchCustomers({ name })
        .then((r) => {
          if (n === nameSeq.current) setSameNames(r.items.filter((h) => sameName(h.name, name)));
        })
        .catch(() => undefined);
    }, 400);
    return () => clearTimeout(t);
  }, [who.name, picked]);
  const warnNames = picked || !who.name.trim() ? [] : sameNames;

  const search = async (page = 1) => {
    const has = Object.values(q).some((v) => v.trim());
    if (!has) {
      setSearchError('검색 조건을 하나 이상 넣어 주세요');
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      setResult(await api.searchCustomers({ name: q.name.trim(), phone: q.phone.trim(), birth: q.birth.trim(), chart: q.chart.trim(), page }));
    } catch (e) {
      if (!authFail(e)) setSearchError(e instanceof Error ? e.message : '검색하지 못했어요');
    } finally {
      setSearching(false);
    }
  };
  const reset = () => {
    setQ({ name: '', phone: '', birth: '', chart: '' });
    setResult(null);
    setSearchError(null);
    setPicked(null);
  };

  // 구역 칸 = 그 그룹에서 켜진 구역 · 하나뿐이면 숨기고 그 구역으로(§5.5 · D-44)
  const zones = (form?.zones ?? []).filter((z) => !draft.zoneIds.length || draft.zoneIds.includes(z.zoneId));
  const showZone = zones.length >= 2;
  const kataBad = !picked && HIRAGANA.test(who.phoneticName);
  const ready = !!form && (picked ? true : identifiable(who) && !kataBad);

  const submit = async (customer: CreateReservation['customer']) => {
    if (!form) return;
    const body: CreateReservation = {
      groupId: draft.groupId,
      start: draft.start,
      customer,
      consultationRequired: consult,
      sedationRequired: sedation,
      doctorStaffIds: doctors,
    };
    if (zoneId !== null) body.zoneId = zoneId;
    if (assignee !== null) body.assigneeStaffId = assignee;
    if (counselor !== null) body.counselorStaffId = counselor;
    if (funnel !== null) {
      body.funnelId = funnel;
      if (funnelDetail.trim()) body.funnelDetail = funnelDetail.trim();
    }
    if (memo.trim()) body.memo = memo;
    if (discharge) body.desiredDischargeTime = discharge;
    setSaving(true);
    setError(null);
    setDup(null);
    try {
      await api.createReservation(body);
      onDone(draft.groupTitle + ' ' + minToHm(draft.startMin) + ' 예약 등록');
    } catch (e) {
      if (authFail(e)) return;
      if (e instanceof api.ApiError && e.code === 'duplicated_visitor' && e.extra.candidate) setDup(e.extra.candidate);
      else setError(e instanceof Error ? e.message : '등록하지 못했어요');
    } finally {
      setSaving(false);
    }
  };
  const save = () => void submit(picked ? { customerId: picked.customerId } : { new: newCustomerOf(who) });
  // KOS 에 같은 고객 → 그 고객으로(기존 고객 길로 다시 보냄 — §5.5 · OQ-708)
  const useDup = () => {
    if (!dup) return;
    setPicked({ customerId: dup.customerId, chartNumber: dup.chartNumber, name: dup.name, phoneticName: null, dateOfBirth: dup.dateOfBirth, nationality: null, isNew: false });
    void submit({ customerId: dup.customerId });
  };

  const setW = (k: keyof Who) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setWho((w) => ({ ...w, [k]: e.target.value }));
  const kind = picked
    ? { text: picked.chartNumber ? '기존 고객 · No.' + picked.chartNumber : '기존 고객', variant: 'primary' as const }
    : { text: '신규 고객', variant: 'neutral' as const };
  const pages = result ? Math.max(1, Math.ceil(result.total / (result.pageSize || 20))) : 1;

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 60, background: 'rgba(0,0,0,0.32)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="예약 등록"
        className="bg-ms-white shadow-pop-over-more"
        style={{ width: 'min(1200px, 92vw)', height: '88vh', maxHeight: '100%', borderRadius: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
      >
        <div className="border-ms-gray-200" style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, borderBottomWidth: 1, borderBottomStyle: 'solid' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span className="text-typo-heading-md-600 text-ms-gray-800">예약 등록</span>
            <span className="text-typo-body-500 text-primary">
              {dateShort(draft.date)} {minToHm(draft.startMin)} ~ {minToHm(draft.endMin)} · {draft.groupTitle}
            </span>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="text-ms-gray-600" style={{ border: 'none', background: 'transparent', fontSize: 20, lineHeight: 1, cursor: 'pointer' }}>
            ×
          </button>
        </div>

        <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          {/* 왼쪽 — 고객 검색 */}
          <div className="bg-ms-gray-100" style={{ flex: '1 1 0', minWidth: 0, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span className="text-typo-heading-sm-600 text-ms-gray-800">고객 검색</span>
              <button type="button" onClick={reset} className="text-typo-body-500 text-primary" style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}>
                ↻ 초기화
              </button>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void search(1);
              }}
              style={{ flexShrink: 0, display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0,1fr)) auto', gap: 6, alignItems: 'center' }}
            >
              {(
                [
                  ['name', '이름'],
                  ['phone', '연락처'],
                  ['birth', '생년월일 (YYYY-MM-DD)'],
                  ['chart', '차트번호'],
                ] as const
              ).map(([k, label]) => (
                <input
                  key={k}
                  aria-label={label}
                  placeholder={label}
                  value={q[k]}
                  onChange={(e) => setQ((x) => ({ ...x, [k]: e.target.value }))}
                  className="bg-ms-white border-ms-gray-300 text-typo-body-400 text-ms-gray-800"
                  style={{ ...INPUT, height: 40 }}
                />
              ))}
              <Button type="submit" variant="solid" color="blue" isLoading={searching}>
                검색
              </Button>
            </form>
            {searchError && <span className="text-typo-body-500 text-red">{searchError}</span>}
            <div className="bg-ms-white border-ms-gray-200" style={{ flexShrink: 0, borderWidth: 1, borderStyle: 'solid', borderRadius: 10, overflow: 'hidden' }}>
              <div
                className="bg-ms-gray-100 border-ms-gray-200 text-typo-body-600 text-ms-gray-700"
                style={{ display: 'grid', gridTemplateColumns: '84px minmax(0,1.4fr) minmax(0,1fr) 72px 48px', gap: 8, padding: '10px 12px', borderBottomWidth: 1, borderBottomStyle: 'solid' }}
              >
                <span>차트번호</span>
                <span>이름 (발음)</span>
                <span>생년월일</span>
                <span>국적</span>
                <span />
              </div>
              {result?.items.map((h) => {
                const on = picked?.customerId === h.customerId;
                return (
                  <div
                    key={h.customerId}
                    role="button"
                    tabIndex={0}
                    onClick={() => setPicked(on ? null : h)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') setPicked(on ? null : h);
                    }}
                    className={(on ? 'bg-primary-100' : 'bg-ms-white') + ' border-ms-gray-200'}
                    style={{ cursor: 'pointer', display: 'grid', gridTemplateColumns: '84px minmax(0,1.4fr) minmax(0,1fr) 72px 48px', gap: 8, alignItems: 'center', padding: '8px 12px', borderBottomWidth: 1, borderBottomStyle: 'solid' }}
                  >
                    <span className="text-typo-body-400 text-ms-gray-600" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {h.chartNumber ? 'No.' + h.chartNumber : '-'}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
                      <span className="text-typo-body-600 text-ms-gray-800" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {h.name}
                      </span>
                      <span className="text-typo-caption-md-400 text-ms-gray-500" style={{ whiteSpace: 'nowrap' }}>
                        {h.phoneticName ?? ''}
                      </span>
                    </div>
                    <span className="text-typo-body-400 text-ms-gray-700" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {h.dateOfBirth ?? '-'}
                    </span>
                    <span className="text-typo-body-400 text-ms-gray-700" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {nationName(h.nationality) || '-'}
                    </span>
                    <span className="text-typo-body-600 text-primary" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                      {on ? '선택됨' : '선택'}
                    </span>
                  </div>
                );
              })}
              {!result?.items.length && (
                <div className="text-typo-body-400 text-ms-gray-500" style={{ padding: '28px 12px', textAlign: 'center' }}>
                  {result ? '일치하는 고객이 없어요 · 신규 고객으로 등록됩니다' : '고객을 검색하세요'}
                </div>
              )}
            </div>
            {result && pages > 1 && (
              <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                <PageBtn label="‹" aria="이전 페이지" disabled={result.page <= 1} onClick={() => void search(result.page - 1)} />
                {Array.from({ length: pages }, (_, i) => i + 1)
                  .filter((n) => Math.abs(n - result.page) <= 2 || n === 1 || n === pages)
                  .map((n) => (
                    <PageBtn key={n} label={String(n)} on={n === result.page} onClick={() => void search(n)} />
                  ))}
                <PageBtn label="›" aria="다음 페이지" disabled={result.page >= pages} onClick={() => void search(result.page + 1)} />
              </div>
            )}
          </div>

          {/* 오른쪽 — 예약 초안 */}
          <div className="border-ms-gray-200" style={{ flex: '1 1 0', minWidth: 0, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12, borderLeftWidth: 1, borderLeftStyle: 'solid' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span className="text-typo-heading-sm-600 text-ms-gray-800">예약 초안</span>
              <Badge variant={kind.variant} size="md">
                {kind.text}
              </Badge>
            </div>
            {formError && <span className="text-typo-body-500 text-red">{formError}</span>}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '8px 12px' }}>
              <Field k="예약일 · 시간">
                <input readOnly value={`${dateShort(draft.date)} ${minToHm(draft.startMin)} ~ ${minToHm(draft.endMin)}`} className={INPUT_CLS + ' bg-ms-gray-100'} style={INPUT} />
              </Field>
              <Field k="그룹">
                <input readOnly value={draft.groupTitle} className={INPUT_CLS + ' bg-ms-gray-100'} style={INPUT} />
              </Field>
              {showZone && (
                <Field k="구역" span>
                  <select value={zoneId ?? ''} onChange={(e) => setZoneId(Number(e.target.value))} className={INPUT_CLS} style={INPUT}>
                    {zones.map((z) => (
                      <option key={z.zoneId} value={z.zoneId} disabled={!z.available}>
                        {z.title}
                        {z.available ? '' : ' (정원 마감)'}
                      </option>
                    ))}
                  </select>
                </Field>
              )}

              {picked ? (
                <>
                  <Field k="이름">
                    <input readOnly value={picked.name} className={INPUT_CLS + ' bg-ms-gray-100'} style={INPUT} />
                  </Field>
                  <Field k="한글 발음 · 국적">
                    <input readOnly value={[picked.phoneticName, nationName(picked.nationality)].filter(Boolean).join(' · ')} className={INPUT_CLS + ' bg-ms-gray-100'} style={INPUT} />
                  </Field>
                  <div style={{ gridColumn: '1 / -1' }}>
                    <button type="button" onClick={() => setPicked(null)} className="text-typo-body-500 text-primary" style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}>
                      고른 고객 풀기 · 신규 고객으로
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <Field k="이름 *" span>
                    <input value={who.name} onChange={setW('name')} placeholder="여권과 같은 이름" className={INPUT_CLS} style={INPUT} />
                    {warnNames.length > 0 && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 4 }}>
                        <span className="text-typo-body-500 text-red">이름이 같은 기존 고객이 있어요 · 같은 사람이면 선택하세요</span>
                        {warnNames.slice(0, 5).map((h) => (
                          <button
                            key={h.customerId}
                            type="button"
                            onClick={() => setPicked(h)}
                            className="text-typo-body-400 text-red"
                            style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', padding: 0, textAlign: 'left', textDecoration: 'underline' }}
                          >
                            {h.name} · {h.chartNumber ? 'No.' + h.chartNumber : '차트 없음'} · {h.dateOfBirth ?? '생년월일 없음'}
                          </button>
                        ))}
                      </div>
                    )}
                  </Field>
                  <Field k="한글 발음">
                    <input value={who.phoneticName} onChange={setW('phoneticName')} className={INPUT_CLS} style={INPUT} />
                    {kataBad && <span className="text-typo-caption-md-500 text-red">가타카나로 입력해 주세요</span>}
                  </Field>
                  <Field k="성별">
                    <select value={who.gender} onChange={setW('gender')} className={INPUT_CLS} style={INPUT}>
                      <option value="">선택 안 함</option>
                      <option value="MALE">남</option>
                      <option value="FEMALE">여</option>
                    </select>
                  </Field>
                  <Field k="생년월일">
                    <input type="date" value={who.birth} onChange={setW('birth')} className={INPUT_CLS} style={INPUT} />
                  </Field>
                  <Field k="국적">
                    <select value={who.nationality} onChange={setW('nationality')} className={INPUT_CLS} style={INPUT}>
                      <option value="">선택 안 함</option>
                      {NATION_OPTIONS.map((n) => (
                        <option key={n.code} value={n.code}>
                          {n.name} ({n.code})
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field k="연락처(국가번호 · 번호)">
                    <div style={{ display: 'grid', gridTemplateColumns: '72px minmax(0,1fr)', gap: 6 }}>
                      <input value={who.phoneCc} onChange={setW('phoneCc')} placeholder="+82" className={INPUT_CLS} style={INPUT} />
                      <input value={who.phoneNo} onChange={setW('phoneNo')} className={INPUT_CLS} style={INPUT} />
                    </div>
                  </Field>
                  <Field k="이메일">
                    <input type="email" value={who.email} onChange={setW('email')} className={INPUT_CLS} style={INPUT} />
                  </Field>
                  <Field k="SNS(종류 · ID)">
                    <div style={{ display: 'grid', gridTemplateColumns: '96px minmax(0,1fr)', gap: 6 }}>
                      <input value={who.snsType} onChange={setW('snsType')} placeholder="종류" className={INPUT_CLS} style={INPUT} />
                      <input value={who.snsId} onChange={setW('snsId')} placeholder="ID" className={INPUT_CLS} style={INPUT} />
                    </div>
                  </Field>
                  <Field k="여권번호">
                    <input value={who.passport} onChange={setW('passport')} className={INPUT_CLS} style={INPUT} />
                  </Field>
                  {!identifiable(who) && (
                    <span className="text-typo-caption-md-500 text-ms-gray-500" style={{ gridColumn: '1 / -1' }}>
                      신규 고객은 이름과 함께 연락처 · SNS · 이메일 · 여권번호 · 생년월일 중 하나 이상이 필요해요
                    </span>
                  )}
                </>
              )}

              <Field k="진행">
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, height: 36 }}>
                  <Check on={consult} onChange={setConsult} label="상담 필요" />
                  <Check on={sedation} onChange={setSedation} label="수면마취" />
                </div>
              </Field>
              <Field k="귀가 희망 시각">
                <input type="time" value={discharge} onChange={(e) => setDischarge(e.target.value)} className={INPUT_CLS} style={INPUT} />
              </Field>
              <Field k="예약 담당자">
                <select value={assignee ?? ''} onChange={(e) => setAssignee(e.target.value ? Number(e.target.value) : null)} className={INPUT_CLS} style={INPUT}>
                  <option value="">선택 안 함</option>
                  {form?.staff.map((s) => (
                    <option key={s.staffId} value={s.staffId}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field k="희망 상담사">
                <select value={counselor ?? ''} onChange={(e) => setCounselor(e.target.value ? Number(e.target.value) : null)} className={INPUT_CLS} style={INPUT}>
                  <option value="">선택 안 함</option>
                  {form?.counselors.map((s) => (
                    <option key={s.staffId} value={s.staffId}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field k="당일 지정 의사" span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', minHeight: 36, alignItems: 'center' }}>
                  {form?.doctors.length ? (
                    form.doctors.map((d) => (
                      <Check
                        key={d.staffId}
                        on={doctors.includes(d.staffId)}
                        onChange={(on) => setDoctors((x) => (on ? [...x, d.staffId] : x.filter((id) => id !== d.staffId)))}
                        label={d.name}
                      />
                    ))
                  ) : (
                    <span className="text-typo-body-400 text-ms-gray-500">원장 목록 없음</span>
                  )}
                </div>
              </Field>
              <Field k="유입 채널">
                <select value={funnel ?? ''} onChange={(e) => setFunnel(e.target.value ? Number(e.target.value) : null)} className={INPUT_CLS} style={INPUT}>
                  <option value="">선택 안 함</option>
                  {form?.funnels.map((f) => (
                    <option key={f.funnelId} value={f.funnelId}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field k="유입 상세">
                <input value={funnelDetail} onChange={(e) => setFunnelDetail(e.target.value)} disabled={funnel === null} className={INPUT_CLS} style={INPUT} />
              </Field>
            </div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="text-typo-body-400 text-ms-gray-500">예약 메모</span>
              <textarea
                value={memo}
                onChange={(e) => setMemo(e.target.value)}
                placeholder="날짜/지점/희망 시술/통역/특이사항"
                className="bg-ms-white border-ms-gray-300 text-typo-heading-sm-400 text-ms-gray-800"
                style={{ height: 110, padding: '10px 12px', borderWidth: 1, borderStyle: 'solid', borderRadius: 6, resize: 'none', fontFamily: 'inherit', boxSizing: 'border-box', width: '100%' }}
              />
            </label>

            {/* 등록 직전 KOS 중복(§5.5 · OQ-708) */}
            {dup && (
              <div className="bg-yellow-100 border-yellow-500" style={{ borderWidth: 1, borderStyle: 'solid', borderRadius: 8, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span className="text-typo-body-600 text-ms-gray-800">KOS 에 같은 고객이 있어요 · 이 고객으로 예약할까요?</span>
                <span className="text-typo-body-400 text-ms-gray-700">
                  {dup.name} · {dup.chartNumber ? 'No.' + dup.chartNumber : '차트 없음'} · {dup.dateOfBirth ?? '생년월일 없음'}
                </span>
                <div>
                  <Button variant="solid" color="blue" size="sm" onClick={useDup} disabled={saving}>
                    이 고객으로
                  </Button>
                </div>
              </div>
            )}
            {error && <span className="text-typo-body-500 text-red">{error}</span>}
          </div>
        </div>

        <div className="border-ms-gray-200" style={{ padding: '12px 20px', display: 'flex', justifyContent: 'flex-end', gap: 8, borderTopWidth: 1, borderTopStyle: 'solid' }}>
          <Button variant="outlined" color="gray" onClick={onClose}>
            취소
          </Button>
          <Button variant="solid" color="blue" disabled={!ready || saving} onClick={save}>
            {saving ? '등록 중…' : '예약 등록'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Field({ k, span, children }: { k: string; span?: boolean; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, gridColumn: span ? '1 / -1' : undefined }}>
      <span className="text-typo-body-400 text-ms-gray-500">{k}</span>
      {children}
    </label>
  );
}

function Check({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', whiteSpace: 'nowrap' }} onClick={() => onChange(!on)}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} onClick={(e) => e.stopPropagation()} style={{ width: 16, height: 16, margin: 0 }} />
      <span className="text-typo-body-400 text-ms-gray-800">{label}</span>
    </span>
  );
}

function PageBtn({ label, aria, on, disabled, onClick }: { label: string; aria?: string; on?: boolean; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={aria}
      aria-current={on ? 'page' : undefined}
      disabled={disabled}
      onClick={onClick}
      className={on ? 'bg-primary border-primary text-ms-white' : 'bg-ms-white border-ms-gray-300 text-ms-gray-700'}
      style={{ minWidth: 32, height: 32, padding: '0 8px', borderWidth: 1, borderStyle: 'solid', borderRadius: 6, cursor: disabled ? 'default' : 'pointer', fontFamily: 'inherit' }}
    >
      {label}
    </button>
  );
}
