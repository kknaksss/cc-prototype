// 자동 저장(웹 E2E batch 3 #3 ~ #5 와 같은 규칙) · 예약 상세 [저장] · [수정] 없음 · 유입 채널 바로 저장 · 여권 사진 삭제
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/screens/reservation_detail_screen.dart';
import 'package:procedure_app/widgets/autosave.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> detailJson({String memo = '메모', int? photoId = 77, int? funnelId}) => {
      'reservationId': 9, 'day': '2026-10-28', 'start': '2026-10-28T10:00:00+09:00', 'state': {'main': 'reception', 'sub': null},
      'memo': memo,
      'customer': {
        'customerId': 3, 'name': '고객 A', 'isNew': true, 'remark': '주의',
        'personal': {'name': '고객 A', 'passportNumber': 'X1', 'phone': {'countryCode': '82', 'number': '1000000000'}},
        'identity': {'status': 'confirmed', 'kind': 'foreign', 'fields': [], 'complete': true, 'photoId': photoId},
        'funnel': funnelId == null ? null : {'funnelId': funnelId, 'name': '강남언니', 'detail': null},
      },
      'funnelCodes': [
        {'funnelId': 1, 'name': '강남언니'},
        {'funnelId': 2, 'name': '인스타그램'},
      ],
      'reservation': {'sedationRequired': false, 'doctors': []}, 'health': {'state': 'none', 'items': []}, 'previousVisits': [],
      'can': {'editMemo': true, 'editRemark': true, 'editPersonal': true}, 'rooms': [], 'counselors': [],
    };

void main() {
  group('AutoSaveField', () {
    Future<(List<String>, void Function(bool))> pump(WidgetTester t, {String value = 'a'}) async {
      final saved = <String>[];
      var fail = false;
      await t.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Column(children: [
            AutoSaveField(
              value: value,
              label: '메모',
              onSave: (v) async {
                saved.add(v);
                if (fail) throw const ApiError(502, 'kos_unavailable', 'x');
              },
            ),
            const TextField(key: Key('other')),
          ]),
        ),
      ));
      return (saved, (bool f) => fail = f);
    }

    testWidgets('입력 멈춤 1초 뒤 저장 · 「저장됨」 · 같은 값이면 안 부름', (t) async {
      final (saved, _) = await pump(t);
      await t.enterText(find.byType(AutoSaveField), 'ab');
      await t.pump(const Duration(milliseconds: 500));
      expect(saved, isEmpty); // 아직 입력 중
      await t.enterText(find.byType(AutoSaveField), 'abc');
      await t.pump(const Duration(milliseconds: 900));
      expect(saved, isEmpty);
      await t.pump(const Duration(milliseconds: 200)); // 마지막 입력 뒤 1초
      await t.pump();
      expect(saved, ['abc']);
      expect(find.text('저장됨'), findsOneWidget);
      await t.enterText(find.byType(AutoSaveField), 'abc'); // 같은 값
      await t.pump(const Duration(seconds: 2));
      expect(saved, ['abc']);
    });

    testWidgets('칸을 벗어날 때 바로 저장', (t) async {
      final (saved, _) = await pump(t);
      await t.enterText(find.byType(AutoSaveField), 'x');
      await t.tap(find.byKey(const Key('other')));
      await t.pump();
      expect(saved, ['x']);
      await t.pump(const Duration(seconds: 2));
      expect(saved, ['x']); // 1초 타이머가 또 부르지 않음
    });

    testWidgets('실패 = 글자 그대로 · 「저장 못 함 · 다시」 → 누르면 다시', (t) async {
      final (saved, setFail) = await pump(t);
      setFail(true);
      await t.enterText(find.byType(AutoSaveField), 'keep');
      await t.pump(const Duration(seconds: 1));
      await t.pump();
      expect(find.text('저장 못 함 · 다시'), findsOneWidget);
      expect(find.text('keep'), findsOneWidget);
      setFail(false);
      await t.tap(find.text('저장 못 함 · 다시'));
      await t.pump();
      expect(saved, ['keep', 'keep']);
      expect(find.text('저장됨'), findsOneWidget);
    });

    testWidgets('화면을 나갈 때 남은 것 저장', (t) async {
      final (saved, _) = await pump(t);
      await t.enterText(find.byType(AutoSaveField), 'left');
      await t.pumpWidget(const SizedBox()); // 화면 닫힘(1초 전)
      expect(saved, ['left']);
    });

    testWidgets('고치는 중이 아니면 서버 새 값으로(폴링)', (t) async {
      await pump(t, value: 'a');
      await pump(t, value: 'server');
      expect(find.text('server'), findsOneWidget);
    });
  });

  group('예약 상세', () {
    Future<(AppState, List<http.Request>)> pumpDetail(WidgetTester t, {int? photoId = 77}) async {
      SharedPreferences.setMockInitialValues({});
      final reqs = <http.Request>[];
      final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((req) async {
        reqs.add(req);
        if (req.method == 'GET') return http.Response(jsonEncode(detailJson(photoId: photoId)), 200, headers: {'content-type': 'application/json; charset=utf-8'});
        if (req.method == 'DELETE') return http.Response('{"ok":true,"kos":"deleted"}', 200);
        return http.Response('{"ok":true}', 200);
      })));
      t.view.physicalSize = const Size(1179, 2556 * 3);
      t.view.devicePixelRatio = 3;
      await t.pumpWidget(AppScope(state: app, child: const MaterialApp(home: ReservationDetailScreen(reservationId: 9))));
      await t.pumpAndSettle();
      return (app, reqs);
    }

    testWidgets('[저장] · [수정] 없음 · 메모 자동 저장 · 고객 칸 하나만 보냄', (t) async {
      final (app, reqs) = await pumpDetail(t);
      expect(find.text('저장'), findsNothing);
      expect(find.text('수정'), findsNothing);
      await t.enterText(find.byKey(const ValueKey('memo-9')), '새 메모');
      await t.pump(const Duration(milliseconds: 1100));
      await t.pump();
      final memo = reqs.where((r) => r.url.path == '/api/reservations/9/memo').single;
      expect(jsonDecode(memo.body), {'memo': '새 메모'});
      await t.enterText(find.byKey(const ValueKey('personal-3-passportNumber')), 'X2');
      await t.pump(const Duration(milliseconds: 1100));
      await t.pump();
      final personal = reqs.where((r) => r.url.path == '/api/customers/3/personal').single;
      expect(jsonDecode(personal.body), {'personal': {'passportNumber': 'X2'}});
      app.stream.dispose();
      await t.pumpWidget(const SizedBox());
    });

    testWidgets('유입 채널 드롭다운 — 고르면 바로 PUT funnel', (t) async {
      final (app, reqs) = await pumpDetail(t);
      await t.tap(find.byType(DropdownButtonFormField<int?>));
      await t.pumpAndSettle();
      await t.tap(find.text('인스타그램').last);
      await t.pumpAndSettle();
      final f = reqs.where((r) => r.url.path == '/api/customers/3/funnel').single;
      expect(f.method, 'PUT');
      expect(jsonDecode(f.body), {'funnelId': 2});
      app.stream.dispose();
      await t.pumpWidget(const SizedBox());
    });

    testWidgets('여권 사진 [사진 삭제] — 확인 창 → DELETE /api/id-photos/{id} · 사진 없으면 버튼 없음', (t) async {
      final (app, reqs) = await pumpDetail(t);
      await t.tap(find.text('사진 삭제'));
      await t.pumpAndSettle();
      expect(find.text('여권 사진을 지울까요?'), findsOneWidget);
      await t.tap(find.text('삭제'));
      await t.pumpAndSettle();
      expect(reqs.where((r) => r.method == 'DELETE').single.url.path, '/api/id-photos/77');
      expect(app.toaster.text, '사진을 지웠어요 · KOS 사진도 지움');
      await t.pump(const Duration(seconds: 3));
      app.stream.dispose();
      await t.pumpWidget(const SizedBox());
    });

    testWidgets('사진 없음 = [사진 삭제] 없음', (t) async {
      final (app, _) = await pumpDetail(t, photoId: null);
      expect(find.text('사진 삭제'), findsNothing);
      app.stream.dispose();
      await t.pumpWidget(const SizedBox());
    });
  });
}
