// 문진(SPEC-004 §6.15 · §8.7) — 잠금(뒤로 막힘 · 대기 화면도) · 언어 칩 · 제출 본문 · unlock 429 문구
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/questionnaire.dart';
import 'package:procedure_app/screens/questionnaire_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> tr(String ko, String ja, String en) => {
      'title': {'translation': {'ko': ko, 'ja': ja, 'zh-Hans': ko, 'zh-Hant': ko, 'en': en, 'id': en}}
    };

final formJson = {
  'reservationId': 9,
  'customerName': '고객 A',
  'language': {'code': 'ja', 'source': 'nationality', 'options': ['ko', 'ja', 'zh-Hans', 'zh-Hant', 'en', 'id']},
  'form': {
    'pages': [
      {'id': 'p1', 'title': '건강', 'translsMap': tr('건강', '健康', 'Health'), 'questions': [
        {'id': '9', 'title': '알레르기', 'translsMap': tr('알레르기', 'アレルギー', 'Allergy'), 'answers': [
          {'id': '1', 'title': '없음', 'inputType': 'SELECT_BOX', 'isSubText': false, 'translsMap': tr('없음', 'なし', 'None')},
          {'id': '2', 'title': '있음', 'inputType': 'SELECT_BOX', 'isSubText': true, 'translsMap': tr('있음', 'あり', 'Yes')},
        ]},
        {'id': '6', 'title': '이메일', 'answers': [{'id': '3', 'title': '', 'inputType': 'INPUT_BOX', 'isSubText': false, 'translsMap': {}}]},
      ]},
    ],
  },
  'agreements': [
    {'id': 'ag-1', 'title': '개인정보 동의', 'required': true, 'type': 'PERSONAL_INFORMATION', 'translsMap': {'title': {'translation': {'ja': '同意', 'en': 'Agree', 'zh': '同意'}}}},
  ],
  'prefill': {'name': '고객 A', 'phone': {'countryCode': '81', 'phoneNumber': '0000000000'}, 'address': '', 'addressDetail': '', 'dateOfBirth': '19900101', 'gender': 'FEMALE'},
  'todaySubmitted': false,
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('제출 answers — 고른 선택지 한 줄씩 · 키 7개 · title 원문 · subText · inputText', () {
    final f = QForm.fromJson(formJson);
    final q = f.pages.single.questions.first;
    final a = QAnswers()..toggle(q, q.answers[1]);
    a.text['2'] = '꽃가루';
    a.text['3'] = 'test@example.com';
    final out = a.toJson(f.pages);
    expect(out.length, 2);
    expect(out.first.keys.toSet(), {'parentQuestionId', 'parentQuestionTitle', 'id', 'title', 'inputType', 'inputText', 'subText'});
    expect(out.first['parentQuestionTitle'], '알레르기'); // 원문(한국어)
    expect(out.first['title'], '있음');
    expect(out.first['subText'], '꽃가루');
    expect(out.last['inputText'], 'test@example.com');
    // SELECT_BOX = 하나만 — 다른 것을 고르면 바뀜
    a.toggle(q, q.answers[0]);
    expect(a.picked['9'], {'1'});
    expect(q.label('ja'), 'アレルギー');
    expect(agreementLang('zh-Hant'), 'zh');
    expect(agreementLang('ko'), '');
  });

  Future<(AppState, List<http.Request>)> pump(WidgetTester t, {int unlockStatus = 200}) async {
    SharedPreferences.setMockInitialValues({});
    final reqs = <http.Request>[];
    final api = Api(
      base: () => 'http://x',
      token: () => 't',
      client: MockClient((req) async {
        reqs.add(req);
        if (req.url.path == '/api/auth/unlock' && unlockStatus != 200) {
          return http.Response(jsonEncode({'error': {'code': 'too_many_attempts', 'message': '여러 번 틀렸어요. 1분 뒤 다시 시도해 주세요'}}), unlockStatus,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        if (req.url.path.startsWith('/api/questionnaires') && req.method == 'GET') {
          return http.Response(jsonEncode(formJson), 200, headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response('{"ok":true}', 200);
      }),
    );
    final app = AppState(api: api);
    t.view.physicalSize = const Size(1179, 2556);
    t.view.devicePixelRatio = 3;
    await t.pumpWidget(AppScope(
      state: app,
      child: MaterialApp(home: Builder(builder: (c) => Scaffold(body: Center(child: TextButton(onPressed: () => showQuestionnaire(c, 9, displayRequestId: 4), child: const Text('open')))))),
    ));
    await t.tap(find.text('open'));
    await t.pumpAndSettle();
    return (app, reqs);
  }

  testWidgets('잠금 — 뒤로 가기 막힘 · 언어 칩 바꾸면 받은 번역 안에서 바뀜(다시 부르지 않음)', (t) async {
    final (app, reqs) = await pump(t);
    expect(find.text('고객 A 様'), findsOneWidget); // back 이 정한 ja
    final gets = reqs.where((r) => r.method == 'GET').length;
    await t.scrollUntilVisible(find.text('English'), 120, scrollable: find.byType(Scrollable).first);
    await t.tap(find.text('English'));
    await t.pump();
    expect(find.text('Hello, 고객 A'), findsOneWidget);
    expect(reqs.where((r) => r.method == 'GET').length, gets);
    expect(app.toaster.muted, isTrue); // 앱 안 배너 끔
    // 뒤로 가기(시스템) — 그대로 남는다
    final nav = t.state<NavigatorState>(find.byType(Navigator).first);
    await nav.maybePop();
    await t.pumpAndSettle();
    expect(find.byType(QuestionnaireScreen), findsOneWidget);
    app.stream.dispose();
  });

  testWidgets('제출 → 감사 → 3초 뒤 대기 화면도 잠금 · deviceId · 언어 · yyyyMMdd', (t) async {
    final (app, reqs) = await pump(t);
    await t.tap(find.text('始める'));
    await t.pumpAndSettle();
    await t.tap(find.text('次へ')); // 기본 정보(미리 채움 그대로)
    await t.pumpAndSettle();
    await t.tap(find.text('なし'));
    await t.pump();
    await t.tap(find.text('次へ'));
    await t.pumpAndSettle();
    await t.tap(find.text('同意 (必須)'));
    await t.pump();
    await t.tap(find.text('送信'));
    await t.pumpAndSettle();
    final post = reqs.lastWhere((r) => r.method == 'POST' && r.url.path == '/api/questionnaires/9');
    final body = jsonDecode(post.body) as Map;
    expect(body['language'], 'ja');
    expect(body['dateOfBirth'], '19900101');
    expect(body['displayRequestId'], 4);
    expect(body.containsKey('registrationNumber'), isFalse);
    expect(body.containsKey('phoneticName'), isFalse);
    expect((body['agreements'] as List).single['agreed'], isTrue);
    expect(find.text('ありがとうございました'), findsOneWidget);
    await t.pump(const Duration(seconds: 3));
    await t.pumpAndSettle();
    expect(find.text('しばらくお待ちください'), findsOneWidget);
    final nav = t.state<NavigatorState>(find.byType(Navigator).first);
    await nav.maybePop();
    await t.pumpAndSettle();
    expect(find.byType(QuestionnaireScreen), findsOneWidget); // 대기 화면도 잠금
    app.stream.dispose();
  });

  testWidgets('[직원] 1.5초 길게 → 비밀번호 → unlock 429 문구 그대로', (t) async {
    final (app, reqs) = await pump(t, unlockStatus: 429);
    await t.longPress(find.text('직원')); // 짧게(0.5초)는 안 열림
    await t.pump();
    expect(find.text('직원 확인'), findsNothing);
    final g = await t.startGesture(t.getCenter(find.text('직원')));
    await t.pump(const Duration(milliseconds: 1600));
    await g.up();
    await t.pumpAndSettle();
    expect(find.text('직원 확인'), findsOneWidget);
    await t.enterText(find.byKey(const Key('unlock-password')), 'wrong');
    await t.tap(find.text('나가기'));
    await t.pumpAndSettle();
    expect(find.text('여러 번 틀렸어요. 1분 뒤 다시 시도해 주세요'), findsOneWidget);
    expect(find.byType(QuestionnaireScreen), findsOneWidget);
    expect(reqs.any((r) => r.url.path == '/api/auth/unlock'), isTrue);
    app.stream.dispose();
  });
}
