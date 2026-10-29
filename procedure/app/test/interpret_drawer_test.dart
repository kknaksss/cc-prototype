// 통역 드로어 높이(SPEC-004 §6.5 · SPEC-007 §10.15 · D9-65 · F9) — 높이 = 놓인 칸 × 0.92 · 상태 표시줄 아래 · 손잡이 보임 ·
// 손잡이 끌어 내림 = 닫힘 · 누름 = 닫힘(회귀) · 폰 · 패드. 로그인 없음 → 마이크 · WS 를 열지 않는다
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/widgets/interpret_drawer.dart';
import 'package:shared_preferences/shared_preferences.dart';

// 닫기는 마이크 · 재생기 플러그인 정리(실제 비동기)를 지난다 — 가짜 시계 + 실제 비동기 틈을 같이 흘린다
Future<void> flow(WidgetTester t) async {
  for (var i = 0; i < 8; i++) {
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
    await t.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const statusBar = 47.0;
  const tabBar = 83.0;

  // 탭바 위 본문 칸(룸 상세 Stack 자리) 안에 드로어 — 칸 높이 = 화면 − 탭바
  Future<List<String?>> pumpDrawer(WidgetTester t, Size screen, {bool tablet = false}) async {
    t.view.physicalSize = screen * 3;
    t.view.devicePixelRatio = 3;
    t.view.padding = const FakeViewPadding(top: statusBar * 3);
    addTearDown(t.view.reset);
    final closed = <String?>[];
    final app = AppState(api: Api(base: () => 'http://x', token: () => null));
    await t.pumpWidget(AppScope(
      state: app,
      child: MaterialApp(
        home: Scaffold(
          body: Column(children: [
            Expanded(
              child: Stack(key: const Key('slot'), children: [
                InterpretDrawer(
                  tablet: tablet,
                  room: '3번 방',
                  customerName: '손님',
                  nationality: null,
                  langCode: 'en',
                  traditional: false,
                  autoCode: 'en',
                  onLang: (_) {},
                  onClose: closed.add,
                ),
              ]),
            ),
            const SizedBox(height: tabBar),
          ]),
        ),
      ),
    ));
    for (var i = 0; i < 6; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
    return closed;
  }

  void expectFits(WidgetTester t) {
    final slot = t.getRect(find.byKey(const Key('slot')));
    final drawer = t.getRect(find.byKey(const Key('interpret-drawer')));
    final handle = t.getRect(find.byKey(const Key('interpret-handle')));
    expect(drawer.height, closeTo((slot.height * 0.92).clamp(0, slot.height - statusBar), 0.5)); // 칸 기준(화면 전체 아님)
    expect(drawer.bottom, closeTo(slot.bottom, 0.5));
    expect(drawer.top, greaterThanOrEqualTo(statusBar)); // 상태 표시줄 아래
    expect(handle.top, greaterThanOrEqualTo(statusBar)); // 손잡이 보임
    expect(handle.bottom, lessThanOrEqualTo(slot.bottom));
    expect(find.textContaining('종료'), findsWidgets); // 머리도 칸 안
  }

  testWidgets('폰(작은 화면 · 탭바 위 칸) — 높이 = 칸 × 0.92 · 머리 · 손잡이가 상태 표시줄 아래에 보임', (t) async {
    await pumpDrawer(t, const Size(375, 667)); // iPhone SE 꼴
    expectFits(t);
  });

  testWidgets('아주 낮은 칸 — 0.92 가 상태 표시줄을 넘으면 상태 표시줄 아래까지만', (t) async {
    await pumpDrawer(t, const Size(375, 420));
    expectFits(t);
    final drawer = t.getRect(find.byKey(const Key('interpret-drawer')));
    expect(drawer.top, closeTo(statusBar, 0.5));
  });

  testWidgets('손잡이 끌어 내림 = 닫힘 · 조금만 끌면 제자리', (t) async {
    final closed = await pumpDrawer(t, const Size(393, 852));
    final before = t.getRect(find.byKey(const Key('interpret-drawer'))).top;
    await t.drag(find.byKey(const Key('interpret-handle')), const Offset(0, 40));
    for (var i = 0; i < 5; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
    expect(closed, isEmpty);
    expect(t.getRect(find.byKey(const Key('interpret-drawer'))).top, closeTo(before, 0.5)); // 제자리
    await t.drag(find.byKey(const Key('interpret-handle')), const Offset(0, 400));
    await flow(t);
    expect(closed, hasLength(1));
  });

  testWidgets('손잡이 누름 = 닫힘(회귀)', (t) async {
    final closed = await pumpDrawer(t, const Size(393, 852));
    await t.tap(find.byKey(const Key('interpret-handle')));
    await flow(t);
    expect(closed, hasLength(1));
  });

  testWidgets('아이패드 — 같은 규칙(칸 × 0.92 · 손잡이 보임) · 끌어 내림 = 닫힘', (t) async {
    final closed = await pumpDrawer(t, const Size(1194, 834), tablet: true);
    expectFits(t);
    await t.drag(find.byKey(const Key('interpret-handle')), const Offset(0, 400));
    await flow(t);
    expect(closed, hasLength(1));
  });
}
