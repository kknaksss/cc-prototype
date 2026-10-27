// 여권 스캔(SPEC-004 §6.16 · §8.7) — 3번 실패 → 손 입력 · 읽은 값 확인 · 바꾼 칸만 저장 · 카메라 없음 길(견본 · 지어낸 값)
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/reservation.dart';
import 'package:procedure_app/scan/mrz.dart';
import 'package:procedure_app/scan/scan_channel.dart';
import 'package:procedure_app/screens/scan_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'mrz_test.dart' show make;

ResvDetail detail() => ResvDetail.fromJson({
      'reservationId': 9, 'day': '2026-10-27', 'state': {'main': 'reception', 'sub': null},
      'customer': {
        'customerId': 3, 'name': '고객 A', 'isNew': true,
        'personal': {'passportSurname': 'TEST', 'passportGivenNames': '', 'passportNumber': 'X00000000', 'nationality': 'JP',
                     'dateOfBirth': '1995-03-05', 'gender': 'FEMALE', 'passportExpiryDate': null},
        'identity': {'status': 'unconfirmed', 'kind': 'foreign', 'fields': [], 'complete': false},
      },
      'reservation': {'sedationRequired': false, 'doctors': []}, 'health': {'state': 'none', 'items': []}, 'previousVisits': [],
      'can': {}, 'rooms': [], 'counselors': [],
    });

// 1×1 그림(지어낸 것 — 사람 · 신분증 아님)
final png = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const ch = MethodChannel('procedure/scan');

  test('바꿀 칸만 — KOS 와 같거나 빈 칸은 안 보냄 · name 칸 없음', () {
    final (l1, l2) = make();
    final read = mrzValues(parseTd3(l1, l2, today: DateTime(2026, 10, 27)));
    final kos = {'passportSurname': 'TEST', 'passportNumber': 'X00000000', 'nationality': 'JP', 'dateOfBirth': '1995-03-05', 'gender': 'FEMALE'};
    final out = changedFields(read, kos);
    expect(out.keys.toSet(), {'passportGivenNames', 'passportNumber', 'passportExpiryDate'});
    expect(out['passportExpiryDate'], '2033-01-01');
    expect(scanFields.any((f) => f.$1 == 'name'), isFalse);
  });

  Future<(AppState, List<http.BaseRequest>)> pump(WidgetTester t, {required Future<Object?> Function(MethodCall) native}) async {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, native);
    final reqs = <http.BaseRequest>[];
    final api = Api(
      base: () => 'http://x',
      token: () => 't',
      client: MockClient.streaming((req, body) async {
        reqs.add(req);
        final bytes = await body.toBytes();
        reqs.add(http.Request('BODY', Uri.parse('http://x'))..bodyBytes = bytes);
        return http.StreamedResponse(
            Stream.value(utf8.encode(jsonEncode({'ok': true, 'personal': 'ok', 'skipped': [], 'photo': {'ccc': 'ok', 'kos': 'failed'}, 'photoId': 5}))), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    final app = AppState(api: api);
    t.view.physicalSize = const Size(1179, 2556);
    t.view.devicePixelRatio = 3;
    await t.pumpWidget(AppScope(state: app, child: MaterialApp(home: ScanScreen(detail: detail(), channel: const ScanChannel(ch)))));
    await t.pumpAndSettle();
    return (app, reqs);
  }

  testWidgets('3번 읽지 못함 → [손으로 입력] → 빈 확인 화면 → 저장 manual=true', (t) async {
    final (app, reqs) = await pump(t, native: (c) async => switch (c.method) {
          'takePassportPhoto' => png,
          'recognizeText' => ['PASSPORT', '아무 글자'],
          _ => null,
        });
    expect(find.text('읽지 못했어요 · 다시 찍어 주세요'), findsOneWidget);
    expect(find.text('손으로 입력'), findsNothing);
    await t.tap(find.text('다시 찍기'));
    await t.pumpAndSettle();
    await t.tap(find.text('다시 찍기'));
    await t.pumpAndSettle();
    expect(find.text('손으로 입력'), findsOneWidget); // 3번째 실패
    await t.tap(find.text('손으로 입력'));
    await t.pumpAndSettle();
    expect(find.text('손으로 입력'), findsOneWidget); // 확인 화면 제목
    await t.enterText(find.byKey(const Key('scan-passportNumber')), 'TK0000009');
    await t.tap(find.text('저장'));
    await t.pumpAndSettle();
    final body = latin1.decode((reqs.last as http.Request).bodyBytes);
    expect(body, contains('name="manual"\r\n\r\ntrue'));
    expect(body, contains('"passportNumber":"TK0000009"'));
    expect(body, contains('name="reservationId"\r\n\r\n9'));
    expect(body, isNot(contains('name="photo"'))); // 손 입력 = 사진 없이(r1 FAIL-2)
    expect(find.text('저장했어요'), findsOneWidget);
    expect(find.text('사진 다시 올리기'), findsOneWidget); // (가짜 응답이 사진 결과를 줄 때) KOS 사진 실패 → 다시 올리기
    app.stream.dispose();
  });

  testWidgets('MRZ 읽힘 → 확인 화면(다른 칸 강조) → 바꾼 칸만 multipart', (t) async {
    final (l1, l2) = make();
    final (app, reqs) = await pump(t, native: (c) async => switch (c.method) {
          'takePassportPhoto' => png,
          'recognizeText' => ['PASSPORT', l1, l2],
          _ => null,
        });
    expect(find.text('읽은 값을 확인하세요'), findsOneWidget);
    expect(find.text('KOS 지금 값'), findsOneWidget);
    await t.tap(find.text('저장'));
    await t.pumpAndSettle();
    final body = latin1.decode((reqs.last as http.Request).bodyBytes);
    final fields = RegExp(r'name="fields"\r\n\r\n(.*?)\r\n').firstMatch(body)!.group(1)!;
    expect((jsonDecode(fields) as Map).keys.toSet(), {'passportGivenNames', 'passportNumber', 'passportExpiryDate'});
    expect(body, contains('name="manual"\r\n\r\nfalse'));
    expect(body, contains('name="photo"')); // 카메라로 읽은 길 = 사진 필수 그대로
    app.stream.dispose();
  });

  testWidgets('손 입력 저장 응답 photo: null → 「사진 없음 · 손으로 입력」(r1 FAIL-2)', (t) async {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (c) async => throw PlatformException(code: 'no_camera'));
    final api = Api(
      base: () => 'http://x',
      token: () => 't',
      client: MockClient.streaming((req, body) async {
        await body.toBytes();
        return http.StreamedResponse(Stream.value(utf8.encode('{"ok":true,"personal":"ok","skipped":[],"photo":null,"photoId":null}')), 200);
      }),
    );
    final app = AppState(api: api);
    t.view.physicalSize = const Size(1179, 2556);
    t.view.devicePixelRatio = 3;
    await t.pumpWidget(AppScope(state: app, child: MaterialApp(home: ScanScreen(detail: detail(), channel: const ScanChannel(ch)))));
    await t.pumpAndSettle();
    await t.tap(find.text('손으로 입력'));
    await t.pumpAndSettle();
    await t.enterText(find.byKey(const Key('scan-passportNumber')), 'TK0000009');
    await t.tap(find.text('저장'));
    await t.pumpAndSettle();
    expect(find.text('사진 없음 · 손으로 입력'), findsOneWidget);
    expect(find.textContaining('KOS 사진'), findsNothing);
    expect(find.text('사진 다시 올리기'), findsNothing);
    app.stream.dispose();
  });

  testWidgets('카메라 없음(시뮬레이터) → [손으로 입력]', (t) async {
    final (app, _) = await pump(t, native: (c) async => throw PlatformException(code: 'no_camera'));
    expect(find.text('이 기기는 카메라를 쓸 수 없어요'), findsOneWidget);
    expect(find.text('손으로 입력'), findsOneWidget);
    app.stream.dispose();
  });
}
