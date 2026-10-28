// 「띄우기 실기기 안 열림」 확인(2026-10-28) — 임시 back · 시뮬레이터. 진행은 print 「E2E …」 줄로 셸과 맞춘다(토큰 · 링크는 출력 안 함)
// 시뮬레이터는 알림 허용을 명령으로 줄 수 없다 → 기기 등록은 앱의 토큰 길(onToken)에 지어낸 토큰 · 앞 푸시는 네이티브 willPresent 가
// 보내는 채널 메시지(onForeground)를 그대로 넣는다. 데스크 = 다른 로그인으로 띄우기를 만든다([태블릿에 띄우기]에서 이 기기를 고른 것과 같음)
// PHASE=fg   : ① 앞 · SSE 끊김 → 푸시만(onForeground) → QR 화면  ② 셸이 다른 앱을 띄워 뒤로 → 띄우기 → 셸이 이 앱을 앞으로 → QR 화면
// PHASE=cold : 저장된 로그인으로 콜드 스타트 — 셸이 시작 전에 기기 행을 다른 계정으로 돌려 둠(= 시작 때 SSE 가 저장된 deviceId 로 열려도
//              back 이 이 계정 기기로 못 알아봄 · 실기기 빌드 8 업데이트 뒤 상태) → 등록 뒤 다시 붙어 ③ SSE 로 QR 화면이 열리나

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/main.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/screens/qr_show_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

const phase = String.fromEnvironment('PHASE', defaultValue: 'fg');
const loginId = String.fromEnvironment('LOGIN_ID');
const loginPw = String.fromEnvironment('LOGIN_PW');
const ch = MethodChannel('e2e/push'); // 알림 권한 창 없이
const _token = 'e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0e2e0'; // 지어낸 기기 토큰

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  Future<void> until(WidgetTester t, bool Function() ok, {int seconds = 60, String what = ''}) async {
    for (var i = 0; i < seconds * 10; i++) {
      await t.pump(const Duration(milliseconds: 100));
      if (ok()) return;
    }
    throw TestFailure('안 됨: $what');
  }

  bool qr() => find.byType(QrShowScreen).evaluate().isNotEmpty;

  Future<void> closeQr(WidgetTester t) async {
    for (var n = 0; n < 5 && qr(); n++) {
      await t.tap(find.text('닫기').last);
      await t.pump(const Duration(seconds: 2)); // 차례에 다른 요청이 있으면 이어서 열린다
    }
    await until(t, () => !qr(), what: 'QR 닫기');
  }

  Future<int> desk(AppState state, int reservationId) async {
    final s = await Api(base: () => state.server.base, token: () => null).login(loginId, loginPw);
    final api = Api(base: () => state.server.base, token: () => s.token);
    final r = await api.createDisplay(reservationId, 'questionnaire', deviceId: state.deviceId);
    return (r['id'] as num).toInt();
  }

  testWidgets('display push $phase', (t) async {
    if (phase == 'fg') {
      await (await SharedPreferences.getInstance()).clear();
      await const FlutterSecureStorage().deleteAll();
    }
    late final AppState state;
    if (phase == 'cold') {
      // 실기기처럼 알림 허용 상태(시뮬레이터는 명령으로 못 줌) · register = iOS 가 토큰을 돌려줌(onToken) — 시작 때 등록 길을 탄다.
      // (flutter drive 는 다시 설치해 SharedPreferences 가 비고 키체인 로그인만 남는다 — 저장된 토큰 없이 시작하는 길)
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (c) async {
        if (c.method == 'status') return 'authorized';
        if (c.method == 'register') Future<void>.delayed(const Duration(milliseconds: 300), () => state.push.onToken!(_token));
        return null;
      });
    }
    state = AppState(push: PushChannel(ch));
    await t.pumpWidget(ProcedureApp(state: state));
    await state.boot();
    await binding.convertFlutterSurfaceToImage();

    if (phase == 'fg') {
      await until(t, () => find.byKey(const Key('login-id')).evaluate().isNotEmpty, what: '로그인 화면');
      await t.enterText(find.byKey(const Key('login-id')), loginId);
      await t.enterText(find.byKey(const Key('login-password')), loginPw);
      await t.tap(find.text('로그인'));
      await until(t, () => state.phase == Phase.loggedIn, what: '로그인');
      state.push.onToken!(_token);
      await until(t, () => state.deviceId != null && state.stream.connected, what: '기기 등록 · SSE');
      await t.pump(const Duration(seconds: 2));

      // ① 앞 · SSE 끊김 — back 은 그 기기 SSE 가 없으니 푸시만 → 앞 푸시(onForeground)로 연다
      state.stream.stop();
      await t.pump(const Duration(seconds: 1));
      final id1 = await desk(state, 1);
      // 네이티브 → Dart 메시지를 그대로(시험 전용 · 앱 코드는 같은 채널 핸들러)
      // ignore: deprecated_member_use
      await ServicesBinding.instance.defaultBinaryMessenger.handlePlatformMessage(
          'e2e/push', const StandardMethodCodec().encodeMethodCall(MethodCall('onForeground', {'kind': 'display', 'requestId': id1})), (_) {});
      await until(t, qr, seconds: 20, what: '① 앞 푸시 → QR 화면');
      await t.pump(const Duration(seconds: 1));
      await binding.takeScreenshot('BUG-phone-01_fg_push_opened');
      await closeQr(t);
      state.stream.start();
      await until(t, () => state.stream.connected, what: 'SSE 다시');

      // ② 뒤 → (그동안 띄우기) → 앞으로
      // 셸: 다른 앱을 띄워 이 앱을 뒤로 → 데스크(curl)가 예약 2 를 이 기기로 띄움(뒤 = SSE 닫힘 → back 은 푸시만 · 시뮬레이터엔 안 옴) → 이 앱을 앞으로
      // ignore: avoid_print
      print('E2E BG-READY deviceId=${state.deviceId}');
      await until(t, qr, seconds: 180, what: '② 앞으로 올 때 QR 화면');
      await t.pump(const Duration(seconds: 1));
      await binding.takeScreenshot('BUG-phone-02_bg_resume_opened');
      await closeQr(t);
      // ignore: avoid_print
      print('E2E FG-DONE deviceId=${state.deviceId}');
    } else {
      // ③ 콜드 스타트(저장된 로그인) — 기기 행이 잠깐 다른 계정이라 시작 SSE 가 기기 없이 붙은 상태에서
      await until(t, () => state.phase == Phase.loggedIn && state.stream.connected, what: '저장된 로그인 · SSE');
      await t.pump(const Duration(seconds: 3)); // 시작 등록 → 다시 붙음
      await until(t, () => state.stream.connected, what: 'SSE 다시');
      await desk(state, 3);
      await until(t, qr, seconds: 20, what: '③ 콜드 스타트 뒤 SSE → QR 화면');
      await t.pump(const Duration(seconds: 1));
      await binding.takeScreenshot('BUG-phone-03_cold_start_sse_opened');
      // ignore: avoid_print
      print('E2E COLD-DONE');
    }
  });
}
