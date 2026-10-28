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
    // 종합 검사 숫자만 틀림 = 통과(E2E batch 2 #4 — 여권번호 · 생년월일 · 만료일 셋이 맞으면)
    final badAll = l2.replaceRange(43, 44, '${(int.parse(l2[43]) + 1) % 10}');
    expect(parseTd3(l1, badAll, today: today)?.passportNumber, 'TK0000001');
    final badDob = l2.replaceRange(19, 20, '${(int.parse(l2[19]) + 1) % 10}');
    expect(parseTd3(l1, badDob, today: today), isNull);
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

  // ─── E2E batch 2 #4 — 오인식을 섞은 견본(지어낸 값)
  group('글자 인식 보정', () {
    final (l1, l2) = make(sur: 'PARK', given: 'MINJI', nat: 'KOR', num: 'M12345678', dob: '900215', sex: 'F', exp: '310630');

    test('채움 < 를 K · « 로 읽음 · 이름 속 K(PARK)는 그대로', () {
      final r1 = l1.replaceFirst('<<<<<<<', '<<KK«<K');
      final r2 = l2.replaceFirst('<<<<<<', '<K<<KK');
      final m = findMrz([r1, r2], today: today)!;
      expect(m.surname, 'PARK');
      expect(m.givenNames, 'MINJI');
      expect(m.passportNumber, 'M12345678');
    });

    test('< 자리가 공백으로 읽힘 · 공백이 끼어듦', () {
      final m = findMrz([l1.replaceAll('<<<<', '    '), l2.replaceAll('<<', '  ')], today: today);
      expect(m?.expiryDate, '2031-06-30');
      final m2 = findMrz(['${l1.substring(0, 10)} ${l1.substring(10)}', '${l2.substring(0, 9)} ${l2.substring(9)}'], today: today);
      expect(m2?.dateOfBirth, '1990-02-15');
    });

    test('숫자 칸 O→0 · I→1 · S→5 · B→8 · 국적 글자 칸 0→O · 이름 칸 숫자 → 글자', () {
      // 생년월일 900215 → 9OO2I5 · 만료일 310630 → 3IO63O · 국적 KOR → K0R · 이름 MINJI → M1NJ1
      var r2 = l2.replaceRange(13, 19, '9OO2I5').replaceRange(21, 27, '3IO63O').replaceRange(10, 13, 'K0R');
      final r1 = l1.replaceFirst('MINJI', 'M1NJ1');
      final m = findMrz([r1, r2], today: today)!;
      expect(m.dateOfBirth, '1990-02-15');
      expect(m.expiryDate, '2031-06-30');
      expect(m.nationality, 'KR');
      expect(m.givenNames, 'MINJI');
      // 검사 숫자 칸 S → 5 · B → 8
      final ck = l2[19];
      r2 = l2.replaceRange(19, 20, ck == '5' ? 'S' : ck == '8' ? 'B' : ck);
      expect(findMrz([l1, r2], today: today)?.dateOfBirth, '1990-02-15');
    });

    test('여권번호의 0 ↔ O · 1 ↔ I 헷갈림 — 검사 숫자가 맞는 쪽', () {
      final (a1, a2) = make(num: 'TO1234567');
      final r2 = a2.replaceRange(0, 9, 'T01234567'); // O 를 0 으로 읽음
      expect(findMrz([a1, r2], today: today)?.passportNumber, 'TO1234567');
    });

    test('둘째 줄 한 자 덜 · 더 읽힘(옵션 칸 끝) · 첫 줄 끝 < 더 읽힘', () {
      expect(findMrz([l1, l2.substring(0, 43)], today: today)?.passportNumber, 'M12345678');
      expect(findMrz([l1, '$l2<'], today: today)?.passportNumber, 'M12345678');
      expect(findMrz(['$l1<<', l2], today: today)?.passportNumber, 'M12345678');
    });

    test('같은 판독 연속 두 번이면 확정 · 사이에 다른 판독 · 못 읽음이 끼면 처음부터', () {
      final c = MrzConfirm();
      expect(c.feed(['아무 글자'], today: today), 'none');
      expect(c.feed([l1, l2.replaceRange(19, 20, 'X')], today: today), 'lines'); // 두 줄 · 검사 숫자 안 맞음
      expect(c.feed([l1, l2], today: today), 'pending');
      expect(c.feed([l1, l2], today: today), 'confirmed');
      final (b1, b2) = make(num: 'X99999999');
      expect(c.feed([l1, l2], today: today), 'confirmed');
      expect(c.feed([b1, b2], today: today), 'pending'); // 다른 판독
      expect(c.feed(['PASSPORT'], today: today), 'none');
      expect(c.feed([b1, b2], today: today), 'pending'); // 못 읽음 뒤 = 처음부터
    });
  });
}
