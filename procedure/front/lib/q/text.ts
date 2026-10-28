// 고객 문진 웹 화면 틀 글자 — 6개 언어(SPEC-006 §4 · 양식 번역 6개 = ko · ja · zh-Hans · zh-Hant · en · id).
// 앱 `lib/l10n/questionnaire_text.dart`(SPEC-004 §6.15)에서 옮김 + 고객 폰 끝 · 오류 화면(§5) 문구. KOS 양식 · 약관 글자는 응답 translsMap 을 쓴다
export const Q_LANGS = ['ko', 'ja', 'zh-Hans', 'zh-Hant', 'en', 'id'] as const;
export type QLang = (typeof Q_LANGS)[number];

export const Q_LANG_NAME: Record<QLang, string> = {
  ko: '한국어',
  ja: '日本語',
  'zh-Hans': '简体中文',
  'zh-Hant': '繁體中文',
  en: 'English',
  id: 'Bahasa Indonesia',
};

type Six = Record<QLang, string>;

const T = {
  hello: { ko: '{name} 님', ja: '{name} 様', 'zh-Hans': '{name} 您好', 'zh-Hant': '{name} 您好', en: 'Hello, {name}', id: 'Halo, {name}' },
  intro: {
    ko: '시술 전에 몇 가지를 여쭤볼게요',
    ja: '施術の前にいくつかお伺いします',
    'zh-Hans': '疗程前请回答几个问题',
    'zh-Hant': '療程前請回答幾個問題',
    en: 'A few questions before your treatment',
    id: 'Beberapa pertanyaan sebelum perawatan',
  },
  start: { ko: '시작', ja: '始める', 'zh-Hans': '开始', 'zh-Hant': '開始', en: 'Start', id: 'Mulai' },
  next: { ko: '다음', ja: '次へ', 'zh-Hans': '下一步', 'zh-Hant': '下一步', en: 'Next', id: 'Lanjut' },
  prev: { ko: '이전', ja: '戻る', 'zh-Hans': '上一步', 'zh-Hant': '上一步', en: 'Back', id: 'Kembali' },
  basic: { ko: '기본 정보', ja: '基本情報', 'zh-Hans': '基本信息', 'zh-Hant': '基本資訊', en: 'Basic information', id: 'Informasi dasar' },
  name: { ko: '이름', ja: '氏名', 'zh-Hans': '姓名', 'zh-Hant': '姓名', en: 'Name', id: 'Nama' },
  dob: { ko: '생년월일', ja: '生年月日', 'zh-Hans': '出生日期', 'zh-Hant': '出生日期', en: 'Date of birth', id: 'Tanggal lahir' },
  gender: { ko: '성별', ja: '性別', 'zh-Hans': '性别', 'zh-Hant': '性別', en: 'Gender', id: 'Jenis kelamin' },
  female: { ko: '여성', ja: '女性', 'zh-Hans': '女', 'zh-Hant': '女', en: 'Female', id: 'Perempuan' },
  male: { ko: '남성', ja: '男性', 'zh-Hans': '男', 'zh-Hant': '男', en: 'Male', id: 'Laki-laki' },
  phone: { ko: '휴대폰', ja: '携帯電話', 'zh-Hans': '手机', 'zh-Hant': '手機', en: 'Mobile', id: 'Ponsel' },
  countryCode: { ko: '국가 번호', ja: '国番号', 'zh-Hans': '国家代码', 'zh-Hant': '國碼', en: 'Country code', id: 'Kode negara' },
  address: { ko: '주소', ja: '住所', 'zh-Hans': '地址', 'zh-Hant': '地址', en: 'Address', id: 'Alamat' },
  addressDetail: { ko: '상세 주소', ja: '詳細住所', 'zh-Hans': '详细地址', 'zh-Hant': '詳細地址', en: 'Address line 2', id: 'Detail alamat' },
  required: { ko: '필수', ja: '必須', 'zh-Hans': '必填', 'zh-Hant': '必填', en: 'Required', id: 'Wajib' },
  other: { ko: '내용을 적어 주세요', ja: '内容をご記入ください', 'zh-Hans': '请填写内容', 'zh-Hant': '請填寫內容', en: 'Please describe', id: 'Silakan tulis' },
  agree: { ko: '동의', ja: '同意', 'zh-Hans': '同意', 'zh-Hant': '同意', en: 'Consent', id: 'Persetujuan' },
  agreeAll: { ko: '모두 동의', ja: 'すべて同意', 'zh-Hans': '全部同意', 'zh-Hant': '全部同意', en: 'Agree to all', id: 'Setuju semua' },
  submit: { ko: '제출', ja: '送信', 'zh-Hans': '提交', 'zh-Hant': '提交', en: 'Submit', id: 'Kirim' },
  sending: { ko: '보내는 중…', ja: '送信中…', 'zh-Hans': '提交中…', 'zh-Hant': '提交中…', en: 'Sending…', id: 'Mengirim…' },
  thanks: { ko: '감사합니다', ja: 'ありがとうございました', 'zh-Hans': '谢谢', 'zh-Hant': '謝謝', en: 'Thank you', id: 'Terima kasih' },
  // ⑦ 끝 — 고객 자기 폰이라 「기기를 돌려주세요」 대신(SPEC-006 §4 ⑦)
  thanksSub: {
    ko: '이 창을 닫으셔도 돼요',
    ja: 'この画面を閉じてもかまいません',
    'zh-Hans': '您可以关闭此页面了',
    'zh-Hant': '您可以關閉此頁面了',
    en: 'You can close this page now',
    id: 'Anda dapat menutup halaman ini',
  },
  failed: {
    ko: '제출하지 못했어요 · 직원에게 알려 주세요',
    ja: '送信できませんでした・スタッフにお知らせください',
    'zh-Hans': '提交失败・请告知工作人员',
    'zh-Hant': '提交失敗・請告知工作人員',
    en: "Couldn't submit · please tell a staff member",
    id: 'Gagal mengirim · mohon beri tahu staf',
  },
  retrySubmit: { ko: '다시 제출', ja: '再送信', 'zh-Hans': '重新提交', 'zh-Hant': '重新提交', en: 'Submit again', id: 'Kirim ulang' },
  retry: { ko: '다시 시도', ja: '再試行', 'zh-Hans': '重试', 'zh-Hant': '重試', en: 'Try again', id: 'Coba lagi' },
  reopen: { ko: '다시 열기', ja: '開き直す', 'zh-Hans': '重新打开', 'zh-Hant': '重新開啟', en: 'Open again', id: 'Buka lagi' },
  loadFailed: {
    ko: '불러오지 못했어요 · 직원에게 알려 주세요',
    ja: '読み込めませんでした・スタッフにお知らせください',
    'zh-Hans': '加载失败・请告知工作人员',
    'zh-Hant': '載入失敗・請告知工作人員',
    en: "Couldn't load · please tell a staff member",
    id: 'Gagal memuat · mohon beri tahu staf',
  },
  // §5 오류 화면
  invalid: {
    ko: '링크가 올바르지 않아요 · 직원에게 새 QR 을 요청해 주세요',
    ja: 'リンクが正しくありません・スタッフに新しいQRコードをお求めください',
    'zh-Hans': '链接无效・请向工作人员索取新的二维码',
    'zh-Hant': '連結無效・請向工作人員索取新的 QR 碼',
    en: 'This link is not valid · please ask a staff member for a new QR code',
    id: 'Tautan tidak valid · mohon minta kode QR baru kepada staf',
  },
  expired: {
    ko: 'QR 유효 시간이 지났어요 · 직원에게 새 QR 을 요청해 주세요',
    ja: 'QRコードの有効期限が切れました・スタッフに新しいQRコードをお求めください',
    'zh-Hans': '二维码已过期・请向工作人员索取新的二维码',
    'zh-Hant': 'QR 碼已過期・請向工作人員索取新的 QR 碼',
    en: 'This QR code has expired · please ask a staff member for a new one',
    id: 'Kode QR sudah kedaluwarsa · mohon minta kode QR baru kepada staf',
  },
  canceled: {
    ko: '새 QR 이 만들어졌어요 · 직원에게 새 QR 을 받아 주세요',
    ja: '新しいQRコードが発行されました・スタッフから新しいQRコードをお受け取りください',
    'zh-Hans': '已生成新的二维码・请向工作人员领取新的二维码',
    'zh-Hant': '已產生新的 QR 碼・請向工作人員領取新的 QR 碼',
    en: 'A new QR code has been issued · please get the new one from a staff member',
    id: 'Kode QR baru telah dibuat · mohon ambil kode QR baru dari staf',
  },
  submitted: {
    ko: '이미 제출했어요 · 감사합니다',
    ja: 'すでに送信済みです・ありがとうございました',
    'zh-Hans': '已提交・谢谢',
    'zh-Hant': '已提交・謝謝',
    en: 'Already submitted · thank you',
    id: 'Sudah dikirim · terima kasih',
  },
  submitting: {
    ko: '제출 중이에요 · 잠시 뒤 다시 열어 주세요',
    ja: '送信中です・しばらくしてから開き直してください',
    'zh-Hans': '正在提交・请稍后重新打开',
    'zh-Hant': '正在提交・請稍後重新開啟',
    en: 'Submitting · please open this page again in a moment',
    id: 'Sedang mengirim · mohon buka lagi sebentar lagi',
  },
  rate: {
    ko: '잠시 뒤 다시 시도해 주세요',
    ja: 'しばらくしてから再度お試しください',
    'zh-Hans': '请稍后再试',
    'zh-Hant': '請稍後再試',
    en: 'Please try again in a moment',
    id: 'Mohon coba lagi sebentar lagi',
  },
  fake: {
    ko: '지금은 제출할 수 없어요 · 직원에게 알려 주세요',
    ja: '現在は送信できません・スタッフにお知らせください',
    'zh-Hans': '目前无法提交・请告知工作人员',
    'zh-Hant': '目前無法提交・請告知工作人員',
    en: "Submitting isn't available right now · please tell a staff member",
    id: 'Saat ini tidak dapat mengirim · mohon beri tahu staf',
  },
} satisfies Record<string, Six>;

export type QKey = keyof typeof T;

// 고정 문구 — {name} 바꿈
export const qt = (key: QKey, lang: QLang, name = '') => T[key][lang].replace('{name}', name);

export const isQLang = (v: unknown): v is QLang => typeof v === 'string' && (Q_LANGS as readonly string[]).includes(v);

// 약관 번역 키 = ja · en · zh(간체 · 번체 둘 다 zh) · 그 밖 원문(SPEC-006 §4 ⑤ · back languages.AGREEMENT_KEY 와 같은 표)
export const AGREEMENT_KEY: Partial<Record<QLang, string>> = { ja: 'ja', en: 'en', 'zh-Hans': 'zh', 'zh-Hant': 'zh' };

// 응답 전 오류 화면 언어 = 브라우저 언어(SPEC-006 §4.1 — 이 경우만)
export function browserLang(langs: readonly string[]): QLang {
  for (const raw of langs) {
    const l = raw.toLowerCase();
    if (l.startsWith('ko')) return 'ko';
    if (l.startsWith('ja')) return 'ja';
    if (l === 'zh-tw' || l === 'zh-hk' || l === 'zh-mo' || l.startsWith('zh-hant')) return 'zh-Hant';
    if (l.startsWith('zh')) return 'zh-Hans';
    if (l.startsWith('id') || l.startsWith('in')) return 'id';
    if (l.startsWith('en')) return 'en';
  }
  return 'en';
}
