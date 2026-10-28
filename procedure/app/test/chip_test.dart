// 공통 상태 칩(2026-10-28) — 범례 · 필터가 같은 크기 · 고름 = primary · 개수 · 한 줄 가로 스크롤
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/theme/tokens.dart';
import 'package:procedure_app/widgets/resv_ui.dart';

void main() {
  testWidgets('범례 칩 · 필터 칩(고름 · 안 고름 · 점) — 보이는 높이 같음 · 글자 「이름 개수」 · 넘치면 한 줄 스크롤', (t) async {
    var tapped = 0;
    await t.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(
          width: 200,
          child: ChipRow([
            const StatusChip('예약', count: 7, bg: Ms.purple100, fg: Ms.purple, key: Key('legend')),
            StatusChip('전체', count: 5, selected: true, onTap: () => tapped++, key: const Key('on')),
            StatusChip('대기', count: 2, dot: Ms.white, dotRing: Ms.primary, onTap: () => tapped++, key: const Key('off')),
            for (var i = 0; i < 8; i++) StatusChip('칩$i', onTap: () {}),
          ]),
        ),
      ),
    ));
    expect(find.text('예약 7'), findsOneWidget);
    expect(find.text('전체 5'), findsOneWidget);
    double visible(Key k) => t.getSize(find.descendant(of: find.byKey(k), matching: find.byType(Container)).first).height;
    expect(visible(const Key('legend')), visible(const Key('on')));
    expect(visible(const Key('on')), visible(const Key('off')));
    final on = t.widget<Container>(find.descendant(of: find.byKey(const Key('on')), matching: find.byType(Container)).first);
    expect((on.decoration as BoxDecoration).color, Ms.primary100);
    await t.tap(find.byKey(const Key('off')));
    expect(tapped, 1);
    expect(find.byType(SingleChildScrollView), findsOneWidget); // 한 줄 · 가로 스크롤
    expect(t.takeException(), isNull); // 넘쳐도 오류 없음
  });

  testWidgets('ChipRow 위 · 아래 여백은 칩 줄이 정한다(모든 탭 같게 · batch 4 #2) · 좌우만 화면이', (t) async {
    await t.pumpWidget(const MaterialApp(home: Scaffold(body: ChipRow([StatusChip('예약', count: 1)], left: 12, right: 16))));
    final sv = t.widget<SingleChildScrollView>(find.byType(SingleChildScrollView));
    expect(sv.padding, const EdgeInsets.fromLTRB(12, chipRowVertical, 16, chipRowVertical));
  });
}
