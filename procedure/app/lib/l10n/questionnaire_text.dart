// 문진 화면 고정 문구 6개 언어(SPEC-004 §6.15 · 양식 번역 6개 = ko · ja · zh-Hans · zh-Hant · en · id).
// KOS 양식 · 약관 글자는 응답 translsMap 을 쓰고, 여기는 화면 틀 글자만. 직원용 [직원] · 비밀번호 창은 한국어
const qLangName = {
  'ko': '한국어',
  'ja': '日本語',
  'zh-Hans': '简体中文',
  'zh-Hant': '繁體中文',
  'en': 'English',
  'id': 'Bahasa Indonesia',
};

const _t = <String, Map<String, String>>{
  'hello': {'ko': '{name} 님', 'ja': '{name} 様', 'zh-Hans': '{name} 您好', 'zh-Hant': '{name} 您好', 'en': 'Hello, {name}', 'id': 'Halo, {name}'},
  'intro': {
    'ko': '시술 전에 몇 가지를 여쭤볼게요',
    'ja': '施術の前にいくつかお伺いします',
    'zh-Hans': '疗程前请回答几个问题',
    'zh-Hant': '療程前請回答幾個問題',
    'en': 'A few questions before your treatment',
    'id': 'Beberapa pertanyaan sebelum perawatan',
  },
  'start': {'ko': '시작', 'ja': '始める', 'zh-Hans': '开始', 'zh-Hant': '開始', 'en': 'Start', 'id': 'Mulai'},
  'next': {'ko': '다음', 'ja': '次へ', 'zh-Hans': '下一步', 'zh-Hant': '下一步', 'en': 'Next', 'id': 'Lanjut'},
  'prev': {'ko': '이전', 'ja': '戻る', 'zh-Hans': '上一步', 'zh-Hant': '上一步', 'en': 'Back', 'id': 'Kembali'},
  'basic': {'ko': '기본 정보', 'ja': '基本情報', 'zh-Hans': '基本信息', 'zh-Hant': '基本資訊', 'en': 'Basic information', 'id': 'Informasi dasar'},
  'name': {'ko': '이름', 'ja': '氏名', 'zh-Hans': '姓名', 'zh-Hant': '姓名', 'en': 'Name', 'id': 'Nama'},
  'dob': {'ko': '생년월일', 'ja': '生年月日', 'zh-Hans': '出生日期', 'zh-Hant': '出生日期', 'en': 'Date of birth', 'id': 'Tanggal lahir'},
  'gender': {'ko': '성별', 'ja': '性別', 'zh-Hans': '性别', 'zh-Hant': '性別', 'en': 'Gender', 'id': 'Jenis kelamin'},
  'female': {'ko': '여성', 'ja': '女性', 'zh-Hans': '女', 'zh-Hant': '女', 'en': 'Female', 'id': 'Perempuan'},
  'male': {'ko': '남성', 'ja': '男性', 'zh-Hans': '男', 'zh-Hant': '男', 'en': 'Male', 'id': 'Laki-laki'},
  'phone': {'ko': '휴대폰', 'ja': '携帯電話', 'zh-Hans': '手机', 'zh-Hant': '手機', 'en': 'Mobile', 'id': 'Ponsel'},
  'address': {'ko': '주소', 'ja': '住所', 'zh-Hans': '地址', 'zh-Hant': '地址', 'en': 'Address', 'id': 'Alamat'},
  'addressDetail': {'ko': '상세 주소', 'ja': '詳細住所', 'zh-Hans': '详细地址', 'zh-Hant': '詳細地址', 'en': 'Address line 2', 'id': 'Detail alamat'},
  'required': {'ko': '필수', 'ja': '必須', 'zh-Hans': '必填', 'zh-Hant': '必填', 'en': 'Required', 'id': 'Wajib'},
  'other': {'ko': '내용을 적어 주세요', 'ja': '内容をご記入ください', 'zh-Hans': '请填写内容', 'zh-Hant': '請填寫內容', 'en': 'Please describe', 'id': 'Silakan tulis'},
  'agree': {'ko': '동의', 'ja': '同意', 'zh-Hans': '同意', 'zh-Hant': '同意', 'en': 'Consent', 'id': 'Persetujuan'},
  'agreeAll': {'ko': '모두 동의', 'ja': 'すべて同意', 'zh-Hans': '全部同意', 'zh-Hant': '全部同意', 'en': 'Agree to all', 'id': 'Setuju semua'},
  'submit': {'ko': '제출', 'ja': '送信', 'zh-Hans': '提交', 'zh-Hant': '提交', 'en': 'Submit', 'id': 'Kirim'},
  'sending': {'ko': '보내는 중…', 'ja': '送信中…', 'zh-Hans': '提交中…', 'zh-Hant': '提交中…', 'en': 'Sending…', 'id': 'Mengirim…'},
  'thanks': {'ko': '감사합니다', 'ja': 'ありがとうございました', 'zh-Hans': '谢谢', 'zh-Hant': '謝謝', 'en': 'Thank you', 'id': 'Terima kasih'},
  'thanksSub': {
    'ko': '직원에게 기기를 돌려주세요',
    'ja': 'スタッフに端末をお返しください',
    'zh-Hans': '请将设备交还给工作人员',
    'zh-Hant': '請將裝置交還給工作人員',
    'en': 'Please return the device to staff',
    'id': 'Silakan kembalikan perangkat ke staf',
  },
  'failed': {
    'ko': '제출하지 못했어요 · 직원에게 알려 주세요',
    'ja': '送信できませんでした・スタッフにお知らせください',
    'zh-Hans': '提交失败・请告知工作人员',
    'zh-Hant': '提交失敗・請告知工作人員',
    'en': "Couldn't submit · please tell a staff member",
    'id': 'Gagal mengirim · mohon beri tahu staf',
  },
  'retry': {'ko': '다시 제출', 'ja': '再送信', 'zh-Hans': '重新提交', 'zh-Hant': '重新提交', 'en': 'Submit again', 'id': 'Kirim ulang'},
  'loadFailed': {
    'ko': '문진을 불러오지 못했어요 · 직원에게 알려 주세요',
    'ja': '問診票を読み込めませんでした・スタッフにお知らせください',
    'zh-Hans': '问诊表加载失败・请告知工作人员',
    'zh-Hant': '問診表載入失敗・請告知工作人員',
    'en': "Couldn't load the form · please tell a staff member",
    'id': 'Gagal memuat formulir · mohon beri tahu staf',
  },
  'waiting': {
    'ko': '잠시 기다려 주세요',
    'ja': 'しばらくお待ちください',
    'zh-Hans': '请稍候',
    'zh-Hant': '請稍候',
    'en': 'Please wait a moment',
    'id': 'Mohon tunggu sebentar',
  },
};

// 고정 문구 — 없는 언어는 en · {name} 바꿈
String qt(String key, String lang, {String name = ''}) {
  final m = _t[key]!;
  return (m[lang] ?? m['en']!).replaceAll('{name}', name);
}
