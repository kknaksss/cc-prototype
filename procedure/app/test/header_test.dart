// 헤더 한 줄(2026-10-28 사용자) — [메뉴명][Céramique][알림] · 폰 · 태블릿 같음 · 시술 현황 「확인 N」 · 시계는 본문 첫 줄
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/screens/shell.dart';
import 'package:procedure_app/widgets/header.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  for (final (name, size) in [('폰', const Size(1179, 2556)), ('태블릿', const Size(2420, 1668))]) {
    testWidgets('$name — 탭 이름 · Céramique · 종이 한 줄(같은 높이 56) · 큰 제목 줄 없음', (t) async {
      SharedPreferences.setMockInitialValues({});
      final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((_) async => http.Response('{}', 200))));
      app.unread.value = 3;
      t.view.physicalSize = size;
      t.view.devicePixelRatio = 2;
      await t.pumpWidget(AppScope(state: app, child: const MaterialApp(home: TabScaffold(tab: AppTab.visits, body: SizedBox()))));
      final title = t.getRect(find.text('내원 현황'));
      final brand = t.getRect(find.text('Céramique'));
      final bell = t.getRect(find.byType(Bell));
      expect(t.getSize(find.byType(AppHeader)).height, 56);
      expect((title.center.dy - brand.center.dy).abs(), lessThan(2)); // 한 줄
      expect((bell.center.dy - brand.center.dy).abs(), lessThan(2));
      expect(title.left, lessThan(brand.left));
      expect(bell.left, greaterThan(brand.right));
      expect((brand.center.dx - t.view.physicalSize.width / 2 / 2).abs(), lessThan(2)); // 가운데
      expect(find.text('3'), findsOneWidget); // 안 읽은 수
      app.stream.dispose();
    });
  }
}
