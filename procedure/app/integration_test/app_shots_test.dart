// WORK-009 앱 스크린샷 순회(SPEC-004 §8.7) — 4탭 · 설정 · 알림(+ WP 마다 늘림)
// flutter drive --driver=test_driver/integration_test.dart --target=integration_test/app_shots_test.dart \
//   -d <시뮬레이터> --dart-define=API_BASE=http://localhost:<임시 포트> --dart-define=WP=APP1 --dart-define=SHOT=phone|tablet
//   --dart-define=LOGIN_ID=<아이디> --dart-define=LOGIN_PW=<비밀번호>(값은 레포에 쓰지 않는다) · SHOT_DIR=<저장 폴더>
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/main.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/scan/scan_channel.dart';
import 'package:procedure_app/screens/launchers.dart';
import 'package:procedure_app/screens/scan_screen.dart';
import 'package:procedure_app/widgets/resv_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

const wp = String.fromEnvironment('WP', defaultValue: 'APP1');
const shot = String.fromEnvironment('SHOT', defaultValue: 'phone');
const loginId = String.fromEnvironment('LOGIN_ID');
const loginPw = String.fromEnvironment('LOGIN_PW');
// 1 = 실제 푸시 채널(알림 권한 창이 뜬다 · 미리 허용해 둔 시뮬레이터에서만) · 그 밖 = 채널 없음(권한 창 없이 찍기)
const realPush = bool.fromEnvironment('PUSH');

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

  var n = 0;
  Future<void> take(String name) async {
    n++;
    await binding.takeScreenshot('$wp-$shot-${n.toString().padLeft(2, '0')}_$name');
  }

  Future<void> tab(WidgetTester t, String name) async {
    await t.tap(find.text(name).last);
    await settle(t, 1500);
  }

  testWidgets('shots $wp', (t) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    await const FlutterSecureStorage().deleteAll();
    final state = AppState(push: realPush ? null : PushChannel(const MethodChannel('shots/no-push')));
    await t.pumpWidget(ProcedureApp(state: state));
    await state.boot();
    await binding.convertFlutterSurfaceToImage();

    await wait(t, find.byKey(const Key('login-id')));
    await settle(t);
    if (wp == 'APP1') await take('login');
    await t.enterText(find.byKey(const Key('login-id')), loginId);
    await t.enterText(find.byKey(const Key('login-password')), loginPw);
    await t.tap(find.text('로그인'));
    await wait(t, find.text('설정'));
    await settle(t, 2500);
    // E2E batch 2 #3 — 이름 창 없음 · 설정 「기기 이름」 = 기종 이름 자동
    if (wp == 'B2') {
      await take('after_login_no_name_sheet');
      await tab(t, '설정');
      await take('settings_model_name');
      return;
    }

    if (wp == 'APP1') {
      await take('tab_reservations');
      await tab(t, '내원 현황');
      await take('tab_visits');
      await tab(t, '시술 현황');
      await take('tab_board');
      await tab(t, '설정');
      await take('tab_settings');
      await t.tap(find.bySemanticsLabel(RegExp('^알림')).first);
      await settle(t, 1500);
      await take('notifications');
    }

    if (wp == 'APP3') {
      // 예약 현황(지금 시각 스크롤) → 상세 접수 전 · 시술실 시트 / 내원 현황 → 상세 접수 뒤 · 귀가 대기 정산
      await take('reservations');
      await t.tap(find.byType(ResvCardTile).hitTestable().first);
      await settle(t, 2000);
      await take('detail_before');
      final room = find.text('시술실 선택');
      if (room.evaluate().isNotEmpty) {
        await t.scrollUntilVisible(room, 300, scrollable: find.byType(Scrollable).last);
        await settle(t, 400);
        await take('detail_reception');
        await t.tap(room);
        await settle(t, 1000);
        await take('room_sheet');
        await t.tapAt(const Offset(20, 100));
        await settle(t, 800);
      }
      await t.tap(find.text('‹ 목록'));
      await settle(t, 800);
      await tab(t, '내원 현황');
      await take('visits');
      await t.tap(find.byType(ClinicCard).hitTestable().first);
      await settle(t, 2000);
      await take('detail_after');
      final person = find.text('고객 기본 정보');
      await t.scrollUntilVisible(person, 300, scrollable: find.byType(Scrollable).last);
      await settle(t, 400);
      await take('detail_info');
      await t.tap(find.text('‹ 목록'));
      await settle(t, 800);
      await t.tap(find.textContaining('귀가 대기').first);
      await settle(t, 800);
      if (find.byType(ClinicCard).evaluate().isNotEmpty) {
        await t.tap(find.byType(ClinicCard).hitTestable().first);
        await settle(t, 2000);
        final pay = find.text('전체 금액');
        if (pay.evaluate().isNotEmpty) await t.scrollUntilVisible(pay.last, -200, scrollable: find.byType(Scrollable).last);
        await settle(t, 400);
        await take('detail_home');
      }
    }

    if (wp == 'APP4') {
      // 종 배지 → 알림 목록(원장 호출 · 상담사 호출 둘만) → 상담사 호출 누름 → 예약 현황 탭 그 예약 상세
      await take('badge');
      await t.tap(find.bySemanticsLabel(RegExp('^알림')).first);
      await settle(t, 1500);
      await take('notifications');
      await t.tap(find.text('상담사 호출').first);
      await settle(t, 2500);
      await take('counselor_open_detail');
      await t.tap(find.text('‹ 목록'));
      await settle(t, 800);
      await take('after_read_badge');
    }

    if (wp == 'APP5') {
      // 예약 상세 [이 기기에서 열기] → 문진(언어 3가지 · 기본 정보 · 4쪽 · 동의 · 제출 · 감사 · 잠긴 대기) → [직원] 길게 → 비밀번호 → 나감
      await t.tap(find.byType(ResvCardTile).hitTestable().first);
      await settle(t, 2000);
      final here = find.text('이 기기에서 열기');
      await t.scrollUntilVisible(here, 300, scrollable: find.byType(Scrollable).last);
      await t.drag(find.byType(Scrollable).last, const Offset(0, 250));
      await settle(t, 600);
      await t.tap(here.hitTestable());
      await settle(t, 2000);
      await take('q_start_ja');
      await t.tap(find.text('한국어'));
      await settle(t, 400);
      await take('q_start_ko');
      await t.scrollUntilVisible(find.text('English'), 120, scrollable: find.byType(Scrollable).first);
      await settle(t, 600);
      await t.tap(find.text('English').hitTestable());
      await settle(t, 400);
      await take('q_start_en');
      await t.tap(find.text('Start'));
      await settle(t, 800);
      await take('q_basic');
      await t.tap(find.text('Next'));
      await settle(t, 800);
      // 쪽마다 첫 선택지(SELECT/CHECK) · 이메일 칸은 지어낸 주소
      for (var i = 0; i < 4; i++) {
        final input = find.byType(TextField);
        if (input.evaluate().isNotEmpty) await t.enterText(input.first, 'test@example.com');
        for (final w in find.byIcon(Icons.radio_button_off_rounded).evaluate().toList()) {
          await t.tap(find.byWidget(w.widget).first, warnIfMissed: false);
          await t.pump(const Duration(milliseconds: 100));
        }
        await settle(t, 400);
        await take('q_page${i + 1}');
        await t.tap(find.text('Next'));
        await settle(t, 800);
      }
      await t.tap(find.byIcon(Icons.check_box_outline_blank_rounded).first);
      await settle(t, 400);
      await take('q_agree');
      await t.tap(find.text('Submit'));
      await settle(t, 1500);
      await take('q_thanks');
      await settle(t, 3500);
      await take('q_waiting_locked');
      final g = await t.startGesture(t.getCenter(find.text('직원')));
      await t.pump(const Duration(milliseconds: 1700));
      await g.up();
      await settle(t, 800);
      await t.enterText(find.byKey(const Key('unlock-password')), 'not-the-password');
      await t.tap(find.text('나가기'));
      await settle(t, 1500);
      await take('q_unlock_wrong');
      await t.enterText(find.byKey(const Key('unlock-password')), loginPw);
      await t.tap(find.text('나가기'));
      await settle(t, 1500);
      await take('q_exit');
    }

    if (wp == 'APP6') {
      // 시험 스위치 — 시뮬레이터가 카메라 「있음」으로 열려 시스템 카메라 화면에서 멈추므로, 카메라 없는 채널로 스캔 화면을 연다(앱 코드 그대로)
      openPassportScan = (ctx, d, {displayRequestId}) => Navigator.of(ctx, rootNavigator: true).push(MaterialPageRoute(
          builder: (_) => ScanScreen(detail: d, displayRequestId: displayRequestId, channel: const ScanChannel(MethodChannel('shots/no-camera')))));
      // 예약 상세 [여권 스캔] → 시뮬레이터 = 카메라 없음 → [손으로 입력] → 확인(KOS 값 나란히 · 다른 칸 강조) → [저장](가짜 판 = 403 → 「저장하지 못했어요」)
      await t.tap(find.byType(ResvCardTile).hitTestable().first);
      await settle(t, 2000);
      await t.tap(find.text('여권 스캔').hitTestable().first);
      await settle(t, 1500);
      await take('scan_no_camera');
      await t.tap(find.text('손으로 입력'));
      await settle(t, 800);
      await take('scan_manual_empty');
      // 지어낸 값
      await t.enterText(find.byKey(const Key('scan-passportSurname')), 'TEST');
      await t.enterText(find.byKey(const Key('scan-passportGivenNames')), 'SAMPLE PERSON');
      await t.enterText(find.byKey(const Key('scan-passportNumber')), 'TK0000001');
      await t.enterText(find.byKey(const Key('scan-passportExpiryDate')), '2033-01-01');
      FocusManager.instance.primaryFocus?.unfocus();
      await settle(t, 800);
      await take('scan_manual_filled');
      await t.tap(find.text('저장'));
      await settle(t, 2000);
      await take('scan_save_result');
    }

    if (wp == 'APP2') {
      // 시술 현황 — 2계층 배지 · 발음 · 필터 점 · 배열 순서 / 룸 상세 — 부상태 칩 · 되돌리기 아이콘 · 확인 시트
      await tab(t, '시술 현황');
      await take('board');
      await t.tap(find.textContaining('A-룸3').first);
      await settle(t, 1500);
      await take('room_doing');
      await t.tap(find.bySemanticsLabel('되돌리기').first);
      await settle(t, 1000);
      await take('undo_confirm');
      await t.tap(find.text('취소').last);
      await settle(t, 800);
      await t.tap(find.text('← 현황').first);
      await settle(t, 800);
      await t.tap(find.textContaining('A-룸4').first);
      await settle(t, 1500);
      await take('room_done');
    }
  });
}
