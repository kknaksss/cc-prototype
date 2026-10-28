// 헤더 한 줄(2026-10-28 사용자) — [Céramique][메뉴명][알림] · 폰 · 태블릿 같음 · 시술 현황 「확인 N」 · 시계는 본문 첫 줄
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/screens/reservation_detail_screen.dart';
import 'package:procedure_app/screens/shell.dart';
import 'package:procedure_app/widgets/header.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  for (final (name, size) in [('폰', const Size(1179, 2556)), ('태블릿', const Size(2420, 1668))]) {
    testWidgets('$name — Céramique 왼쪽 · 탭 이름 가운데 · 종 오른쪽 한 줄(높이 headerHeight) · 큰 제목 줄 없음', (t) async {
      SharedPreferences.setMockInitialValues({});
      final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((_) async => http.Response('{}', 200))));
      app.unread.value = 3;
      t.view.physicalSize = size;
      t.view.devicePixelRatio = 2;
      await t.pumpWidget(AppScope(state: app, child: const MaterialApp(home: TabScaffold(tab: AppTab.visits, body: SizedBox()))));
      final title = t.getRect(find.text('내원 현황'));
      final brand = t.getRect(find.text('Céramique'));
      final bell = t.getRect(find.byType(Bell));
      expect(t.getSize(find.byType(AppHeader)).height, headerHeight);
      expect((title.center.dy - brand.center.dy).abs(), lessThan(2)); // 한 줄
      expect((bell.center.dy - brand.center.dy).abs(), lessThan(2));
      expect(brand.right, lessThan(title.left)); // Céramique 왼쪽
      expect(bell.left, greaterThan(title.right)); // 종 오른쪽
      expect((title.center.dx - t.view.physicalSize.width / 2 / 2).abs(), lessThan(2)); // 메뉴명 가운데
      expect(find.text('3'), findsOneWidget); // 안 읽은 수
      app.stream.dispose();
    });
  }

  testWidgets('예약 상세 — 흰 머리 [‹ 들어온 탭] 「예약 상세」 정가운데 · 상태 제목 · 시각 없음 · 공통 머리 높이', (t) async {
    SharedPreferences.setMockInitialValues({});
    final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((_) async {
      await Future<void>.delayed(const Duration(seconds: 30));
      return http.Response('{}', 500);
    })));
    t.view.physicalSize = const Size(1179, 2556);
    t.view.devicePixelRatio = 3;
    await t.pumpWidget(AppScope(state: app, child: const MaterialApp(home: ReservationDetailScreen(reservationId: 9, back: '내원 현황'))));
    await t.pump();
    expect(find.text('예약 상세'), findsOneWidget);
    expect(find.text('내원 현황'), findsOneWidget); // 뒤로 = 들어온 탭
    expect(find.text('접수 전'), findsNothing);
    final title = t.getRect(find.byKey(const Key('detail-title')));
    expect((title.center.dx - 1179 / 3 / 2).abs(), lessThan(1)); // 화면 정가운데(왼쪽 버튼 폭과 상관없이)
    expect(t.getSize(find.byType(DetailHeader)).height, headerHeight);
    await t.pumpWidget(const SizedBox());
    await t.pump(const Duration(seconds: 31));
    app.stream.dispose();
  });
}
