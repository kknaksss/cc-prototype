// WORK-010 WP-APP — 실제 back(임시 포트)으로 한 번: 다른 기기가 [태블릿에 띄우기](이 기기) → SSE display → QR 화면 →
// 데스크 브라우저가 링크를 엶(공개 GET) → 5초 폴링에서 opened → 「고객 폰에서 열렸어요」 → 저절로 닫힘 / [이 기기에 QR 보이기] → QR 화면
// flutter drive --driver=test_driver/integration_test.dart --target=integration_test/qweb_e2e_test.dart -d <시뮬레이터>
//   --dart-define=API_BASE=http://localhost:<임시 포트> --dart-define=LOGIN_ID=… --dart-define=LOGIN_PW=…(값은 레포에 쓰지 않는다)
// 토큰 · 링크는 로그 · 파일 이름에 쓰지 않는다(SPEC-006 §7.5) — 스크린샷의 QR 은 저장 뒤 가린다
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:integration_test/integration_test.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/main.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/screens/qr_show_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

const loginId = String.fromEnvironment('LOGIN_ID');
const loginPw = String.fromEnvironment('LOGIN_PW');

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  Future<void> until(WidgetTester t, bool Function() ok, {int seconds = 20, String what = ''}) async {
    for (var i = 0; i < seconds * 10; i++) {
      await t.pump(const Duration(milliseconds: 100));
      if (ok()) return;
    }
    throw TestFailure('안 됨: $what');
  }

  testWidgets('qweb e2e', (t) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    await const FlutterSecureStorage().deleteAll();
    final state = AppState(push: PushChannel(const MethodChannel('qweb/no-push')));
    await t.pumpWidget(ProcedureApp(state: state));
    await state.boot();
    await binding.convertFlutterSurfaceToImage();
    await until(t, () => find.byKey(const Key('login-id')).evaluate().isNotEmpty, what: '로그인 화면');
    await t.enterText(find.byKey(const Key('login-id')), loginId);
    await t.enterText(find.byKey(const Key('login-password')), loginPw);
    await t.tap(find.text('로그인'));
    await until(t, () => state.phase == Phase.loggedIn, what: '로그인');

    // 이 기기 행 — 시뮬레이터는 APNs 토큰이 없어 앱의 토큰 받기 길(onToken)에 지어낸 16진 값을 넣는다
    state.push.onToken!('5c7a7c7a5c7a7c7a5c7a7c7a5c7a7c7a5c7a7c7a5c7a7c7a5c7a7c7a5c7a7c7a');
    await until(t, () => state.deviceId != null && state.stream.connected, what: '기기 등록 · SSE');
    await t.pump(const Duration(seconds: 2)); // deviceId 를 실은 SSE 로 다시 붙음

    // 데스크(다른 로그인) — [태블릿에 띄우기] 에서 이 기기를 고른 것과 같은 요청
    final desk = await Api(base: () => state.server.base, token: () => null).login(loginId, loginPw);
    final deskApi = Api(base: () => state.server.base, token: () => desk.token);
    final made = await deskApi.createDisplay(1, 'questionnaire', deviceId: state.deviceId);
    final url = made['qrUrl'] as String;
    expect(made['qrToken'], isNull);
    await until(t, () => find.byType(QrShowScreen).evaluate().isNotEmpty, what: 'SSE → QR 화면');
    await until(t, () => find.bySemanticsLabel('문진 QR').evaluate().isNotEmpty, what: 'QR 그림');
    expect(find.textContaining('남은 시간'), findsOneWidget); // SSE 로 열어도 만료 시각(pending 응답)
    for (var i = 0; i < 15; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
    await binding.takeScreenshot('W10E-phone-01_sse_qr_screen');

    // 데스크 브라우저가 그 링크를 엶 = 공개 GET(토큰은 fragment → 헤더)
    final token = Uri.parse(url).fragment;
    final r = await http.get(Uri.parse('${state.server.base}/api/public/questionnaire'), headers: {'X-Questionnaire-Token': token});
    expect(r.statusCode, 200);
    await until(t, () => find.text('고객 폰에서 열렸어요').evaluate().isNotEmpty, seconds: 12, what: '폴링 → opened');
    await t.pump(const Duration(milliseconds: 300));
    await binding.takeScreenshot('W10E-phone-02_opened_closing');
    await until(t, () => find.byType(QrShowScreen).evaluate().isEmpty, seconds: 5, what: '저절로 닫힘');
    final detail = jsonDecode(utf8.decode((await http.get(Uri.parse('${state.server.base}/api/reservations/1'),
            headers: {'Authorization': 'Bearer ${desk.token}'}))
        .bodyBytes)) as Map;
    expect(((detail['displays'] as List).firstWhere((x) => x['id'] == made['id']) as Map)['status'], 'opened');

    // [이 기기에 QR 보이기] — 예약 1 상세(가짜 판) → 버튼 → 응답 qrUrl 로 QR 화면 · [닫기] = 화면만
    state.openReservation.value = 1;
    await until(t, () => find.text('이 기기에 QR 보이기').evaluate().isNotEmpty, what: '예약 상세');
    await t.ensureVisible(find.text('이 기기에 QR 보이기'));
    await t.pump(const Duration(milliseconds: 400));
    await t.tap(find.text('이 기기에 QR 보이기'));
    await until(t, () => find.bySemanticsLabel('문진 QR').evaluate().isNotEmpty, what: '이 기기 QR');
    expect(find.textContaining('남은 시간'), findsOneWidget);
    for (var i = 0; i < 15; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
    await binding.takeScreenshot('W10E-phone-03_here_qr_screen');
    await t.tap(find.text('닫기'));
    await until(t, () => find.byType(QrShowScreen).evaluate().isEmpty, what: '[닫기]');
    await t.pump(const Duration(seconds: 1));
    final after = jsonDecode(utf8.decode((await http.get(Uri.parse('${state.server.base}/api/reservations/1'),
            headers: {'Authorization': 'Bearer ${desk.token}'}))
        .bodyBytes)) as Map;
    final list = (after['displays'] as List).cast<Map>()..sort((a, b) => (b['id'] as int).compareTo(a['id'] as int));
    final first = list.first; // 방금 만든 것
    expect(first['status'], 'pending'); // [닫기] = 화면만 — 요청 그대로
    expect(first['deviceName'], isNull); // 이 기기 QR = deviceId 없이
    await binding.takeScreenshot('W10E-phone-04_detail_after_close');
  });
}
