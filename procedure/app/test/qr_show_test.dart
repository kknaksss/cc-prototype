// WORK-010 WP-APP — 문진 QR 화면(SPEC-006 §8.2 · §10.2) · 띄우기(문진) = QR 화면 · [이 기기에 QR 보이기]. 링크 · 토큰은 지어낸 값
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/display.dart';
import 'package:procedure_app/model/reservation.dart';
import 'package:procedure_app/scan/scan_channel.dart';
import 'package:procedure_app/screens/launchers.dart';
import 'package:procedure_app/screens/qr_show_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'scan_test.dart' show png;

const scan = MethodChannel('procedure/scan');
const fakeUrl = 'https://example.invalid/q#not-a-real-token';
final json = {'content-type': 'application/json; charset=utf-8'};

Map<String, dynamic> detailWith(String status) => {
      'reservationId': 9, 'day': '2026-10-28', 'state': {'main': 'reception', 'sub': null},
      'customer': {'customerId': 3, 'name': '고객 A', 'isNew': true, 'personal': {},
                   'identity': {'status': 'unconfirmed', 'kind': 'foreign', 'fields': [], 'complete': false}},
      'reservation': {'sedationRequired': false, 'doctors': []}, 'health': {'state': 'none', 'items': []}, 'previousVisits': [],
      'can': {}, 'rooms': [], 'counselors': [],
      'displays': [
        {'id': 41, 'kind': 'questionnaire', 'status': status, 'deviceName': null, 'createdAt': '2026-10-28T10:00:00+09:00', 'closedAt': null,
         'qrUrl': status == 'pending' ? fakeUrl : null},
      ],
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  // QR 화면을 버튼 뒤에 올린다(닫히면 버튼이 다시 보임)
  Future<(AppState, List<MethodCall>, List<http.Request>, List<String>)> pump(WidgetTester t, {String expiresIn = '+5m'}) async {
    SharedPreferences.setMockInitialValues({});
    final native = <MethodCall>[];
    messenger.setMockMethodCallHandler(scan, (c) async {
      native.add(c);
      return c.method == 'qrImage' ? png : null;
    });
    final reqs = <http.Request>[];
    final statuses = <String>['pending'];
    final app = AppState(
      api: Api(
        base: () => 'http://x',
        token: () => 't',
        client: MockClient((req) async {
          reqs.add(req);
          final st = statuses.length > 1 ? statuses.removeAt(0) : statuses.first;
          return http.Response(jsonEncode(detailWith(st)), 200, headers: json);
        }),
      ),
    );
    t.view.physicalSize = const Size(1179, 2556);
    t.view.devicePixelRatio = 3;
    final until = DateTime.now().add(const Duration(minutes: 5)).toIso8601String();
    await t.pumpWidget(AppScope(
      state: app,
      child: MaterialApp(
        home: Builder(
          builder: (ctx) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () => Navigator.of(ctx).push(MaterialPageRoute(
                    builder: (_) => QrShowScreen(
                        requestId: 41, reservationId: 9, qrUrl: fakeUrl, expiresAt: until, channel: const ScanChannel(scan), poll: const Duration(seconds: 1)))),
                child: const Text('열기'),
              ),
            ),
          ),
        ),
      ),
    ));
    await t.tap(find.text('열기'));
    await t.pumpAndSettle();
    return (app, native, reqs, statuses);
  }

  testWidgets('qrUrl 로 QR 을 그림 · 안내 두 줄 · 남은 시간 · 고객 이름 없음 · 꺼짐 막기', (t) async {
    final (app, native, _, _) = await pump(t);
    expect(find.text('휴대폰 카메라로 QR 을 찍어 주세요'), findsOneWidget);
    expect(find.text('Scan with your phone camera'), findsOneWidget);
    expect(find.bySemanticsLabel('문진 QR'), findsOneWidget);
    expect(find.textContaining('남은 시간 0'), findsOneWidget); // 04:59 안팎
    expect(find.textContaining('고객 A'), findsNothing);
    expect(native.firstWhere((c) => c.method == 'qrImage').arguments['text'], fakeUrl);
    expect(native.any((c) => c.method == 'keepAwake' && c.arguments == true), isTrue);
    await t.tap(find.text('닫기'));
    await t.pumpAndSettle();
    app.stream.dispose();
  });

  testWidgets('폴링 — pending 이면 그대로 · opened 가 되면 「고객 폰에서 열렸어요」 1.5초 뒤 저절로 닫힘 · 꺼짐 막기 풂', (t) async {
    final (app, native, reqs, statuses) = await pump(t);
    statuses
      ..clear()
      ..addAll(['pending', 'opened']);
    await t.pump(const Duration(seconds: 1));
    await t.pump();
    expect(find.byType(QrShowScreen), findsOneWidget);
    await t.pump(const Duration(seconds: 1));
    await t.pump();
    expect(find.text('고객 폰에서 열렸어요'), findsOneWidget);
    expect(reqs.every((r) => r.url.path == '/api/reservations/9' && r.method == 'GET'), isTrue); // 닫기 요청 등 쓰기 없음
    await t.pump(const Duration(milliseconds: 1600));
    await t.pumpAndSettle();
    expect(find.byType(QrShowScreen), findsNothing);
    expect(native.last.method == 'keepAwake' && native.last.arguments == false, isTrue);
    app.stream.dispose();
  });

  testWidgets('[닫기] = 화면만 — 요청은 그대로(close · cancel 안 부름)', (t) async {
    final (app, _, reqs, _) = await pump(t);
    await t.tap(find.text('닫기'));
    await t.pumpAndSettle();
    expect(find.byType(QrShowScreen), findsNothing);
    expect(reqs.where((r) => r.method == 'POST'), isEmpty);
    app.stream.dispose();
  });

  test('닫히며 보일 한 줄', () {
    expect(qrClosedLine('opened'), '고객 폰에서 열렸어요');
    expect(qrClosedLine('done'), '제출됐어요');
    expect(qrClosedLine('expired'), '시간이 지났어요');
    expect(qrClosedLine('canceled'), '닫혔어요');
  });

  group('여는 길', () {
    late QrOpener saved;
    setUp(() => saved = openQrScreen);
    tearDown(() => openQrScreen = saved);

    testWidgets('띄우기(문진) = QR 화면(qrUrl · 남은 시간) · qrUrl 없으면 토스트', (t) async {
      SharedPreferences.setMockInitialValues({});
      final opened = <(int, int, String, String?)>[];
      openQrScreen = (ctx, {required requestId, required reservationId, required qrUrl, expiresAt}) async =>
          opened.add((requestId, reservationId, qrUrl, expiresAt));
      final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((_) async => http.Response('{}', 200))));
      late BuildContext ctx;
      await t.pumpWidget(AppScope(state: app, child: MaterialApp(home: Builder(builder: (c) => (ctx = c, const SizedBox()).$2))));
      await openDisplay(ctx, const DisplayReq(requestId: 41, kind: 'questionnaire', reservationId: 9, qrUrl: fakeUrl, expiresAt: 'E'));
      expect(opened, [(41, 9, fakeUrl, 'E')]);
      await openDisplay(ctx, const DisplayReq(requestId: 42, kind: 'questionnaire', reservationId: 9));
      expect(opened.length, 1);
      expect(app.toaster.text, '문진 QR 을 받지 못했어요');
      await t.pump(const Duration(seconds: 3)); // 토스트 타이머
      app.stream.dispose();
    });

    testWidgets('[이 기기에 QR 보이기] = POST {reservationId, kind: questionnaire}(deviceId 없이) → 응답 qrUrl 로 QR 화면', (t) async {
      SharedPreferences.setMockInitialValues({});
      final opened = <(int, int, String)>[];
      openQrScreen = (ctx, {required requestId, required reservationId, required qrUrl, expiresAt}) async =>
          opened.add((requestId, reservationId, qrUrl));
      final bodies = <Object?>[];
      final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((req) async {
        bodies.add(jsonDecode(req.body));
        return http.Response(jsonEncode({'id': 43, 'qrToken': null, 'qrUrl': fakeUrl, 'expiresAt': '2026-10-28T10:10:00+09:00'}), 200);
      })));
      app.deviceId = 9; // 기기 행이 있어도 이 기기 QR 은 deviceId 없이
      late BuildContext ctx;
      await t.pumpWidget(AppScope(state: app, child: MaterialApp(home: Builder(builder: (c) => (ctx = c, const SizedBox()).$2))));
      await showQuestionnaireQrHere(ctx, ResvDetail.fromJson(detailWith('pending')));
      expect(bodies, [
        {'reservationId': 9, 'kind': 'questionnaire'},
      ]);
      expect(opened, [(43, 9, fakeUrl)]);
      app.stream.dispose();
    });
  });
}
