// 고객 문진 — KOS 양식(pages[] · translsMap) 그대로 읽기 · 답 모으기(SPEC-006 §4 ④ · 앱 model/questionnaire.dart 에서 옮김)
// 질문 = questionId(또는 id) · title · answers[] / 답 = answerId(또는 id) · title · inputType(CHECK_BOX · SELECT_BOX · INPUT_BOX) · isSubText · translsMap
// (데모 KOS 실제 응답 = questionId · answerId — id 키 없음 · 필수 표시 없음 · 2026-10-28 실제 back 로 확인)
// 보여 주는 글자만 번역 · 제출 title · parentQuestionTitle 은 원문(한국어 — KOS 와 같게 · app-kos-report §4)
import type { QJson } from '../publicApi';
import { AGREEMENT_KEY, type QLang } from './text';

const obj = (v: unknown): QJson => (v && typeof v === 'object' && !Array.isArray(v) ? (v as QJson) : {});
const list = (v: unknown): QJson[] => (Array.isArray(v) ? v.filter((x): x is QJson => !!x && typeof x === 'object' && !Array.isArray(x)) : []);
const str = (v: unknown) => (v === null || v === undefined ? '' : String(v));

// translsMap.<field>.translation[lang] — 없으면 원문
export function trOf(item: QJson, field: string, lang: string, fallback: string): string {
  const t = obj(obj(obj(item.translsMap)[field]).translation)[lang];
  return typeof t === 'string' && t.trim() ? t : fallback;
}

export interface QAnswer {
  raw: QJson;
  id: string;
  title: string;
  inputType: string;
  isSubText: boolean;
  isInput: boolean;
}

export interface QQuestion {
  raw: QJson;
  id: string;
  title: string;
  answers: QAnswer[];
  single: boolean; // 하나만 고르기 = 답이 모두 SELECT_BOX
  input: boolean; // 글 입력 = INPUT_BOX 하나
  required: boolean; // 필수 표시 = KOS 값(있으면)
}

export interface QPage {
  raw: QJson;
  questions: QQuestion[];
}

const answerOf = (raw: QJson): QAnswer => {
  const inputType = str(raw.inputType) || 'CHECK_BOX';
  return { raw, id: str(raw.answerId ?? raw.id), title: str(raw.title), inputType, isSubText: raw.isSubText === true, isInput: inputType === 'INPUT_BOX' };
};

const questionOf = (raw: QJson): QQuestion => {
  const answers = list(raw.answers).map(answerOf);
  return {
    raw,
    id: str(raw.questionId ?? raw.id),
    title: str(raw.title),
    answers,
    single: answers.length > 0 && answers.every((a) => a.inputType.endsWith('SELECT_BOX')),
    input: answers.length === 1 && answers[0].isInput,
    required: raw.required === true || raw.isRequired === true || raw.essential === true,
  };
};

// 질문 없는 쪽은 뺀다(앱과 같음)
export const pagesOf = (form: unknown): QPage[] =>
  list(obj(form).pages)
    .map((raw) => ({ raw, questions: list(raw.questions).map(questionOf) }))
    .filter((p) => p.questions.length > 0);

export const label = (item: { raw: QJson; title?: string }, lang: QLang) => trOf(item.raw, 'title', lang, item.title ?? str(item.raw.title));
export const subLabel = (a: QAnswer, lang: QLang) => trOf(a.raw, 'subText', lang, str(a.raw.subText));

// 약관 글자 — 번역 키 ja · en · zh · 그 밖 원문(§4 ⑤)
export const agreementLabel = (a: QJson, lang: QLang) => {
  const key = AGREEMENT_KEY[lang];
  return key ? trOf(a, 'title', key, str(a.title)) : str(a.title);
};
export const agreementId = (a: QJson) => str(a.id);

// 고객 입력 — 질문 id → 고른 답 id 들 · 답 id → 자유 글(subText · inputText)
export type Picked = Record<string, string[]>;
export type Texts = Record<string, string>;

export function toggle(picked: Picked, q: QQuestion, a: QAnswer): Picked {
  const cur = picked[q.id] ?? [];
  const had = cur.includes(a.id);
  const next = q.single ? (had ? [] : [a.id]) : had ? cur.filter((x) => x !== a.id) : [...cur, a.id];
  return { ...picked, [q.id]: next };
}

export const isPicked = (picked: Picked, q: QQuestion, a: QAnswer) => (picked[q.id] ?? []).includes(a.id);

// 그 쪽 필수 질문이 다 답했나
export const pageDone = (p: QPage, picked: Picked, texts: Texts) =>
  p.questions.filter((q) => q.required).every((q) => (q.input ? (texts[q.answers[0].id] ?? '').trim() !== '' : (picked[q.id] ?? []).length > 0));

// 제출 answers[] — 고른 선택지 한 줄씩(+ INPUT_BOX 글) · title 은 원문(키 = 앱 · AK§5.1 과 같음)
export function answersBody(pages: QPage[], picked: Picked, texts: Texts): QJson[] {
  const out: QJson[] = [];
  for (const p of pages)
    for (const q of p.questions)
      for (const a of q.answers) {
        const text = (texts[a.id] ?? '').trim();
        if (a.isInput ? text === '' : !isPicked(picked, q, a)) continue;
        out.push({
          parentQuestionId: q.raw.questionId ?? q.raw.id,
          parentQuestionTitle: q.title,
          id: a.raw.answerId ?? a.raw.id, // 제출 키 = id(KOS 제출본 answerId 로 돌아옴 — AK§5.2)
          title: a.title,
          inputType: a.inputType,
          inputText: a.isInput ? text : '',
          subText: !a.isInput && a.isSubText ? text : '',
        });
      }
  return out;
}

// 생년월일 — 받는 · 보내는 꼴 yyyyMMdd(F#2) ↔ 날짜 칸 yyyy-MM-dd
export const ymdToInput = (v: string) => (/^\d{8}$/.test(v) ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}` : '');
export const inputToYmd = (v: string) => v.replace(/-/g, '');
