// WP-APP6(r4) — 전달 시트([공유] = 앱 안 전달 · SPEC-007 §10.14 · D9-62 ~ D9-64 · r4 처분 OQ-959 ~ OQ-961) · 초성 검색 · 시스템 공유 걷어냄
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:procedure_app/chat/chat_search.dart';
import 'package:procedure_app/screens/chat_forward_sheet.dart';
import 'package:procedure_app/screens/chat_room_screen.dart' show ChatMenu;
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_app2_test.dart' show openRoom;
import 'chat_fixture.dart';
import 'scan_test.dart' show png;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // 나 = 1 · 방 1 = 나의사(2) 1:1 · 방 2 = 그룹 「4층 시술실」 · 방 3 = 마관리(비활성) 1:1 · 직원 = 나의사 · 다코디 · 라상담
  FakeChat fake() => FakeChat()
    ..photoBytes = png
    ..rooms = [
      roomJ(1, last: preview(10, text: '전달할 글')),
      roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM], last: preview(20, at: '2026-10-29T13:00:00.000+09:00')),
      roomJ(3, members: [meM, offM], last: preview(30, sender: 5, at: '2026-10-29T12:00:00.000+09:00')),
    ]
    ..messages[1] = [
      msgJ(10, 1, text: '전달할 글'),
      msgJ(11, 1, kind: 'photo', text: null, photo: {'id': 50, 'width': 400, 'height': 300}),
      msgJ(12, 1, sender: 1, senderName: '가간호', role: 'nurse', kind: 'video', text: null, video: {'id': 7, 'width': 720, 'height': 1280, 'durationMs': 5000}),
    ];

  // 길게 누름 — 텍스트는 글자를(줄 가운데는 말풍선 밖 빈칸) · 사진 · 동영상은 그 말풍선을
  Future<void> share(WidgetTester t, String msgKey) async {
    await t.longPress(msgKey == 'chat-msg-10' ? find.text('전달할 글').first : find.byKey(Key(msgKey)));
    await t.pumpAndSettle();
    await t.tap(find.byKey(const Key('chat-menu-share')));
    await t.pumpAndSettle();
    await settle(t, 4);
  }

  bool row(String key) => find.byKey(Key('fwd-row-$key')).evaluate().isNotEmpty;

  group('전달 시트 — 틀 · 목록(§10.14)', () {
    testWidgets('[공유] → 시트(머리 「공유」 · 검색 · [전체][사람]) · 대화방 = 내 방 − 비활성 1:1 · 직원 = 1:1 없는 사람만(같은 사람 한 번 · OQ-960) · [사람] = 직원 한 번씩', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      expect(find.text('공유'), findsWidgets);
      expect(find.text('이름 · 대화방 검색(초성 가능)'), findsOneWidget);
      expect(find.byKey(const Key('fwd-chip-all')), findsOneWidget);
      expect(find.byKey(const Key('fwd-chip-people')), findsOneWidget);
      expect(find.text('대화방'), findsOneWidget);
      expect(find.text('직원'), findsOneWidget);
      // [전체] — 나의사 = 1:1 방으로 한 번 · 그룹 · 다코디 · 라상담 · 비활성 1:1 없음
      expect(row('p:2'), isTrue);
      expect(row('r:2'), isTrue);
      expect(row('p:3'), isTrue);
      expect(row('p:4'), isTrue);
      expect(row('p:5'), isFalse);
      expect(find.text('마관리'), findsNothing);
      expect(find.text('나의사'), findsNWidgets(2)); // 대화 머리 + 시트 1행(두 번 안 보임)
      // [사람] — 직원만 · 한 번씩
      await t.tap(find.byKey(const Key('fwd-chip-people')));
      await t.pump();
      expect(find.text('대화방'), findsNothing);
      expect([row('p:2'), row('p:3'), row('p:4'), row('r:2')], [true, true, true, false]);
      // 시스템 공유 흔적 없음
      expect(find.textContaining('저장'), findsNothing);
      await teardown(t, app);
    });

    testWidgets('사진 · 동영상 · 남의 것 · 내 것 모두 [공유] = 같은 시트 · 아이패드 = 가운데(Dialog)', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-11');
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      await t.tap(find.byKey(const Key('fwd-close')));
      await t.pumpAndSettle();
      await share(t, 'chat-msg-12');
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      expect(find.byType(BottomSheet), findsOneWidget); // 폰 = 바텀 시트
      await t.tap(find.byKey(const Key('fwd-close')));
      await t.pumpAndSettle();
      await teardown(t, app);
    });

    testWidgets('아이패드 = 가운데', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      ipad(t);
      await t.pumpAndSettle();
      await share(t, 'chat-msg-10');
      expect(find.byType(Dialog), findsOneWidget);
      expect(find.byType(BottomSheet), findsNothing);
      await teardown(t, app);
    });

    testWidgets('직원 목록 실패 = 「직원 목록을 불러오지 못했어요」 · 대화방 묶음은 그대로', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      f.override['/api/chat/people'] = (_) => http.Response('{}', 502);
      await share(t, 'chat-msg-10');
      expect(find.byKey(const Key('fwd-people-failed')), findsOneWidget);
      expect(row('r:2'), isTrue);
      await teardown(t, app);
    });
  });

  group('검색 · 초성(OQ-961)', () {
    test('nameMatches — 초성 · 섞어 쓰기 · 겹자음 · 이어지는 자리 · 대소문자 · 앞뒤 공백', () {
      expect(nameMatches('가나다', 'ㄱㄴ'), isTrue);
      expect(nameMatches('김나래', '김ㄴ'), isTrue);
      expect(nameMatches('가나다', 'ㄴㄷ'), isTrue);
      expect(nameMatches('가나다', 'ㄱㄷ'), isFalse); // 이어지는 자리만
      expect(nameMatches('까치', 'ㄲ'), isTrue);
      expect(nameMatches('까치', 'ㄱ'), isFalse); // 겹자음은 따로
      expect(nameMatches('Room A', 'room a'), isTrue);
      expect(nameMatches('나의사', '  의사 '), isTrue);
      expect(nameMatches('나의사', ''), isTrue);
      expect(nameMatches('나의사', 'ㅁ'), isFalse);
      expect(initialOf('힣'.runes.first), 'ㅎ');
      expect(initialOf('a'.runes.first), isNull);
    });

    testWidgets('시트 검색 — 방 이름 · 사람 이름 · 초성 · 결과 없음 문구 · 고른 것은 검색과 상관없이 칩 줄에 남음', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      await t.tap(find.byKey(const Key('fwd-row-p:4')));
      await t.pump();
      await t.enterText(find.byKey(const Key('fwd-search')), '4층');
      await t.pump();
      expect([row('r:2'), row('p:2'), row('p:3')], [true, false, false]);
      await t.enterText(find.byKey(const Key('fwd-search')), 'ㄷㅋ');
      await t.pump();
      expect([row('p:3'), row('r:2')], [true, false]);
      await t.enterText(find.byKey(const Key('fwd-search')), '나ㅇ');
      await t.pump();
      expect(row('p:2'), isTrue);
      await t.enterText(find.byKey(const Key('fwd-search')), '없는이름');
      await t.pump();
      expect(find.text('찾는 대화방 · 직원이 없어요'), findsOneWidget);
      expect(find.byKey(const Key('fwd-selected-p:4')), findsOneWidget); // 고른 라상담 칩 남음
      await teardown(t, app);
    });

    testWidgets('새 대화 · 참여자 추가 검색도 같은 초성 함수(OQ-961)', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      // 새 대화 화면은 방 목록에서 — 같은 ChatPeopleScreen 이 참여자 추가에도 쓰인다
      Navigator.of(t.element(find.byKey(const Key('chat-input')))).popUntil((r) => r.isFirst);
      await t.pumpAndSettle();
      await t.tap(find.text('새 대화').first);
      await t.pumpAndSettle();
      await settle(t);
      await t.enterText(find.byType(TextField).first, 'ㄷㅋ');
      await t.pump();
      expect(find.text('다코디'), findsOneWidget);
      expect(find.text('라상담'), findsNothing);
      await teardown(t, app);
    });
  });

  group('고르기 · [전송] · 결과(§10.14 · OQ-959)', () {
    testWidgets('동그라미 → 칩 줄 · ✕ 로 빼기 · [전송 N] → forward 본문(고른 차례 · 대상마다 clientId · 1:1 = 방 · 1:1 없는 사람 = accountId) → 전부 됨 = 닫힘 「보냈어요」 · 응답 Message 가 그 방 메모리에(SSE 와 겹침 1개)', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      expect(find.text('전송'), findsOneWidget); // 0개 = 꺼짐
      await t.tap(find.byKey(const Key('fwd-row-r:2')));
      await t.tap(find.byKey(const Key('fwd-row-p:2')));
      await t.tap(find.byKey(const Key('fwd-row-p:4')));
      await t.tap(find.byKey(const Key('fwd-row-p:3')));
      await t.pump();
      expect(find.text('전송 4'), findsOneWidget);
      await t.tap(find.descendant(of: find.byKey(const Key('fwd-selected-p:3')), matching: find.byIcon(Icons.close_rounded))); // 칩 ✕
      await t.pump();
      expect(find.text('전송 3'), findsOneWidget);
      await t.tap(find.byKey(const Key('fwd-send')));
      await settle(t, 8);
      await t.pumpAndSettle();
      final body = jsonDecode(f.where('POST', '/api/chat/messages/10/forward').single.body) as Map;
      final targets = (body['targets'] as List).cast<Map>();
      expect(targets.map((x) => x['roomId'] ?? 'a${x['accountId']}').toList(), [2, 1, 'a4']);
      expect(targets.map((x) => x['clientId']).toSet(), hasLength(3));
      for (final x in targets) {
        expect(x['clientId'], matches(RegExp(r'^[0-9a-f-]{36}$')));
      }
      expect(find.byType(ChatForwardSheet), findsNothing);
      expect(app.toaster.text, '보냈어요');
      // 지금 보던 방(1)으로 보낸 것 = 이 대화 아래에 붙음 · SSE 로 같은 메시지가 와도 1개
      final sentToMe = f.messages[1]!.last;
      expect(app.chat.thread(1).byId.containsKey(sentToMe['id']), isTrue);
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': sentToMe});
      await t.pump();
      expect(find.text('전달할 글'), findsNWidgets(2)); // 원본 + 전달본(겹침 없음)
      expect(app.chat.room(1)!.unread, 0); // 내 것 = 안 읽음 안 늚
      await teardown(t, app);
    });

    testWidgets('10곳 넘으면 토스트 「한 번에 10곳까지 보낼 수 있어요」 · 남은 동그라미 흐림', (t) async {
      final f = fake()..people = [for (var i = 0; i < 12; i++) {'id': 100 + i, 'name': '직원$i', 'role': 'nurse'}];
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      for (var i = 0; i < 10; i++) {
        final k = find.byKey(Key('fwd-row-p:${100 + i}'), skipOffstage: false);
        await t.ensureVisible(k);
        await t.tap(k);
        await t.pump();
      }
      expect(find.text('전송 10'), findsOneWidget);
      final k = find.byKey(const Key('fwd-row-p:110'), skipOffstage: false);
      await t.ensureVisible(k);
      final dim = t.widget<Opacity>(find.ancestor(of: find.byKey(const Key('fwd-pick-p:110')), matching: find.byType(Opacity)).first);
      expect(dim.opacity, lessThan(1));
      await t.tap(k);
      await t.pump();
      expect(app.toaster.text, '한 번에 10곳까지 보낼 수 있어요');
      expect(find.text('전송 10'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('일부 실패 = 시트 남김 · 실패한 곳만 고른 채 · 「1곳에 보내지 못했어요」 · 다시 [전송] = 같은 clientId · 비활성 1:1 대상 = 그것만 실패', (t) async {
      final f = fake()..forwardFail.add('r:2');
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      await t.tap(find.byKey(const Key('fwd-row-p:2')));
      await t.tap(find.byKey(const Key('fwd-row-r:2')));
      await t.pump();
      await t.tap(find.byKey(const Key('fwd-send')));
      await settle(t, 8);
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      expect(app.toaster.text, '1곳에 보내지 못했어요');
      expect(find.byKey(const Key('fwd-selected-r:2')), findsOneWidget);
      expect(find.byKey(const Key('fwd-selected-p:2')), findsNothing);
      final first = ((jsonDecode(f.where('POST', '/api/chat/messages/10/forward').single.body) as Map)['targets'] as List).cast<Map>();
      f.forwardFail.clear();
      await t.tap(find.byKey(const Key('fwd-send')));
      await settle(t, 8);
      await t.pumpAndSettle();
      final second = ((jsonDecode(f.where('POST', '/api/chat/messages/10/forward').last.body) as Map)['targets'] as List).cast<Map>();
      expect(second.single['roomId'], 2);
      expect(second.single['clientId'], first.firstWhere((x) => x['roomId'] == 2)['clientId']); // 같은 clientId
      expect(find.byType(ChatForwardSheet), findsNothing);
      expect(app.toaster.text, '보냈어요');
      await teardown(t, app);
    });

    testWidgets('전부 실패 = 닫힘 + 첫 실패 문구 · 요청 4xx = 닫힘 + message · 네트워크 · 5xx = 시트 남김 「보내지 못했어요」 · 다시 = 같은 clientId', (t) async {
      final f = fake()..forwardFail.addAll(['r:2']);
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      await t.tap(find.byKey(const Key('fwd-row-r:2')));
      await t.pump();
      await t.tap(find.byKey(const Key('fwd-send')));
      await settle(t, 8);
      await t.pumpAndSettle();
      expect(find.byType(ChatForwardSheet), findsNothing);
      expect(app.toaster.text, '대화방을 찾을 수 없어요');
      // 5xx — 시트 남김 · 고른 것 그대로
      f.forwardFail.clear();
      f.override['POST /api/chat/messages/10/forward'] = (_) => http.Response('{}', 502);
      await share(t, 'chat-msg-10');
      await t.tap(find.byKey(const Key('fwd-row-r:2')));
      await t.pump();
      await t.tap(find.byKey(const Key('fwd-send')));
      await settle(t, 8);
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      expect(app.toaster.text, '보내지 못했어요');
      expect(find.text('전송 1'), findsOneWidget);
      final c1 = (((jsonDecode(f.where('POST', '/api/chat/messages/10/forward').last.body) as Map)['targets'] as List).single as Map)['clientId'];
      f.override['POST /api/chat/messages/10/forward'] = (_) => http.Response(
          jsonEncode({'error': {'code': 'chat_not_forwardable', 'message': '전달할 수 없는 메시지예요'}}), 400,
          headers: jsonHeaders);
      await t.tap(find.byKey(const Key('fwd-send')));
      await settle(t, 8);
      await t.pumpAndSettle();
      final c2 = (((jsonDecode(f.where('POST', '/api/chat/messages/10/forward').last.body) as Map)['targets'] as List).single as Map)['clientId'];
      expect(c2, c1); // 다시 = 같은 clientId
      expect(find.byType(ChatForwardSheet), findsNothing); // 4xx = 닫힘
      expect(app.toaster.text, '전달할 수 없는 메시지예요');
      await teardown(t, app);
    });
  });

  group('시트 높이 · 보내는 중(review-code r3 W3-1 · W3-3)', () {
    // 화면 · 상태 표시줄 · 키보드를 바꾼 뒤 시트를 연다 — 머리(손잡이 · [✕] · [전송])가 위 안전 영역 아래 · 화면 안
    Future<void> check(WidgetTester t, Size size, double top, {double keyboard = 0}) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      t.view.physicalSize = size * 3;
      t.view.devicePixelRatio = 3;
      t.view.padding = FakeViewPadding(top: top * 3);
      t.view.viewInsets = FakeViewPadding(bottom: keyboard * 3);
      addTearDown(t.view.reset);
      await t.pumpAndSettle();
      await share(t, 'chat-msg-12'); // 맨 아래 말풍선(작은 화면에서도 보임)
      if (keyboard > 0) {
        await t.tap(find.byKey(const Key('fwd-search')));
        await t.pumpAndSettle();
      }
      for (final k in ['fwd-close', 'fwd-send', 'fwd-search']) {
        final r = t.getRect(find.byKey(Key(k)));
        expect(r.top, greaterThanOrEqualTo(top), reason: '$k 가 상태 표시줄 밑');
        expect(r.bottom, lessThanOrEqualTo(size.height - keyboard), reason: '$k 가 키보드 밑');
      }
      final sheet = t.getRect(find.byType(BottomSheet));
      expect(sheet.top, greaterThanOrEqualTo(top));
      expect(sheet.bottom, lessThanOrEqualTo(size.height - keyboard + 0.5));
      await teardown(t, app);
    }

    testWidgets('작은 화면(SE 꼴 667 · 상태 표시줄 20) — 머리가 상태 표시줄 아래', (t) => check(t, const Size(375, 667), 20));
    testWidgets('큰 화면(Pro Max 꼴 932 · Dynamic Island 59) — 머리가 상태 표시줄 아래', (t) => check(t, const Size(430, 932), 59));
    testWidgets('키보드 열림(검색칸 · 336) — 시트가 키보드 위 칸으로 줄어도 머리는 상태 표시줄 아래', (t) => check(t, const Size(430, 932), 59, keyboard: 336));

    testWidgets('보내는 중 = [✕] 꺼짐 · 바깥 누름 · 끌어 내림으로 안 닫힘 · 「보내는 중…」 → 응답 뒤 닫힘 + 토스트', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      await t.tap(find.byKey(const Key('fwd-row-r:2')));
      await t.pump();
      final gate = Completer<void>();
      f.delay = gate.future;
      await t.tap(find.byKey(const Key('fwd-send')));
      await t.pump();
      expect(find.byKey(const Key('fwd-sending')), findsOneWidget);
      expect(find.text('보내는 중…'), findsOneWidget);
      expect(t.widget<IconButton>(find.byKey(const Key('fwd-close'))).onPressed, isNull);
      // 응답 대기(12초 한도) 안에서만 시계를 흘린다 — pumpAndSettle 은 시간 넘김까지 가 버림
      Future<void> brief() async {
        for (var i = 0; i < 5; i++) {
          await t.pump(const Duration(milliseconds: 100));
        }
      }

      await t.tapAt(const Offset(200, 5)); // 바깥(막) 누름
      await brief();
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      await t.drag(find.text('공유').last, const Offset(0, 500)); // 머리 끌어 내림
      await brief();
      expect(find.byType(ChatForwardSheet), findsOneWidget);
      expect(find.text('보내는 중…'), findsOneWidget);
      gate.complete();
      await settle(t, 8);
      await t.pumpAndSettle();
      expect(find.byType(ChatForwardSheet), findsNothing);
      expect(app.toaster.text, '보냈어요');
      await teardown(t, app);
    });

    testWidgets('보내는 중이 아니면 끌어 내림 · 바깥 누름 = 닫힘(회귀)', (t) async {
      final f = fake();
      final app = await openRoom(t, f, '나의사');
      await share(t, 'chat-msg-10');
      await t.drag(find.text('공유').last, const Offset(0, 500));
      await t.pumpAndSettle();
      expect(find.byType(ChatForwardSheet), findsNothing);
      await share(t, 'chat-msg-10');
      await t.tapAt(const Offset(200, 5));
      await t.pumpAndSettle();
      expect(find.byType(ChatForwardSheet), findsNothing);
      await teardown(t, app);
    });
  });

  test('바텀 시트는 모두 공용 도우미(showAppSheet — 위 안전 영역 아래)로 연다 · 화면 전체 높이 × 로 시트 높이를 잡지 않는다', () {
    final hits = <String>[];
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>()) {
      if (!f.path.endsWith('.dart') || f.path.endsWith('widgets/sheet.dart')) continue;
      if (f.readAsStringSync().contains('showModalBottomSheet')) hits.add(f.path);
    }
    expect(hits, isEmpty);
    expect(File('lib/screens/chat_forward_sheet.dart').readAsStringSync().contains('sizeOf(ctx).height * 0.88'), isFalse);
  });

  test('시스템 공유 걷어냄 — share_plus · SharePlus · chatVideoDownload grep 0 · [공유] 이름 그대로', () {
    final hits = <String>[];
    for (final f in [...Directory('lib').listSync(recursive: true).whereType<File>(), File('pubspec.yaml')]) {
      if (!f.path.endsWith('.dart') && !f.path.endsWith('.yaml')) continue;
      final s = f.readAsStringSync();
      for (final w in ['share_plus', 'SharePlus', 'chatVideoDownload']) {
        if (s.contains(w)) hits.add('${f.path}:$w');
      }
    }
    expect(hits, isEmpty);
    expect(ChatMenu.share.label, '공유');
  });
}
