// MRZ 파서(SPEC-004 §6.16 ② · §8.7) — ICAO 9303 견본값 · 지어낸 값만(실명 · 실제 여권 없음)
import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/scan/mrz.dart';

// 지어낸 여권 두 줄을 검사 숫자까지 맞춰 만든다
(String, String) make({String sur = 'TEST', String given = 'SAMPLE<PERSON', String nat = 'JPN', String num = 'TK0000001', String dob = '950305', String sex = 'F', String exp = '330101'}) {
  final l1 = 'P<$nat$sur<<$given'.padRight(44, '<');
  final n = num.padRight(9, '<');
  final opt = ''.padRight(14, '<');
  final optCk = '<';
  final body = '$n${checkDigit(n)}$nat$dob${checkDigit(dob)}$sex$exp${checkDigit(exp)}$opt$optCk';
  final all = checkDigit('$n${checkDigit(n)}$dob${checkDigit(dob)}$exp${checkDigit(exp)}$opt$optCk');
  return (l1, '$body$all');
}

void main() {
  final today = DateTime(2026, 10, 27);

  test('검사 숫자 — ICAO 9303 견본(L898902C3 → 6 · 740812 → 2 · 120415 → 9)', () {
    expect(checkDigit('L898902C3'), 6);
    expect(checkDigit('740812'), 2);
    expect(checkDigit('120415'), 9);
    expect(checkDigit('<<<<<'), 0);
  });

  test('ICAO 견본 TD3 — 이름 < → 공백 · 모르는 나라(UTO) = 빈 값 · 세기', () {
    final m = parseTd3('P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<', 'L898902C36UTO7408122F1204159ZE184226B<<<<<10', today: today)!;
    expect(m.surname, 'ERIKSSON');
    expect(m.givenNames, 'ANNA MARIA');
    expect(m.passportNumber, 'L898902C3');
    expect(m.nationality, ''); // alpha-3 표에 없음
    expect(m.dateOfBirth, '1974-08-12'); // 2074 > 오늘 → 19
    expect(m.gender, 'FEMALE');
    expect(m.expiryDate, '2012-04-15'); // 만료일 = 늘 20YY
  });

  test('지어낸 견본 — alpha-3 → alpha-2 · 2000년대 생', () {
    final (l1, l2) = make(nat: 'KOR', dob: '050101', sex: 'M');
    final m = parseTd3(l1, l2, today: today)!;
    expect(m.nationality, 'KR');
    expect(m.dateOfBirth, '2005-01-01');
    expect(m.gender, 'MALE');
    expect(m.givenNames, 'SAMPLE PERSON');
    expect(alpha2('D<<'), 'DE');
    expect(alpha2('TWN'), 'TW');
  });

  test('세기 규칙 — 생년월일 YY 가 올해 뒤면 19xx · 만료일은 늘 20xx', () {
    expect(mrzDate('261027', birth: true, today: today), '2026-10-27'); // 오늘 = 20
    expect(mrzDate('261028', birth: true, today: today), '1926-10-28'); // 내일 = 19
    expect(mrzDate('990101', birth: false), '2099-01-01');
    expect(mrzDate('991301', birth: false), isNull);
  });

  test('검사 숫자 틀림 → null(「읽지 못했어요」)', () {
    final (l1, l2) = make();
    final bad = l2.replaceRange(9, 10, '${(int.parse(l2[9]) + 1) % 10}');
    expect(parseTd3(l1, bad, today: today), isNull);
    final badAll = l2.replaceRange(43, 44, '${(int.parse(l2[43]) + 1) % 10}');
    expect(parseTd3(l1, badAll, today: today), isNull);
  });

  test('글자 인식 줄에서 찾기 — 공백 · 소문자 · 앞뒤 다른 글자 · 날짜 칸 O→0 · 첫 줄 끝 < 덜 읽힘', () {
    final (l1, l2) = make(dob: '900101');
    final noisy = ['PASSPORT', 'Surname / 성', 'TEST', l1.substring(0, 30).toLowerCase(), l2.replaceRange(14, 15, 'O').replaceAll('<', ' <')];
    // 첫 줄이 30자만 읽힘 → < 로 채움 · 날짜 9 → 그대로 · O → 0
    final m = findMrz([...noisy.take(3), l1.substring(0, 30), l2.replaceRange(14, 15, 'O')], today: today);
    expect(m?.dateOfBirth, '1990-01-01');
    expect(findMrz(['$l1$l2'], today: today)?.passportNumber, 'TK0000001'); // 한 덩어리 88
    expect(findMrz(['아무 글자', 'P<JPN'], today: today), isNull);
    expect(noisy, isNotEmpty);
  });
}
