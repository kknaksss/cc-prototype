'use client';

// 고객 문진 웹(SPEC-006 §2 · §4 · §5) — 고객 자기 폰 · 로그인 없음 · 토큰 = 주소 # 뒤(서버로 안 감).
// 차례: ① 불러오기 → ② 언어 칩 6 · 「{이름} 님」 · [시작] → ③ 기본 정보(미리 채움 · 고칠 수 있음) → ④ KOS 양식 쪽마다 → ⑤ 동의 → ⑥ 제출 → ⑦ 끝.
// 쓰던 답은 브라우저에 저장하지 않는다(OQ-806 — 고객 폰에 개인정보를 두지 않음). 시안 없음 → DS 기본값(모바일)
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { Button, Checkbox, Input, Loading, Progress, RadioGroup, RadioGroupItem } from '@medisolve-ai/medikit';
import { isQToken, loadQuestionnaire, PublicError, submitQuestionnaire, type PublicQuestionnaire } from '@/lib/publicApi';
import {
  agreementId,
  agreementLabel,
  answersBody,
  inputToYmd,
  isPicked,
  label,
  pageDone,
  pagesOf,
  subLabel,
  toggle,
  ymdToInput,
  type Picked,
  type QQuestion,
  type Texts,
} from '@/lib/q/form';
import { browserLang, isQLang, Q_LANG_NAME, Q_LANGS, qt, type QKey, type QLang } from '@/lib/q/text';

type Step = 'start' | 'basic' | 'page' | 'agree' | 'thanks';

// 오류 화면(§5) — 문구 키 · 버튼
interface Fail {
  code: string; // data-code(E2E 확인용 — 화면에는 안 보임)
  text: QKey;
  action?: 'retry' | 'reopen';
}

function failOf(e: unknown): Fail {
  const code = e instanceof PublicError ? e.code : 'error';
  const status = e instanceof PublicError ? e.status : 0;
  if (status === 404 || code === 'q_token_missing' || code === 'q_not_found' || code === 'q_token_format') return { code, text: 'invalid' };
  if (code === 'q_expired') return { code, text: 'expired' };
  if (code === 'q_canceled') return { code, text: 'canceled' };
  if (code === 'q_submitted') return { code, text: 'submitted' };
  if (code === 'q_submitting') return { code, text: 'submitting', action: 'reopen' };
  if (status === 429) return { code, text: 'rate', action: 'retry' };
  if (code === 'fake_board') return { code, text: 'fake' };
  return { code, text: 'loadFailed', action: 'retry' };
}

// 제출 실패 중 화면을 바꾸는 것(그 밖 = 입력 유지 + 「제출하지 못했어요」 · [다시 제출])
const SUBMIT_SCREEN = new Set(['q_expired', 'q_canceled', 'q_submitted', 'q_submitting', 'q_not_found', 'fake_board']);

// 토큰 = location.hash(# 뒤) — 서버 렌더 때는 null(불러오는 중으로 그림)
const subscribeHash = (on: () => void) => {
  window.addEventListener('hashchange', on);
  return () => window.removeEventListener('hashchange', on);
};
const readHash = () => window.location.hash.replace(/^#/, '');

export function QuestionnairePage() {
  const token = useSyncExternalStore(subscribeHash, readHash, () => null);
  const [data, setData] = useState<PublicQuestionnaire | null>(null);
  const [fail, setFail] = useState<Fail | null>(null);
  const [tries, setTries] = useState(0);

  useEffect(() => {
    if (token === null || !isQToken(token)) return;
    let live = true;
    loadQuestionnaire(token)
      .then((x) => live && setData(x))
      .catch((e: unknown) => live && setFail(failOf(e)));
    return () => {
      live = false;
    };
  }, [token, tries]);

  const again = useCallback(() => {
    setFail(null);
    setData(null);
    setTries((n) => n + 1);
  }, []);

  if (token === null) return <Shell><Spinner /></Shell>;
  // 토큰 꼴이 틀리면 back 을 부르지 않는다(§2)
  const badToken = !isQToken(token);
  if (badToken || fail) {
    const f = badToken ? { code: 'q_token_format', text: 'invalid' as const } : fail!;
    return <FailScreen fail={f} lang={browserLang(typeof navigator === 'undefined' ? [] : navigator.languages)} onAction={again} />;
  }
  if (!data) return <Shell><Spinner /></Shell>;
  // 토큰이 바뀌면(다른 링크로 hashchange) 화면 상태를 처음부터
  return <Form key={token + '/' + tries} token={token} data={data} onReload={again} />;
}

function Form({ token, data, onReload }: { token: string; data: PublicQuestionnaire; onReload: () => void }) {
  const options = useMemo(() => {
    const xs = data.language.options.filter(isQLang);
    return xs.length ? xs : [...Q_LANGS];
  }, [data.language.options]);
  const [lang, setLang] = useState<QLang>(isQLang(data.language.code) && options.includes(data.language.code) ? data.language.code : 'en');
  const pages = useMemo(() => pagesOf(data.form), [data.form]);
  const agreements = data.agreements;

  const [step, setStep] = useState<Step>('start');
  const [page, setPage] = useState(0);
  const p = data.prefill;
  const [name, setName] = useState(p.name ?? '');
  const [dob, setDob] = useState(ymdToInput(p.dateOfBirth ?? ''));
  const [gender, setGender] = useState<string | null>(p.gender === 'FEMALE' || p.gender === 'MALE' ? p.gender : null);
  const [cc, setCc] = useState(p.phone?.countryCode ?? '');
  const [phone, setPhone] = useState(p.phone?.phoneNumber ?? ''); // KOS 값 그대로(앞 0 빠질 수 있음 · §6.3)
  const [addr, setAddr] = useState(p.address ?? '');
  const [addr2, setAddr2] = useState(p.addressDetail ?? '');
  const [picked, setPicked] = useState<Picked>({});
  const [texts, setTexts] = useState<Texts>({});
  const [agreed, setAgreed] = useState<Record<string, boolean>>({});
  const [sending, setSending] = useState(false);
  const [submitErr, setSubmitErr] = useState<QKey | null>(null);
  const [screen, setScreen] = useState<Fail | null>(null);

  const basicOk = name.trim() !== '' && /^\d{4}-\d{2}-\d{2}$/.test(dob) && gender !== null;
  const agreeOk = agreements.filter((a) => a.required === true).every((a) => agreed[agreementId(a)]);
  const total = pages.length + 2; // 기본 정보 + 양식 쪽 + 동의
  const t = (k: QKey) => qt(k, lang);

  // 단계가 바뀌면 맨 위로
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [step, page]);

  const submit = async () => {
    setSending(true);
    setSubmitErr(null);
    try {
      await submitQuestionnaire(token, {
        language: lang,
        name: name.trim(),
        dateOfBirth: inputToYmd(dob),
        gender,
        phone: { countryCode: cc.trim(), phoneNumber: phone.trim() },
        address: addr.trim(),
        addressDetail: addr2.trim(),
        agreements: agreements.map((a) => ({ ...a, agreed: !!agreed[agreementId(a)] })),
        answers: answersBody(pages, picked, texts),
      });
      setStep('thanks');
    } catch (e) {
      const f = failOf(e);
      if (SUBMIT_SCREEN.has(f.code)) setScreen(f);
      else setSubmitErr(f.text === 'rate' ? 'rate' : 'failed'); // 입력값 유지 + [다시 제출]
    } finally {
      setSending(false);
    }
  };

  if (screen) return <FailScreen fail={screen} lang={lang} onAction={onReload} />;

  if (step === 'thanks')
    return (
      <Shell>
        <Center>
          <span className="bg-primary text-ms-white" style={{ width: 72, height: 72, borderRadius: 36, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 36 }} aria-hidden>
            ✓
          </span>
          <h1 className="text-typo-title-md-600 text-ms-gray-800" style={{ fontSize: 26, margin: '16px 0 8px' }}>
            {t('thanks')}
          </h1>
          <p className="text-typo-heading-md-400 text-ms-gray-600">{t('thanksSub')}</p>
        </Center>
      </Shell>
    );

  const chips = (
    <div style={{ display: 'flex', gap: 6, overflowX: 'auto', padding: '10px 16px', WebkitOverflowScrolling: 'touch' }}>
      {options.map((l) => (
        <Button key={l} variant={l === lang ? 'solid' : 'outlined'} color={l === lang ? 'blue' : 'gray'} size="sm" onClick={() => setLang(l)} style={{ flexShrink: 0, whiteSpace: 'nowrap' }} aria-pressed={l === lang}>
          {Q_LANG_NAME[l]}
        </Button>
      ))}
    </div>
  );

  if (step === 'start')
    return (
      <Shell top={chips}>
        <Center>
          <p className="text-typo-heading-md-500 text-primary" style={{ marginBottom: 12, letterSpacing: 1 }}>
            Céramique
          </p>
          <h1 className="text-typo-title-md-600 text-ms-gray-800" style={{ fontSize: 26, margin: '0 0 10px' }}>
            {qt('hello', lang, data.customerName)}
          </h1>
          <p className="text-typo-heading-md-400 text-ms-gray-600" style={{ marginBottom: 32 }}>
            {t('intro')}
          </p>
          <Button variant="solid" color="blue" onClick={() => setStep('basic')} style={{ width: '100%', maxWidth: 320 }}>
            {t('start')}
          </Button>
        </Center>
      </Shell>
    );

  if (step === 'basic')
    return (
      <Frame
        top={chips}
        title={t('basic')}
        n={1}
        total={total}
        lang={lang}
        canNext={basicOk}
        onPrev={() => setStep('start')}
        onNext={() => {
          setPage(0);
          setStep(pages.length ? 'page' : 'agree');
        }}
      >
        <Field label={t('name')} req>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" style={INPUT} />
        </Field>
        <Field label={t('dob')} req>
          <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} autoComplete="bday" style={INPUT} />
        </Field>
        <Field label={t('gender')} req group>
          <RadioGroup value={gender ?? ''} onValueChange={(v) => setGender(v)} style={{ display: 'flex', gap: 8 }}>
            {(['FEMALE', 'MALE'] as const).map((g) => (
              <Choice key={g} on={gender === g} grow>
                <RadioGroupItem value={g} />
                {t(g === 'FEMALE' ? 'female' : 'male')}
              </Choice>
            ))}
          </RadioGroup>
        </Field>
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ width: 104, flexShrink: 0 }}>
            <Field label={t('countryCode')}>
              <Input value={cc} onChange={(e) => setCc(e.target.value)} inputMode="numeric" placeholder="+" style={INPUT} />
            </Field>
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Field label={t('phone')}>
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" autoComplete="tel-national" style={INPUT} />
            </Field>
          </div>
        </div>
        <Field label={t('address')}>
          <Input value={addr} onChange={(e) => setAddr(e.target.value)} autoComplete="address-line1" style={INPUT} />
        </Field>
        <Field label={t('addressDetail')}>
          <Input value={addr2} onChange={(e) => setAddr2(e.target.value)} autoComplete="address-line2" style={INPUT} />
        </Field>
      </Frame>
    );

  if (step === 'page') {
    const pg = pages[page];
    return (
      <Frame
        top={chips}
        title={label(pg, lang)}
        n={page + 2}
        total={total}
        lang={lang}
        canNext={pageDone(pg, picked, texts)}
        onPrev={() => (page === 0 ? setStep('basic') : setPage(page - 1))}
        onNext={() => (page + 1 < pages.length ? setPage(page + 1) : setStep('agree'))}
      >
        {pg.questions.map((q) => (
          <Question key={q.id} q={q} lang={lang} picked={picked} texts={texts} onPick={(a) => setPicked(toggle(picked, q, a))} onText={(id, v) => setTexts({ ...texts, [id]: v })} />
        ))}
      </Frame>
    );
  }

  // ⑤ 동의 · ⑥ 제출
  const all = agreements.length > 0 && agreements.every((a) => agreed[agreementId(a)]);
  return (
    <Frame
      top={chips}
      title={t('agree')}
      n={total}
      total={total}
      lang={lang}
      canNext={agreeOk && !sending}
      nextLabel={sending ? t('sending') : submitErr ? t('retrySubmit') : t('submit')}
      onPrev={() => {
        if (pages.length) {
          setPage(pages.length - 1);
          setStep('page');
        } else setStep('basic');
      }}
      onNext={() => void submit()}
    >
      {agreements.length > 1 && (
        <Choice on={all}>
          <Checkbox checked={all} onCheckedChange={() => setAgreed(Object.fromEntries(agreements.map((a) => [agreementId(a), !all])))} />
          <span className="text-typo-heading-md-600">{t('agreeAll')}</span>
        </Choice>
      )}
      {agreements.map((a) => {
        const id = agreementId(a);
        return (
          <Choice key={id} on={!!agreed[id]}>
            <Checkbox checked={!!agreed[id]} onCheckedChange={(v) => setAgreed({ ...agreed, [id]: v === true })} />
            <span>
              {agreementLabel(a, lang)}
              {a.required === true && <span className="text-red"> ({t('required')})</span>}
            </span>
          </Choice>
        );
      })}
      {submitErr && (
        <p className="text-typo-heading-md-600 text-red" role="alert" style={{ marginTop: 12 }}>
          {t(submitErr)}
        </p>
      )}
    </Frame>
  );
}

// ── KOS 질문 — CHECK_BOX 여럿 · SELECT_BOX 하나 · INPUT_BOX 글 · isSubText 고르면 아래 글칸
function Question({
  q,
  lang,
  picked,
  texts,
  onPick,
  onText,
}: {
  q: QQuestion;
  lang: QLang;
  picked: Picked;
  texts: Texts;
  onPick: (a: QQuestion['answers'][number]) => void;
  onText: (id: string, v: string) => void;
}) {
  const head = (
    <p className="text-typo-heading-md-600 text-ms-gray-800" style={{ margin: '0 0 8px' }}>
      {label(q, lang)}
      {q.required && <span className="text-red"> *</span>}
    </p>
  );
  if (q.input) {
    const a = q.answers[0];
    return (
      <section style={{ marginBottom: 24 }}>
        {head}
        <Input value={texts[a.id] ?? ''} onChange={(e) => onText(a.id, e.target.value)} style={INPUT} />
      </section>
    );
  }
  const boxes = q.answers.map((a) => {
    const on = isPicked(picked, q, a);
    return (
      <div key={a.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Choice on={on}>
          {q.single ? <RadioGroupItem value={a.id} /> : <Checkbox checked={on} onCheckedChange={() => onPick(a)} />}
          <span>{label(a, lang)}</span>
        </Choice>
        {a.isSubText && on && (
          <Input value={texts[a.id] ?? ''} onChange={(e) => onText(a.id, e.target.value)} placeholder={subLabel(a, lang) || qt('other', lang)} style={INPUT} />
        )}
      </div>
    );
  });
  return (
    <section style={{ marginBottom: 24 }}>
      {head}
      {q.single ? (
        <RadioGroup
          value={(picked[q.id] ?? [])[0] ?? ''}
          onValueChange={(v) => {
            const a = q.answers.find((x) => x.id === v);
            if (a) onPick(a);
          }}
          style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
        >
          {boxes}
        </RadioGroup>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{boxes}</div>
      )}
    </section>
  );
}

// ── 틀
const INPUT: React.CSSProperties = { fontSize: 16 }; // iOS 확대 막기(16px 이상)

function Shell({ top, children }: { top?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-ms-white" style={{ minHeight: '100dvh', display: 'flex', flexDirection: 'column', fontSize: 16 }}>
      <div style={{ width: '100%', maxWidth: 560, margin: '0 auto', flex: 1, display: 'flex', flexDirection: 'column' }}>
        {top}
        {children}
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: 24 }}>{children}</div>;
}

function Spinner() {
  return (
    <Center>
      <Loading />
    </Center>
  );
}

function Frame({
  top,
  title,
  n,
  total,
  lang,
  canNext,
  nextLabel,
  onPrev,
  onNext,
  children,
}: {
  top: React.ReactNode;
  title: string;
  n: number;
  total: number;
  lang: QLang;
  canNext: boolean;
  nextLabel?: string;
  onPrev: () => void;
  onNext: () => void;
  children: React.ReactNode;
}) {
  return (
    <Shell top={top}>
      <div style={{ padding: '4px 16px 0' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
          <h1 className="text-typo-title-sm-600 text-ms-gray-800" style={{ fontSize: 22, margin: 0 }}>
            {title}
          </h1>
          <span className="text-typo-body-500 text-ms-gray-500" style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
            {n} / {total}
          </span>
        </div>
        <Progress value={n} max={total} size="sm" tone="primary" />
      </div>
      <div style={{ flex: 1, padding: '20px 16px' }}>{children}</div>
      <div className="bg-ms-white border-ms-gray-200" style={{ position: 'sticky', bottom: 0, display: 'flex', gap: 8, padding: '12px 16px calc(12px + env(safe-area-inset-bottom))', borderTopWidth: 1, borderTopStyle: 'solid' }}>
        <Button variant="outlined" color="gray" onClick={onPrev} style={{ flex: 1 }}>
          {qt('prev', lang)}
        </Button>
        <Button variant="solid" color="blue" disabled={!canNext} onClick={onNext} style={{ flex: 2 }}>
          {nextLabel ?? qt('next', lang)}
        </Button>
      </div>
    </Shell>
  );
}

// group = 안에 고르는 줄(label)이 여럿 — label 을 겹치지 않게 div 로
function Field({ label: text, req, group, children }: { label: string; req?: boolean; group?: boolean; children: React.ReactNode }) {
  const Tag = group ? 'div' : 'label';
  return (
    <Tag role={group ? 'group' : undefined} aria-label={group ? text : undefined} style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
      <span className="text-typo-body-500 text-ms-gray-600">
        {text}
        {req && <span className="text-red"> *</span>}
      </span>
      {children}
    </Tag>
  );
}

// 고르는 줄 — 줄 전체를 눌러도 된다(손가락 크기 48px)
function Choice({ on, grow, children }: { on: boolean; grow?: boolean; children: React.ReactNode }) {
  return (
    <label
      className={(on ? 'bg-primary-100 border-primary text-primary' : 'bg-ms-white border-ms-gray-300 text-ms-gray-800') + ' text-typo-heading-md-500'}
      style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 48, padding: '10px 14px', borderWidth: on ? 2 : 1, borderStyle: 'solid', borderRadius: 10, cursor: 'pointer', flex: grow ? 1 : undefined, boxSizing: 'border-box' }}
    >
      {children}
    </label>
  );
}

// §5 오류 · 끝 화면 — 고객 이름 · 예약 · 오류 코드 · 영어 원문 0(코드는 data-code 로만)
function FailScreen({ fail, lang, onAction }: { fail: Fail; lang: QLang; onAction: () => void }) {
  return (
    <Shell>
      <Center>
        <div data-code={fail.code} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
          <p className="text-typo-heading-md-500 text-primary" style={{ letterSpacing: 1 }}>
            Céramique
          </p>
          <p className="text-typo-title-sm-600 text-ms-gray-800" style={{ fontSize: 20, lineHeight: 1.5, whiteSpace: 'pre-line' }}>
            {qt(fail.text, lang).replace(/ · |・/, '\n')}
          </p>
          {fail.action && (
            <Button variant="solid" color="blue" onClick={onAction} style={{ minWidth: 200 }}>
              {qt(fail.action === 'reopen' ? 'reopen' : 'retry', lang)}
            </Button>
          )}
        </div>
      </Center>
    </Shell>
  );
}

