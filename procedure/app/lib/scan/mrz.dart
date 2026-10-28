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

// ─── 글자 인식 보정(E2E batch 2 #4) — OCR-B 글꼴을 Vision 이 흔히 잘못 읽는 것을 칸 종류별로 고친다
// 숫자 칸(날짜 · 검사 숫자)에 온 글자 → 숫자
const _toDigit = {'O': '0', 'Q': '0', 'D': '0', 'U': '0', 'I': '1', 'L': '1', 'T': '1', 'Z': '2', 'S': '5', 'B': '8', 'G': '6', 'A': '4'};
// 글자 칸(국적 · 발급국 · 이름)에 온 숫자 → 글자
const _toLetter = {'0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', '6': 'G', '4': 'A'};
// 여권번호(글자 · 숫자 섞임)에서 서로 헷갈리는 짝 — 검사 숫자가 맞는 쪽을 고른다
const _swap = {'0': 'O', 'O': '0', '1': 'I', 'I': '1', '5': 'S', 'S': '5', '8': 'B', 'B': '8', '2': 'Z', 'Z': '2', '6': 'G', 'G': '6'};

String _digits(String s) => [for (final c in s.split('')) _toDigit[c] ?? c].join();
String _letters(String s) => [for (final c in s.split('')) _toLetter[c] ?? c].join();

// 채움 문자 < 를 « ‹ く 〈 등으로 읽은 것 → <
String _fillers(String s) => s.replaceAll(RegExp('[«‹く〈＜≤]'), '<');

// < 줄 안의 K — 왼쪽이 < 이고 오른쪽이 < · K · 줄 끝이면 < (이름 속 K 는 앞뒤가 글자라 그대로: PARK<< · <KIM)
String _fixK(String s) {
  final out = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    final c = s[i];
    if (c == 'K') {
      final left = out.isEmpty ? '' : out.toString()[out.length - 1];
      final right = i + 1 < s.length ? s[i + 1] : '<';
      if (left == '<' && (right == '<' || right == 'K')) {
        out.write('<');
        continue;
      }
    }
    out.write(c);
  }
  return out.toString();
}

// 글자 인식 줄 정리 — 대문자 · 채움 문자 · 공백 처리(지움 / < 로) 두 가지 후보
List<String> _variants(String raw) {
  final u = _fillers(raw.toUpperCase().trim());
  final a = _fixK(u.replaceAll(RegExp(r'\s'), ''));
  final b = _fixK(u.replaceAll(RegExp(r'\s'), '<'));
  return a == b ? [a] : [a, b];
}

// 여권번호 9칸 — 그대로 검사 숫자가 안 맞으면 헷갈리는 글자를 바꿔 본다(헷갈리는 자리 최대 6 · 적게 바꾼 것부터)
String? _docNumber(String num, String ck) {
  if (_ok(num, ck)) return num;
  final pos = [for (var i = 0; i < num.length; i++) if (_swap.containsKey(num[i])) i];
  if (pos.isEmpty || pos.length > 6) return null;
  int bits(int m) => m.toRadixString(2).replaceAll('0', '').length;
  final masks = [for (var m = 1; m < (1 << pos.length); m++) m]..sort((a, b) => bits(a).compareTo(bits(b)));
  for (final mask in masks) {
    final c = num.split('');
    for (var k = 0; k < pos.length; k++) {
      if (mask & (1 << k) != 0) c[pos[k]] = _swap[c[pos[k]]]!;
    }
    final v = c.join();
    if (_ok(v, ck)) return v;
  }
  return null;
}

// 두 줄을 44 로 맞춤 — 첫 줄은 끝 < 가 덜 · 더 읽힘, 둘째 줄은 끝이 덜 읽힘 · 한 자 더(필드 위치는 그대로 · 검사 숫자가 거른다)
String? _fit(String l, {required bool first}) {
  if (l.length == 44) return l;
  if (first) {
    // 이름이 짧으면 끝 채움 < 전체가 안 읽히기도 한다(공백 · 빈칸) — 「P?발급국 성<<」 꼴만
    if (l.length < 44 && (l.length >= 30 || (l.length >= 8 && l.contains('<<')))) return l.padRight(44, '<');
    if (l.length > 44 && l.substring(44).replaceAll('<', '').isEmpty) return l.substring(0, 44);
    return null;
  }
  // 끝(옵션 · 종합 검사 숫자) 채움 < 가 덜 읽힘 — 앞 28자(여권번호 · 국적 · 생년월일 · 성별 · 만료일)는 자리 그대로
  if (l.length >= 30 && l.length < 44) return l.padRight(44, '<');
  if (l.length == 45) return l.substring(0, 44);
  return null;
}

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

// 두 줄(44자)에서 값 — 칸 종류별 보정 뒤 여권번호 · 생년월일 · 만료일 검사 숫자 셋이 맞으면 통과.
// 종합 검사 숫자(마지막 칸)는 옵션 칸 인식이 흔들려 틀릴 수 있어 보지 않는다(E2E batch 2 #4 코디 기준)
Mrz? parseTd3(String l1, String l2, {DateTime? today}) {
  if (l1.length != 44 || l2.length != 44 || !l1.startsWith('P')) return null;
  final numCk = _digits(l2.substring(9, 10));
  final num = _docNumber(l2.substring(0, 9), numCk);
  final nat = _letters(l2.substring(10, 13));
  final dob = _digits(l2.substring(13, 19));
  final dobCk = _digits(l2.substring(19, 20));
  final sex = l2.substring(20, 21);
  final exp = _digits(l2.substring(21, 27));
  final expCk = _digits(l2.substring(27, 28));
  if (num == null || !_ok(dob, dobCk) || !_ok(exp, expCk)) return null;
  final birth = mrzDate(dob, birth: true, today: today);
  final expiry = mrzDate(exp, birth: false);
  if (birth == null || expiry == null) return null;
  // 이름 — 「성<<이름<이름」 · < → 공백 · 숫자로 읽힌 글자 고침
  final names = _letters(l1.substring(5)).split('<<');
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

// 글자 인식 줄 목록 → MRZ(못 찾으면 null). 줄마다 보정 후보를 만들고 이웃한 두 줄 · 한 덩어리(88)를 본다
Mrz? findMrz(List<String> lines, {DateTime? today}) {
  final rows = [
    for (final l in lines)
      [for (final v in _variants(l)) if (v.length >= 30 || (v.startsWith('P') && v.contains('<<'))) v],
  ].where((r) => r.isNotEmpty).toList();
  for (var i = 0; i + 1 < rows.length; i++) {
    for (final a in rows[i]) {
      if (!a.startsWith('P')) continue;
      final l1 = _fit(a, first: true);
      if (l1 == null) continue;
      for (final b in rows[i + 1]) {
        final l2 = _fit(b, first: false);
        if (l2 == null) continue;
        final m = parseTd3(l1, l2, today: today);
        if (m != null) return m;
      }
    }
  }
  // 두 줄이 한 덩어리(88)로 온 경우
  for (final r in rows) {
    for (final l in r) {
      if (l.length == 88 && l.startsWith('P')) {
        final m = parseTd3(l.substring(0, 44), l.substring(44), today: today);
        if (m != null) return m;
      }
    }
  }
  return null;
}

// MRZ 처럼 보이는 줄(< 가 든 30자 이상)이 두 줄 이상인가 — 스캔 화면 상태 글자(「두 줄 읽음」)
bool looksLikeMrz(List<String> lines) =>
    lines.expand(_variants).where((l) => l.length >= 30 && l.contains('<')).length >= 2;

// 같은 판독이 연속 두 번이면 확정(E2E batch 2 #4) — 한 프레임 잘못 읽은 값으로 찍지 않게
class MrzConfirm {
  String? _last;

  // none = MRZ 줄 없음 · lines = 두 줄은 읽었지만 검사 숫자가 안 맞음 · pending = 맞음(한 번) · confirmed = 같은 값 두 번 연속
  String feed(List<String> lines, {DateTime? today}) {
    final m = findMrz(lines, today: today);
    if (m == null) {
      _last = null;
      return looksLikeMrz(lines) ? 'lines' : 'none';
    }
    final key = '${m.passportNumber}|${m.dateOfBirth}|${m.expiryDate}|${m.surname}|${m.givenNames}|${m.nationality}|${m.gender}';
    final same = key == _last;
    _last = key;
    return same ? 'confirmed' : 'pending';
  }

  void reset() => _last = null;
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
