// 여권 MRZ 읽기(SPEC-004 §6.16 ②) — TD3(두 줄 · 44자) · ICAO 9303 검사 숫자(여권번호 · 생년월일 · 만료일 · 종합).
// 기기 안 글자 인식(iOS Vision) 결과 줄들에서 MRZ 두 줄을 찾아 값으로. 외부 서비스 0(D7-49).
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 신분증 종류 = 여권만(D7-17 · D7-51). 주민번호가 있는 신분증(주민등록증 등)을
// 넣는다면 이 자리에서 마스킹이 필요하다 — 지금은 여권 TD3 만 받고 그 밖 MRZ(TD1 · TD2)는 「읽지 못함」으로 버린다.

class Mrz {
  final String surname;
  final String givenNames;
  final String passportNumber;
  final String nationality; // alpha-2 · 모르는 코드 = ''
  final String dateOfBirth; // yyyy-MM-dd
  final String? gender; // MALE | FEMALE | null(<)
  final String expiryDate; // yyyy-MM-dd
  const Mrz({
    required this.surname,
    required this.givenNames,
    required this.passportNumber,
    required this.nationality,
    required this.dateOfBirth,
    required this.gender,
    required this.expiryDate,
  });
}

// 검사 숫자 — 가중치 7 · 3 · 1 · 0-9 · A-Z = 10-35 · < = 0
int checkDigit(String s) {
  const w = [7, 3, 1];
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    final c = s.codeUnitAt(i);
    final v = c >= 48 && c <= 57
        ? c - 48
        : c >= 65 && c <= 90
            ? c - 55
            : 0;
    sum += v * w[i % 3];
  }
  return sum % 10;
}

bool _ok(String field, String digit) => digit.length == 1 && int.tryParse(digit) == checkDigit(field);

// 숫자 자리에서 글자 인식이 흔히 헷갈리는 것 — 날짜 · 검사 숫자 칸에만
String _digits(String s) => s
    .replaceAll('O', '0')
    .replaceAll('Q', '0')
    .replaceAll('D', '0')
    .replaceAll('I', '1')
    .replaceAll('L', '1')
    .replaceAll('Z', '2')
    .replaceAll('S', '5')
    .replaceAll('B', '8')
    .replaceAll('G', '6');

// 글자 인식 줄 정리 — 공백 지움 · 대문자 · « 꼴 < 로
String _clean(String s) => s.toUpperCase().replaceAll(RegExp(r'\s'), '').replaceAll('«', '<').replaceAll('‹', '<').replaceAll('く', '<');

// 세기(r2) — 생년월일: 20YY 가 오늘보다 뒤면 19YY · 만료일: 늘 20YY
String? mrzDate(String yymmdd, {required bool birth, DateTime? today}) {
  if (!RegExp(r'^\d{6}$').hasMatch(yymmdd)) return null;
  final yy = int.parse(yymmdd.substring(0, 2));
  final mm = int.parse(yymmdd.substring(2, 4));
  final dd = int.parse(yymmdd.substring(4, 6));
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return null;
  var y = 2000 + yy;
  if (birth) {
    final now = today ?? DateTime.now();
    if (DateTime(y, mm, dd).isAfter(DateTime(now.year, now.month, now.day))) y -= 100;
  }
  String p(int n) => n.toString().padLeft(2, '0');
  return '$y-${p(mm)}-${p(dd)}';
}

// 두 줄(정리된 44자)에서 값 — 검사 숫자 하나라도 틀리면 null
Mrz? parseTd3(String l1, String l2, {DateTime? today}) {
  if (l1.length != 44 || l2.length != 44 || !l1.startsWith('P')) return null;
  final num = l2.substring(0, 9);
  final numCk = _digits(l2.substring(9, 10));
  final nat = l2.substring(10, 13);
  final dob = _digits(l2.substring(13, 19));
  final dobCk = _digits(l2.substring(19, 20));
  final sex = l2.substring(20, 21);
  final exp = _digits(l2.substring(21, 27));
  final expCk = _digits(l2.substring(27, 28));
  final opt = l2.substring(28, 43);
  final allCk = _digits(l2.substring(43, 44));
  if (!_ok(num, numCk) || !_ok(dob, dobCk) || !_ok(exp, expCk)) return null;
  if (!_ok('$num$numCk$dob$dobCk$exp$expCk$opt', allCk)) return null;
  final birth = mrzDate(dob, birth: true, today: today);
  final expiry = mrzDate(exp, birth: false);
  if (birth == null || expiry == null) return null;
  // 이름 — 「성<<이름<이름」 · < → 공백
  final names = l1.substring(5).split('<<');
  String words(String s) => s.split('<').where((w) => w.isNotEmpty).join(' ');
  return Mrz(
    surname: words(names.first),
    givenNames: words(names.skip(1).join('<<')),
    passportNumber: num.replaceAll('<', ''),
    nationality: alpha2(nat),
    dateOfBirth: birth,
    gender: switch (sex) {
      'M' => 'MALE',
      'F' => 'FEMALE',
      _ => null,
    },
    expiryDate: expiry,
  );
}

// 글자 인식 줄 목록 → MRZ(못 찾으면 null). 줄이 쪼개져 오면 이어 붙여 본다
Mrz? findMrz(List<String> lines, {DateTime? today}) {
  final c = lines.map(_clean).where((l) => l.length >= 30).toList();
  // 한 줄 44 짜리 둘이 이어진 경우
  for (var i = 0; i + 1 < c.length; i++) {
    if (c[i].startsWith('P') && c[i].length == 44 && c[i + 1].length == 44) {
      final m = parseTd3(c[i], c[i + 1], today: today);
      if (m != null) return m;
    }
  }
  // 두 줄이 한 덩어리(88)로 온 경우
  for (final l in c) {
    if (l.length == 88 && l.startsWith('P')) {
      final m = parseTd3(l.substring(0, 44), l.substring(44), today: today);
      if (m != null) return m;
    }
  }
  // 끝 < 가 덜 읽혀 44 보다 짧은 첫 줄 — < 로 채워 본다
  for (var i = 0; i + 1 < c.length; i++) {
    if (c[i].startsWith('P<') && c[i].length < 44 && c[i + 1].length == 44) {
      final m = parseTd3(c[i].padRight(44, '<'), c[i + 1], today: today);
      if (m != null) return m;
    }
  }
  return null;
}

// ICAO 국가 코드(alpha-3) → alpha-2(앱 표 · 웹 국가 표에 있는 나라 + 독일 D) · 모르는 코드 = ''
const _a3 = {
  'KOR': 'KR', 'CHN': 'CN', 'TWN': 'TW', 'HKG': 'HK', 'MAC': 'MO', 'JPN': 'JP', 'USA': 'US', 'CAN': 'CA', 'GBR': 'GB',
  'AUS': 'AU', 'NZL': 'NZ', 'IRL': 'IE', 'SGP': 'SG', 'MYS': 'MY', 'THA': 'TH', 'VNM': 'VN', 'PHL': 'PH', 'IDN': 'ID',
  'MNG': 'MN', 'KAZ': 'KZ', 'UZB': 'UZ', 'KHM': 'KH', 'MMR': 'MM', 'LAO': 'LA', 'BRN': 'BN', 'IND': 'IN', 'NPL': 'NP',
  'BGD': 'BD', 'PAK': 'PK', 'LKA': 'LK', 'ARE': 'AE', 'SAU': 'SA', 'QAT': 'QA', 'KWT': 'KW', 'ISR': 'IL', 'TUR': 'TR',
  'RUS': 'RU', 'UKR': 'UA', 'D': 'DE', 'DEU': 'DE', 'FRA': 'FR', 'ITA': 'IT', 'ESP': 'ES', 'PRT': 'PT', 'NLD': 'NL',
  'BEL': 'BE', 'CHE': 'CH', 'AUT': 'AT', 'SWE': 'SE', 'NOR': 'NO', 'DNK': 'DK', 'FIN': 'FI', 'POL': 'PL', 'CZE': 'CZ',
  'HUN': 'HU', 'GRC': 'GR', 'ROU': 'RO', 'MEX': 'MX', 'BRA': 'BR', 'ARG': 'AR', 'CHL': 'CL', 'COL': 'CO', 'PER': 'PE',
  'EGY': 'EG', 'ZAF': 'ZA', 'NGA': 'NG', 'KEN': 'KE', 'MAR': 'MA', 'GBD': 'GB', 'GBN': 'GB', 'GBO': 'GB',
};
String alpha2(String a3) => _a3[a3.replaceAll('<', '')] ?? '';
