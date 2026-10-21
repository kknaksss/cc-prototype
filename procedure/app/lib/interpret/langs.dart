// 통역 언어(SPEC-004 §4.4) · 빠른 말하기 문구(§5 — 하드코딩)
class Lang {
  final String code; // WS start lang
  final String name;
  const Lang(this.code, this.name);
}

const langs = [
  Lang('zh', '중국어'),
  Lang('en', '영어'),
  Lang('ja', '일본어'),
  Lang('th', '태국어'),
  Lang('fr', '프랑스어'),
  Lang('es', '스페인어'),
  Lang('tl', '타갈로그어'),
  Lang('hi', '힌디어'),
];

String langName(String code) => langs.firstWhere((l) => l.code == code, orElse: () => const Lang('en', '영어')).name;

// 고객 국적 → 자동 언어(이전 front NAT_LANG). KR · 없음 · 그 밖 = en
const _natLang = {'TW': 'zh', 'CN': 'zh', 'HK': 'zh', 'US': 'en', 'PH': 'en', 'IN': 'en', 'JP': 'ja', 'TH': 'th', 'FR': 'fr'};
const _traditional = {'TW', 'HK'};

class AutoLang {
  final String code;
  final bool traditional;
  const AutoLang(this.code, this.traditional);
}

AutoLang autoLang(String? nationality) {
  final n = (nationality ?? '').trim().toUpperCase();
  return AutoLang(_natLang[n] ?? 'en', _traditional.contains(n));
}

// 빠른 말하기 — 키 = 언어(zh 는 번체 zhTW · 간체 zhCN)
class Phrase {
  final String ko;
  final Map<String, String> tr;
  const Phrase(this.ko, this.tr);
}

String phraseKey(String code, bool traditional) => code == 'zh' ? (traditional ? 'zhTW' : 'zhCN') : code;

const phrases = [
  Phrase('조금 뜨거울 수 있어요', {
    'zhTW': '會有一點熱', 'zhCN': '会有一点热', 'en': 'It may feel a little hot.', 'ja': '少し熱くなります',
    'th': 'อาจจะรู้สึกร้อนเล็กน้อยนะคะ', 'fr': 'Cela peut chauffer un peu.', 'es': 'Puede sentir un poco de calor.',
    'tl': 'Maaaring medyo mainit po ito.', 'hi': 'थोड़ी गर्मी महसूस हो सकती है।',
  }),
  Phrase('아프면 손을 들어주세요', {
    'zhTW': '痛的話請舉手', 'zhCN': '痛的话请举手', 'en': 'If it hurts, please raise your hand.', 'ja': '痛かったら手を挙げてください',
    'th': 'ถ้าเจ็บ กรุณายกมือขึ้นนะคะ', 'fr': "Si vous avez mal, levez la main, s'il vous plaît.",
    'es': 'Si le duele, levante la mano, por favor.', 'tl': 'Kung masakit po, pakitaas ang inyong kamay.',
    'hi': 'दर्द हो तो कृपया हाथ उठाइए।',
  }),
  Phrase('눈을 감아주세요', {
    'zhTW': '請閉上眼睛', 'zhCN': '请闭上眼睛', 'en': 'Please close your eyes.', 'ja': '目を閉じてください',
    'th': 'กรุณาหลับตานะคะ', 'fr': "Fermez les yeux, s'il vous plaît.", 'es': 'Cierre los ojos, por favor.',
    'tl': 'Pakipikit po ang inyong mga mata.', 'hi': 'कृपया आँखें बंद कीजिए।',
  }),
  Phrase('10분 정도 걸려요', {
    'zhTW': '大約需要十分鐘', 'zhCN': '大约需要十分钟', 'en': 'It will take about 10 minutes.', 'ja': '10分ほどかかります',
    'th': 'ใช้เวลาประมาณ 10 นาทีค่ะ', 'fr': 'Cela prendra environ 10 minutes.', 'es': 'Tardará unos 10 minutos.',
    'tl': 'Aabutin po ito ng mga 10 minuto.', 'hi': 'इसमें लगभग 10 मिनट लगेंगे।',
  }),
  Phrase('움직이지 마세요', {
    'zhTW': '請不要動', 'zhCN': '请不要动', 'en': "Please don't move.", 'ja': '動かないでください',
    'th': 'กรุณาอย่าขยับนะคะ', 'fr': "Ne bougez pas, s'il vous plaît.", 'es': 'No se mueva, por favor.',
    'tl': 'Huwag po kayong gumalaw.', 'hi': 'कृपया हिलें नहीं।',
  }),
  Phrase('다 끝났습니다', {
    'zhTW': '已經結束了', 'zhCN': '已经结束了', 'en': "We're all done.", 'ja': '終わりました',
    'th': 'เสร็จเรียบร้อยแล้วค่ะ', 'fr': "C'est terminé.", 'es': 'Ya hemos terminado.', 'tl': 'Tapos na po.',
    'hi': 'सब पूरा हो गया है।',
  }),
];

// TTS 음성 로캘(§5)
String ttsLocale(String code, bool traditional) => switch (code) {
      'zh' => traditional ? 'zh-TW' : 'zh-CN',
      'en' => 'en-US',
      'ja' => 'ja-JP',
      'th' => 'th-TH',
      'fr' => 'fr-FR',
      'es' => 'es-ES',
      'tl' => 'fil-PH',
      'hi' => 'hi-IN',
      _ => 'en-US',
    };

// 화면 이름(번체면 「중국어(번체)」)
String langLabel(String code, bool traditional) => code == 'zh' ? (traditional ? '중국어(번체)' : '중국어(간체)') : langName(code);
