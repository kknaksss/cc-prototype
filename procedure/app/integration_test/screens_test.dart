// 화면 스크린샷 순회(SPEC-004 §8.2) — 로그인 · 목록 · 룸 상세 · 호출 시트 · 통역 드로어
// flutter drive --driver=test_driver/integration_test.dart --target=integration_test/screens_test.dart \
//   -d <시뮬레이터> --dart-define=API_BASE=http://localhost:8700 --dart-define=SCENE=board|interpret --dart-define=SHOT=phone|tablet
//   --dart-define=LOGIN_ID=<아이디> --dart-define=LOGIN_PW=<비밀번호>(값은 레포에 쓰지 않는다)
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/main.dart';
import 'package:procedure_app/screens/board_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

const scene = String.fromEnvironment('SCENE', defaultValue: 'board');
const shot = String.fromEnvironment('SHOT', defaultValue: 'phone');
const loginId = String.fromEnvironment('LOGIN_ID');
const loginPw = String.fromEnvironment('LOGIN_PW');
const role = String.fromEnvironment('ROLE', defaultValue: 'nurse');

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  Future<void> wait(WidgetTester t, Finder f, {int seconds = 20}) async {
    for (var i = 0; i < seconds * 10; i++) {
      await t.pump(const Duration(milliseconds: 100));
      if (f.evaluate().isNotEmpty) return;
    }
    throw TestFailure('안 보임: $f');
  }

  Future<void> settle(WidgetTester t, [int ms = 1200]) async {
    for (var i = 0; i < ms ~/ 100; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
  }

  Future<void> take(String name) async {
    await binding.takeScreenshot('${shot}_$name');
  }

  testWidgets('screens $scene', (t) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    await const FlutterSecureStorage().deleteAll();
    final state = AppState();
    await t.pumpWidget(ProcedureApp(state: state));
    await state.boot();
    await binding.convertFlutterSurfaceToImage();

    await wait(t, find.byKey(const Key('login-id')));
    await settle(t);
    await take('01_login_$scene');

    await t.enterText(find.byKey(const Key('login-id')), loginId);
    await t.enterText(find.byKey(const Key('login-password')), loginPw);
    await t.tap(find.text('로그인'));
    await wait(t, find.byType(RoomCard));
    await settle(t, 2000);
    await take('02_list_${scene}_$role');

    if (scene == 'board') {
      // 호출 상자가 있는 카드 → 룸 상세
      await t.tap(find.byType(RoomCard).at(1));
      await wait(t, find.text('← 현황'));
      await settle(t);
      await take('03_room_call');
      await t.tap(find.text('← 현황'));
      await settle(t, 800);
      // 진행 중 카드
      await t.tap(find.byType(RoomCard).first);
      await wait(t, find.text('← 현황'));
      await settle(t);
      await take('04_room');
      final callBtn = find.text('의사 호출');
      await t.scrollUntilVisible(callBtn, 200, scrollable: find.byType(Scrollable).at(shot == 'tablet' ? 1 : 0));
      await t.tap(callBtn);
      await settle(t);
      await take('05_call_sheet');
      final pickable = find.textContaining('비어있음');
      if (pickable.evaluate().isNotEmpty) await t.tap(pickable.first);
      await settle(t, 600);
      await take('06_call_sheet_picked');
      await t.tap(find.text('취소'));
      await settle(t, 800);
    } else {
      await t.tap(find.byType(RoomCard).first);
      await wait(t, find.text('통역하기'));
      await settle(t);
      await take('03_room_$role');
      await t.tap(find.text('통역하기'));
      await wait(t, find.text('듣는 중'), seconds: 30);
      await settle(t, 1500);
      await take('07_drawer_listening');
      // 이 사이에 맥 스피커로 한 마디(검증 스크립트가 SAY_NOW 를 보고 읽는다)
      debugPrint('SAY_NOW');
      await settle(t, 25000);
      await take('08_drawer_talk');
      await t.tap(find.text(shot == 'tablet' ? '통역 종료' : '종료'));
      await settle(t, 1500);
      await take('09_after_drawer');
    }
  });
}
