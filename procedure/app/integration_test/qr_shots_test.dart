// WORK-010 WP-APP 스크린샷 — 문진 QR 화면(SPEC-006 §8.2). back 없이 가짜 응답 · 지어낸 링크(쓸 수 없는 주소 · 토큰 아님)라 가릴 것 없음
// flutter drive --driver=test_driver/integration_test.dart --target=integration_test/qr_shots_test.dart -d <시뮬레이터> --dart-define=SHOT=phone|tablet
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:integration_test/integration_test.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/screens/qr_show_screen.dart';
import 'package:procedure_app/theme/tokens.dart';

const shot = String.fromEnvironment('SHOT', defaultValue: 'phone');
const fakeUrl = 'https://example.invalid/q#not-a-real-token-screenshot-only';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('qr shots', (t) async {
    var status = 'pending';
    final app = AppState(
      api: Api(
        base: () => 'http://x',
        token: () => 't',
        client: MockClient((req) async => http.Response(
            jsonEncode({
              'reservationId': 9, 'day': '2026-10-28', 'state': {'main': 'reception', 'sub': null},
              'customer': {'customerId': 3, 'name': '고객', 'isNew': true, 'personal': {}, 'identity': {'status': 'unconfirmed', 'kind': 'foreign', 'fields': [], 'complete': false}},
              'reservation': {'sedationRequired': false, 'doctors': []}, 'health': {'state': 'none', 'items': []}, 'previousVisits': [],
              'can': {}, 'rooms': [], 'counselors': [],
              'displays': [
                {'id': 41, 'kind': 'questionnaire', 'status': status, 'createdAt': '2026-10-28T10:00:00+09:00'},
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'})),
      ),
    );
    final until = DateTime.now().add(const Duration(minutes: 9, seconds: 42)).toIso8601String();
    await t.pumpWidget(AppScope(
      state: app,
      child: MaterialApp(
        theme: ceramiqueTheme(),
        home: QrShowScreen(requestId: 41, reservationId: 9, qrUrl: fakeUrl, expiresAt: until, poll: const Duration(seconds: 2)),
      ),
    ));
    await binding.convertFlutterSurfaceToImage();
    for (var i = 0; i < 15; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
    await binding.takeScreenshot('W10-$shot-01_qr_screen');
    status = 'opened'; // 고객 폰이 엶 → 한 줄 뒤 닫힘
    for (var i = 0; i < 25; i++) {
      await t.pump(const Duration(milliseconds: 100));
      if (find.text('고객 폰에서 열렸어요').evaluate().isNotEmpty) break;
    }
    await binding.takeScreenshot('W10-$shot-02_qr_opened_closing');
  });
}
