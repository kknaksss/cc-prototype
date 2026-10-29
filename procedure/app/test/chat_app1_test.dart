// WORK-011 WP-APP1 — 5탭 · 배지 · SSE 채팅 이벤트 · 방 이름 · 미리보기 · 시각 글자 · 방 목록(S1 · S2) · 새 대화(S3a ~ c) · 머리(D9-38)
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/chat/chat_model.dart';
import 'package:procedure_app/chat/chat_view.dart';
import 'package:procedure_app/screens/chat_list_screen.dart';
import 'package:procedure_app/screens/shell.dart';
import 'package:procedure_app/sse/board_stream.dart';
import 'package:procedure_app/widgets/header.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_fixture.dart';

Room room(Map<String, dynamic> j) => Room.fromJson(j);

// 채팅 탭 스택만(목록이 루트) — 대화는 그 위에 쌓인다
Widget chatTab(AppState app) => AppScope(
      state: app,
      child: MaterialApp(
        navigatorObservers: [app.chat.rootRoutes],
        home: Scaffold(
          body: Navigator(observers: [app.chat.chatRoutes], onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => const ChatScreen())),
        ),
      ),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('SSE', () {
    test('채팅 이벤트 6개(r3 chat_message_edited)는 version 규칙 없이 onEvent 로(board 만 version) · 모르는 이름은 버림', () async {
      final ctl = StreamController<List<int>>();
      final got = <String>[];
      final s = BoardStream(
        uri: () => Uri.parse('http://x/api/board/stream?token=t'),
        onUnauthorized: () {},
        onEvent: (e, _) => got.add(e),
        clientFactory: () => MockClient.streaming((req, _) async => http.StreamedResponse(ctl.stream, 200)),
      );
      s.start();
      await Future<void>.delayed(Duration.zero);
      ctl.add(utf8.encode('event: board\ndata: ${jsonEncode({'now': t0, 'version': 3, 'cards': []})}\n\n'));
      for (final e in ['chat_message', 'chat_message_deleted', 'chat_message_edited', 'chat_room', 'chat_room_removed', 'chat_read', 'chat_typing']) {
        ctl.add(utf8.encode('event: $e\ndata: {"roomId":1}\n\n'));
      }
      await Future<void>.delayed(Duration.zero);
      expect(got, ['chat_message', 'chat_message_deleted', 'chat_message_edited', 'chat_room', 'chat_room_removed', 'chat_read']);
      expect(s.board?.version, 3); // 허브 version 그대로
      s.stop();
      await ctl.close();
    });
  });

  group('방 이름 · 미리보기 · 시각 글자(§4.5 · §10.0)', () {
    test('1:1 = 상대 이름 · 그룹 = back 이름(이름 없는 그룹 = 나열) · 비활성 상대', () {
      expect(roomTitle(room(roomJ(1))), '나의사');
      expect(roomTitle(room(roomJ(2, group: true, members: [meM, docM, coordM]))), '나의사, 다코디');
      expect(roomTitle(room(roomJ(3, group: true, title: '4층 시술실', members: [meM, docM, coordM]))), '4층 시술실');
      expect(peerInactive(room(roomJ(4, members: [meM, offM]))), isTrue);
      expect(peerInactive(room(roomJ(5))), isFalse);
    });

    test('미리보기 — 1:1 상대 = 본문 · 내 것 = 「나: 」 · 그룹 = 「보낸 사람: 」 · 사진 · 지운 것 · 시스템 줄', () {
      ({String prefix, String body, MsgKind? media}) p(Map<String, dynamic> last, {bool group = false}) =>
          previewOf(room(roomJ(1, group: group, members: [meM, docM, coordM], last: last)));
      expect(p(preview(1, text: '줄\n바꿈')), (prefix: '', body: '줄 바꿈', media: null));
      expect(p(preview(1, mine: true, sender: 1)), (prefix: '나: ', body: '안녕하세요', media: null));
      expect(p(preview(1), group: true), (prefix: '나의사: ', body: '안녕하세요', media: null));
      expect(p(preview(1, kind: 'photo', text: null), group: true), (prefix: '나의사: ', body: '사진', media: MsgKind.photo));
      expect(p(preview(1, deleted: true, text: null)), (prefix: '', body: '삭제된 메시지예요', media: null));
      expect(p(preview(1, deleted: true, text: null), group: true), (prefix: '나의사: ', body: '삭제된 메시지예요', media: null));
      expect(p(preview(1, kind: 'system', text: '나의사 님이 나갔어요'), group: true), (prefix: '', body: '나의사 님이 나갔어요', media: null));
      expect(previewOf(room(roomJ(1))).body, '');
    });

    test('시각 — 오늘 HH:MM · 어제 · 올해 M. D · 그 전 YYYY. M. D · 말풍선 · 날짜 구분선 · 크게 보기(KST)', () {
      final now = DateTime.parse('2026-10-29T15:00:00+09:00');
      expect(listTime('2026-10-29T14:03:07.215+09:00', now: now), '14:03');
      expect(listTime('2026-10-29T05:03:07.215Z', now: now), '14:03'); // 오프셋이 달라도 KST 로
      expect(listTime('2026-10-28T23:59:00.000+09:00', now: now), '어제');
      expect(listTime('2026-10-27T10:00:00.000+09:00', now: now), '10. 27');
      expect(listTime('2025-12-31T10:00:00.000+09:00', now: now), '2025. 12. 31');
      expect(bubbleTime('2026-10-29T09:05:00.000+09:00'), '09:05');
      expect(dayLabel('2026-10-29T09:05:00.000+09:00'), '10월 29일 (목)');
      expect(dayLabel('2026-10-28T09:05:00.000+09:00'), '10월 28일 (수)');
      expect(viewerTime('2026-10-29T14:20:00.000+09:00'), '10월 29일 14:20');
      expect(countText(99), '99');
      expect(countText(100), '99+');
    });

    test('그룹 보낸 사람 이름 — 연달아면 첫 번째만 · 시스템 줄 · 날짜가 끼면 다시 · 1:1 · 내 것 없음', () {
      ChatMessage m(int id, int s, {String kind = 'text', String at = t0}) => ChatMessage.fromJson(msgJ(id, 1, sender: s, kind: kind, at: at));
      expect(showSenderName(group: true, cur: m(1, 2), prev: null, mine: false), isTrue);
      expect(showSenderName(group: true, cur: m(2, 2), prev: m(1, 2), mine: false), isFalse);
      expect(showSenderName(group: true, cur: m(3, 3), prev: m(2, 2), mine: false), isTrue);
      expect(showSenderName(group: true, cur: m(4, 2), prev: m(3, 2, kind: 'system'), mine: false), isTrue);
      expect(showSenderName(group: true, cur: m(5, 2, at: '2026-10-30T09:00:00.000+09:00'), prev: m(4, 2), mine: false), isTrue);
      expect(showSenderName(group: false, cur: m(1, 2), prev: null, mine: false), isFalse);
      expect(showSenderName(group: true, cur: m(1, 1), prev: null, mine: true), isFalse);
    });
  });

  group('탭 배지 · 상태(§10.1)', () {
    test('GET rooms → unreadRooms(알림 끈 방도 셈) · SSE chat_message 남의 것 +1 · 시스템 줄 · 내 것 · 이미 센 것은 안 올림', () async {
      final f = FakeChat()
        ..rooms = [
          roomJ(1, unread: 2, last: preview(10)),
          roomJ(2, group: true, members: [meM, docM, coordM], muted: true, unread: 1, last: preview(20)),
          roomJ(3, members: [meM, coordM], last: preview(30, sender: 3)),
        ];
      final app = chatApp(f);
      await app.chat.refreshRooms();
      expect(app.chat.unreadRooms.value, 2);
      expect(app.chat.meId, 1);
      // 방 3 에 남의 메시지 → 0 → 1 = 방 수 +1
      app.chat.onEvent('chat_message', {'roomId': 3, 'message': msgJ(31, 3, sender: 3, senderName: '다코디', at: '2026-10-29T15:00:00.000+09:00')});
      expect(app.chat.room(3)!.unread, 1);
      expect(app.chat.unreadRooms.value, 3);
      expect(app.chat.rooms.first.id, 3); // 마지막 메시지 순
      // 시스템 줄 = 남이 한 일이어도 안 셈
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': msgJ(11, 1, kind: 'system', text: '나의사 님이 나갔어요')});
      expect(app.chat.room(1)!.unread, 2);
      // 내 것(다른 기기) = 그 방 읽음
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': msgJ(12, 1, sender: 1, senderName: '가간호')});
      expect(app.chat.room(1)!.unread, 0);
      expect(app.chat.room(1)!.lastMessage!.mine, isTrue);
      // chat_room 이 먼저 와서 이미 센 메시지는 다시 세지 않음
      app.chat.onEvent('chat_room', {'room': roomJ(3, members: [meM, coordM], unread: 2, last: preview(32, sender: 3))});
      app.chat.onEvent('chat_message', {'roomId': 3, 'message': msgJ(32, 3, sender: 3, senderName: '다코디')});
      expect(app.chat.room(3)!.unread, 2);
      // chat_read(같은 계정 다른 기기) → 0
      app.chat.onEvent('chat_read', {'roomId': 3, 'lastReadMessageId': 32, 'unreadRooms': 1, 'lastViewedAt': t0});
      expect(app.chat.room(3)!.unread, 0);
      expect(app.chat.unreadRooms.value, 1);
      // chat_room_removed → 목록에서 빠짐
      app.chat.onEvent('chat_room_removed', {'roomId': 2});
      expect(app.chat.room(2), isNull);
      expect(app.chat.unreadRooms.value, 0);
      app.stream.dispose();
    });

    test('SSE 채팅 이벤트는 AppState 가 채팅 상태로 넘긴다(_onStreamEvent)', () async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = chatApp(f);
      await app.chat.refreshRooms();
      app.stream.onEvent!('chat_message', {'roomId': 1, 'message': msgJ(5, 1)});
      expect(app.chat.unreadRooms.value, 1);
      app.stream.onEvent!('notification', {'unread': 4});
      expect(app.unread.value, 4); // 종 배지는 그대로 따로(채팅은 안 셈 — D9-30)
      app.stream.dispose();
    });

    // 셸 전체는 아이패드 크기로(시험 글꼴 Ahem 이 넓어 폰 폭에서 다른 탭 줄이 넘친다) — 탭바 · 레일은 같은 _TabIcon
    testWidgets('5탭 — 예약 · 내원 · 시술 현황 · 채팅 · 설정 차례 · 채팅 칸 빨간 배지(99+)', (t) async {
      ipad(t);
      expect(AppTab.values, [AppTab.reservations, AppTab.visits, AppTab.board, AppTab.chat, AppTab.settings]);
      expect(tabName[AppTab.chat], '채팅');
      final f = FakeChat()..rooms = [for (var i = 1; i <= 120; i++) roomJ(i, unread: 1, last: preview(i))];
      final app = chatApp(f);
      await t.pumpWidget(AppScope(state: app, child: MaterialApp(navigatorObservers: [app.chat.rootRoutes], home: const Shell())));
      await t.runAsync(() => app.chat.refreshRooms());
      await t.pump();
      final labels = ['예약 현황', '내원 현황', '시술 현황', '채팅', '설정'];
      final ys = [for (final l in labels) t.getCenter(find.text(l).first).dy];
      expect([...ys]..sort(), ys); // 레일 위부터 차례
      expect(find.descendant(of: find.byKey(const Key('chat-tab-badge')), matching: find.text('99+')), findsOneWidget);
      await teardown(t, app);
    });
  });

  group('방 목록(S1 · S2) · 머리(D9-38)', () {
    testWidgets('머리 = AppHeader [Céramique][채팅][종] · 「채팅」 한 번 · 아래 [새 대화] · 행(이름 · 역할 · 인원 · 종 빗금 · 안 읽음)', (t) async {
      phone(t);
      final f = FakeChat()
        ..rooms = [
          roomJ(1, unread: 3, last: preview(10, text: '3번 방 비워 주세요')),
          roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM, consM], muted: true, unread: 2, last: preview(20, kind: 'photo', text: null)),
          roomJ(3, members: [meM, offM], last: preview(30, sender: 5, senderName: '마관리')),
        ];
      final app = chatApp(f);
      await t.pumpWidget(chatTab(app));
      await settle(t);
      expect(find.byType(AppHeader), findsOneWidget);
      expect(find.text('Céramique'), findsOneWidget);
      expect(find.text('채팅'), findsOneWidget); // 헤더 가운데 한 번만(시안 S1 의 둘째 「채팅」 줄 없음)
      expect(find.byKey(const Key('chat-new')), findsOneWidget);
      expect(find.text('나의사'), findsOneWidget);
      expect(find.text('의사'), findsOneWidget); // 1:1 역할 Badge
      expect(find.text('3번 방 비워 주세요'), findsOneWidget);
      expect(find.text('4층 시술실'), findsOneWidget);
      expect(find.text('4'), findsOneWidget); // 그룹 인원
      expect(find.byIcon(Icons.notifications_off_outlined), findsOneWidget);
      expect(find.text('나의사: '), findsOneWidget);
      expect(find.text('사진'), findsOneWidget);
      expect(find.text('(비활성)'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('빈 목록(S2) — 안내 + 가운데 [새 대화]', (t) async {
      phone(t);
      final app = chatApp(FakeChat());
      await t.pumpWidget(chatTab(app));
      await settle(t);
      expect(find.text('아직 대화가 없어요'), findsOneWidget);
      expect(find.text('함께 일하는 직원을 골라 메시지와 사진을 보내 보세요. 한 명이면 1:1, 여러 명이면 그룹이에요.'), findsOneWidget);
      expect(find.text('새 대화'), findsNWidgets(2));
      await teardown(t, app);
    });

    testWidgets('채팅 읽기 실패(옛 back 404)는 조용히 — 토스트 없음', (t) async {
      phone(t);
      final f = FakeChat()..override['GET /api/chat/rooms'] = (_) => http.Response('{"error":{"code":"not_found","message":"없음"}}', 404);
      final app = chatApp(f);
      expect(await app.chat.refreshRooms(), isFalse);
      expect(app.toaster.text, isNull);
      app.stream.dispose();
    });
  });

  group('새 대화(S3a ~ c)', () {
    Future<(AppState, FakeChat)> openNew(WidgetTester t) async {
      phone(t);
      final f = FakeChat()..people = [docM, coordM, consM, member(6, '바간호')];
      final app = chatApp(f);
      await t.pumpWidget(chatTab(app));
      await settle(t);
      await t.tap(find.text('새 대화').first);
      await t.pumpAndSettle();
      await settle(t);
      return (app, f);
    }

    testWidgets('1명 = [대화 시작] · 「1명 선택 · 1:1 대화」 → POST rooms/direct → 그 방 대화', (t) async {
      final (app, f) = await openNew(t);
      expect(find.text('새 대화'), findsWidgets);
      expect(find.text('코디'), findsOneWidget); // 역할 Badge
      await t.tap(find.text('나의사'));
      await t.pump();
      expect(find.text('대화 시작'), findsOneWidget);
      expect(find.text('1명 선택 · 1:1 대화'), findsOneWidget);
      await t.tap(find.text('대화 시작'));
      await settle(t);
      await t.pumpAndSettle();
      expect(jsonDecode(f.where('POST', '/api/chat/rooms/direct').single.body), {'accountId': 2});
      expect(find.text('채팅'), findsOneWidget); // 대화 머리 「‹ 채팅」
      expect(find.byKey(const Key('chat-input')), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('2명 이상 = [만들기] + 그룹 이름 · 안내 · 고른 칩 ✕ 로 빼기 → POST rooms {accountIds, title}', (t) async {
      final (app, f) = await openNew(t);
      await t.tap(find.text('나의사'));
      await t.tap(find.text('다코디'));
      await t.pump();
      expect(find.text('만들기'), findsOneWidget);
      expect(find.text('그룹 이름'), findsOneWidget);
      expect(find.text('2명 선택 · 나 포함 3명 · 최대 20명'), findsOneWidget);
      await t.tap(find.text('라상담'));
      await t.pump();
      await t.tap(find.bySemanticsLabel('라상담 빼기'));
      await t.pump();
      expect(find.text('2명 선택 · 나 포함 3명 · 최대 20명'), findsOneWidget);
      await t.enterText(find.byKey(const Key('chat-group-title')), '4층');
      await t.tap(find.text('만들기'));
      await settle(t);
      await t.pumpAndSettle();
      expect(jsonDecode(f.where('POST', '/api/chat/rooms').single.body), {'accountIds': [2, 3], 'title': '4층'});
      await teardown(t, app);
    });

    testWidgets('검색 — 이름에 든 사람만 · 없으면 「찾는 직원이 없어요」 · 고른 사람은 칩에 남음 · 0명이면 버튼 꺼짐', (t) async {
      final (app, f) = await openNew(t);
      expect(find.text('대화 시작'), findsOneWidget); // 0명 — 꺼짐
      await t.tap(find.text('대화 시작'));
      await t.pump();
      expect(f.where('POST', '/api/chat/rooms/direct'), isEmpty);
      await t.tap(find.text('바간호'));
      await t.enterText(find.byKey(const Key('chat-search')), '코디');
      await t.pump();
      expect(find.text('다코디'), findsOneWidget);
      expect(find.text('나의사'), findsNothing);
      expect(find.text('바간호'), findsOneWidget); // 칩
      await t.enterText(find.byKey(const Key('chat-search')), '없는이름');
      await t.pump();
      expect(find.text('찾는 직원이 없어요'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('19명이 차면 더 못 고름(나 포함 20)', (t) async {
      phone(t);
      final f = FakeChat()..people = [for (var i = 0; i < 21; i++) member(100 + i, '직원${i.toString().padLeft(2, '0')}')];
      final app = chatApp(f);
      await t.pumpWidget(chatTab(app));
      await settle(t);
      await t.tap(find.text('새 대화').first);
      await t.pumpAndSettle();
      await settle(t);
      for (var i = 0; i < 21; i++) {
        final w = find.text('직원${i.toString().padLeft(2, '0')}');
        await t.scrollUntilVisible(w.last, 200, scrollable: find.byType(Scrollable).last);
        await t.tap(w.last);
        await t.pump();
      }
      expect(find.text('19명 선택 · 나 포함 20명 · 최대 20명'), findsOneWidget);
      await teardown(t, app);
    });
  });
}
