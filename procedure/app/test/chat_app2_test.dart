// WORK-011 WP-APP2 — 대화(S4 · S5) · 머리 「‹ 채팅」 · 비활성 1:1 · 입력 한도 · 보내는 중 · 실패 · 다시 보내기(S6) · since 겹침 ·
// 읽음 · before · 삭제(S9a · S9b) · 사진(S7a · S7b · S8 — JPEG 다시 인코딩은 실기기 C5)
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/chat/chat_state.dart';
import 'package:procedure_app/chat/chat_view.dart';
import 'package:procedure_app/chat/photo_pick.dart';
import 'package:procedure_app/screens/chat_attach_sheet.dart';
import 'package:procedure_app/screens/chat_list_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_fixture.dart';
import 'scan_test.dart' show png;

Widget chatTab(AppState app) => AppScope(
      state: app,
      child: MaterialApp(
        navigatorObservers: [app.chat.rootRoutes],
        home: Scaffold(
          body: Navigator(observers: [app.chat.chatRoutes], onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => const ChatScreen())),
        ),
      ),
    );

// 목록 → 그 방(폰 · 채팅 탭)
Future<AppState> openRoom(WidgetTester t, FakeChat f, String rowText) async {
  phone(t);
  final app = chatApp(f)..tab.value = AppTab.chat;
  await t.pumpWidget(chatTab(app));
  await settle(t);
  await t.tap(find.text(rowText).first);
  await t.pumpAndSettle();
  await settle(t);
  return app;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('대화 그리기', () {
    testWidgets('1:1(S4) — 머리 「‹ 채팅」 · 이름 + 역할 Badge · 날짜 구분선 · 내 것 / 상대 · 지운 자리 · 사진(Bearer · 메모리)', (t) async {
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1, last: preview(14))]
        ..messages[1] = [
          msgJ(10, 1, text: '장비 점검 있어요', at: '2026-10-28T18:10:00.000+09:00'),
          msgJ(11, 1, sender: 1, senderName: '가간호', role: 'nurse', at: '2026-10-28T18:12:00.000+09:00', deletedAt: '2026-10-28T18:20:00.000+09:00'),
          msgJ(12, 1, sender: 1, senderName: '가간호', role: 'nurse', text: '네 비워 둘게요', at: '2026-10-28T18:13:00.000+09:00'),
          msgJ(13, 1, text: '마취 크림 언제?', at: '2026-10-29T13:58:00.000+09:00'),
          msgJ(14, 1, kind: 'photo', text: null, photo: {'id': 77, 'width': 400, 'height': 300}, at: '2026-10-29T14:20:00.000+09:00'),
        ];
      final app = await openRoom(t, f, '나의사');
      expect(find.text('채팅'), findsOneWidget); // ‹ 채팅
      expect(find.text('나의사'), findsOneWidget);
      expect(find.text('의사'), findsOneWidget);
      expect(find.text('Céramique'), findsNothing); // 대화 화면엔 공통 헤더 없음
      expect(find.text('10월 28일 (수)'), findsOneWidget);
      expect(find.text('10월 29일 (목)'), findsOneWidget);
      expect(find.text('장비 점검 있어요'), findsOneWidget);
      expect(find.text('네 비워 둘게요'), findsOneWidget);
      expect(find.text('삭제된 메시지예요'), findsOneWidget);
      expect(find.text('18:13'), findsOneWidget);
      final photoReq = f.where('GET', '/api/chat/photos/77').single;
      expect(photoReq.headers['Authorization'], 'Bearer t');
      expect(photoReq.url.query, isEmpty); // ?token= 없음
      expect(find.byType(Image), findsOneWidget);
      expect(app.chat.photos.get(77), isNotNull);
      await teardown(t, app);
    });

    testWidgets('그룹(S5) — 보낸 사람 이름(연달아면 첫 번째만 · 시스템 줄 뒤 다시) · 시스템 줄 가운데 · 「N명」 · 비활성 이름', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM, consM], last: preview(25))]
        ..messages[2] = [
          msgJ(20, 2, sender: 5, senderName: '마관리', role: 'admin', active: false, text: '소모품 채웠어요', at: '2026-10-29T10:00:00.000+09:00'),
          msgJ(21, 2, sender: 3, senderName: '다코디', role: 'coordinator', text: '첫째', at: '2026-10-29T10:01:00.000+09:00'),
          msgJ(22, 2, sender: 3, senderName: '다코디', role: 'coordinator', text: '둘째', at: '2026-10-29T10:02:00.000+09:00'),
          msgJ(23, 2, kind: 'system', text: '다코디님이 라상담님을 초대했습니다', at: '2026-10-29T10:03:00.000+09:00'),
          msgJ(24, 2, sender: 3, senderName: '다코디', role: 'coordinator', text: '셋째', at: '2026-10-29T10:04:00.000+09:00'),
          msgJ(25, 2, sender: 1, senderName: '가간호', role: 'nurse', text: '내 것', at: '2026-10-29T10:05:00.000+09:00'),
        ];
      final app = await openRoom(t, f, '4층 시술실');
      expect(find.text('4명'), findsOneWidget);
      expect(find.text('마관리 (비활성)'), findsOneWidget);
      expect(find.text('다코디'), findsNWidgets(2)); // 첫째 위 · 시스템 줄 뒤 셋째 위(둘째 위는 없음)
      expect(find.text('다코디님이 라상담님을 초대했습니다'), findsOneWidget);
      expect(find.text('가간호'), findsNothing); // 내 것엔 이름 없음
      await teardown(t, app);
    });

    testWidgets('비활성 상대 1:1(D9-42) — 입력줄 대신 「비활성 계정이에요」 · 옛 메시지 보임', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(3, members: [meM, offM], last: preview(30, sender: 5))]
        ..messages[3] = [msgJ(30, 3, sender: 5, senderName: '마관리', text: '인수인계 메모', active: false)];
      final app = await openRoom(t, f, '마관리');
      expect(find.byKey(const Key('chat-inactive')), findsOneWidget);
      expect(find.text('비활성 계정이에요'), findsOneWidget);
      expect(find.byKey(const Key('chat-input')), findsNothing);
      expect(find.byKey(const Key('chat-plus')), findsNothing);
      expect(find.text('인수인계 메모'), findsOneWidget);
      await teardown(t, app);
    });

    test('입력 한도 = 코드 포인트 2000(이모지 2001 → 2000 · Flutter maxLength 아님)', () {
      const f = RuneLimitFormatter();
      final emoji = '😀' * 2001;
      final out = f.formatEditUpdate(TextEditingValue.empty, TextEditingValue(text: emoji));
      expect(out.text.runes.length, 2000);
      expect(out.text.length, 4000); // UTF-16 은 두 배
      final ok = '가' * 2000;
      expect(f.formatEditUpdate(TextEditingValue.empty, TextEditingValue(text: ok)).text, ok);
      expect(newClientId(), matches(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')));
    });
  });

  group('보내기(S6)', () {
    testWidgets('보내기 → 흐린 말풍선 「보내는 중…」 → 200 이면 보통 · SSE 로 같은 clientId 가 와도 하나 · 비면 [보내기] 꺼짐', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      // 응답을 붙잡아 「보내는 중」을 본다
      final gate = Completer<void>();
      f.override['POST /api/chat/rooms/1/messages'] = (req) {
        final b = jsonDecode(req.body) as Map;
        final m = msgJ(80, 1, sender: 1, senderName: '가간호', role: 'nurse', text: b['text'] as String, clientId: b['clientId'] as String);
        f.messages[1] = [m];
        return http.Response(jsonEncode(m), 200, headers: jsonHeaders);
      };
      f.delay = gate.future;
      await t.tap(find.byKey(const Key('chat-send')));
      expect(f.where('POST', '/api/chat/rooms/1/messages'), isEmpty);
      await t.enterText(find.byKey(const Key('chat-input')), '  들어갈게요  ');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-send')));
      await t.pump();
      expect(find.text('보내는 중…'), findsOneWidget);
      gate.complete();
      await settle(t);
      final sent = jsonDecode(f.where('POST', '/api/chat/rooms/1/messages').single.body) as Map;
      expect(sent['text'], '들어갈게요');
      expect((sent['clientId'] as String).length, 36);
      expect(find.text('보내는 중…'), findsNothing);
      expect(find.text('들어갈게요'), findsOneWidget);
      final m = f.messages[1]!.single;
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': m});
      await t.pump();
      expect(find.text('들어갈게요'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('실패(5xx · 네트워크) → 빨간 ! 「보내지 못했어요」 [다시 보내기] = 같은 clientId', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      var fail = true;
      final app = await openRoom(t, f, '나의사');
      f.override['POST /api/chat/rooms/1/messages'] = (req) => fail
          ? http.Response('{"error":{"code":"error","message":"x"}}', 503)
          : http.Response(jsonEncode(msgJ(70, 1, sender: 1, senderName: '가간호', text: '마취 크림 닦았어요', clientId: (jsonDecode(req.body) as Map)['clientId'] as String)), 200,
              headers: jsonHeaders);
      await t.enterText(find.byKey(const Key('chat-input')), '마취 크림 닦았어요');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-send')));
      await settle(t);
      expect(find.text('보내지 못했어요'), findsOneWidget);
      expect(find.byIcon(Icons.error_outline_rounded), findsOneWidget); // 빨간 !
      fail = false;
      await t.tap(find.text('다시 보내기'));
      await settle(t);
      final ids = [for (final r in f.where('POST', '/api/chat/rooms/1/messages')) (jsonDecode(r.body) as Map)['clientId']];
      expect(ids.length, 2);
      expect(ids.toSet().length, 1); // 같은 clientId — 두 번 가지 않음(D9-16)
      expect(find.text('보내지 못했어요'), findsNothing);
      expect(find.text('마취 크림 닦았어요'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('4xx(401 빼고) = 토스트 message + 말풍선 지움(OQ-934)', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      f.override['POST /api/chat/rooms/1/messages'] = (_) => http.Response(jsonEncode({'error': {'code': 'chat_peer_inactive', 'message': '비활성 계정이에요'}}), 409, headers: jsonHeaders);
      await t.enterText(find.byKey(const Key('chat-input')), '안녕');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-send')));
      await settle(t);
      expect(app.toaster.text, '비활성 계정이에요');
      expect(find.text('보내지 못했어요'), findsNothing);
      expect(app.chat.thread(1).pending, isEmpty);
      await teardown(t, app);
    });
  });

  group('읽기 · 페이지 · 읽음', () {
    testWidgets('열면 읽음 {messageId = 그린 마지막 id}(채팅 탭 · 맨 위) · 메시지 0개 방은 읽음 안 보냄(W2-2) · since 없이 처음 읽기', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1, unread: 2, last: preview(12)), roomJ(2, members: [meM, coordM])]
        ..messages[1] = [msgJ(11, 1), msgJ(12, 1)];
      final app = await openRoom(t, f, '나의사');
      expect(jsonDecode(f.where('POST', '/api/chat/rooms/1/read').single.body), {'messageId': 12});
      expect(app.chat.room(1)!.unread, 0);
      expect(app.chat.unreadRooms.value, 0);
      expect(f.where('GET', '/api/chat/rooms/1/messages').single.url.query, isEmpty);
      // 보고 있는 방에 새 메시지 → 1초 묶음 읽음 · 안 읽음 안 오름
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': msgJ(13, 1, at: '2026-10-29T15:00:00.000+09:00')});
      await t.pump();
      expect(app.chat.room(1)!.unread, 0);
      await t.pump(const Duration(milliseconds: 1100));
      await settle(t);
      expect([for (final r in f.where('POST', '/api/chat/rooms/1/read')) (jsonDecode(r.body) as Map)['messageId']], [12, 13]);
      // 빈 방
      await t.tap(find.text('채팅'));
      await t.pumpAndSettle();
      await t.tap(find.text('다코디'));
      await t.pumpAndSettle();
      await settle(t);
      expect(f.where('POST', '/api/chat/rooms/2/read'), isEmpty);
      await teardown(t, app);
    });

    test('since — 받은 것 중 가장 늦은 updatedAt(지운 것 포함) · queryParameters 로 %2B · 겹침은 id 로 바꿔 끼움 · hasMore 면 최근 50 다시', () async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = chatApp(f);
      app.chat.viewOpened(1); // 열린 대화
      f.messages[1] = [msgJ(1, 1, text: 'a'), msgJ(2, 1, text: 'b', at: '2026-10-29T14:03:08.000+09:00')];
      await app.chat.loadLatest(1);
      expect(app.chat.thread(1).latestUpdatedAt, '2026-10-29T14:03:08.000+09:00');
      // 경계 메시지(2)가 다시 오고 · 1 은 지워짐 · 3 은 새것
      f.messages[1] = [
        msgJ(1, 1, deletedAt: '2026-10-29T14:05:00.000+09:00'),
        msgJ(2, 1, text: 'b', at: '2026-10-29T14:03:08.000+09:00'),
        msgJ(3, 1, text: 'c', at: '2026-10-29T14:04:00.000+09:00'),
      ];
      await app.chat.catchUp();
      final q = f.where('GET', '/api/chat/rooms/1/messages').last;
      expect(q.url.query, 'since=2026-10-29T14%3A03%3A08.000%2B09%3A00');
      expect(q.url.queryParameters['since'], '2026-10-29T14:03:08.000+09:00');
      final t1 = app.chat.thread(1);
      expect([for (final m in t1.messages) m.id], [1, 2, 3]);
      expect(t1.byId[1]!.deleted, isTrue);
      // 받은 게 없는 방은 since 없이
      final t2 = ChatThread();
      expect(t2.latestUpdatedAt, isNull);
      // hasMore → since 응답 대신 최근 50 다시
      f.messages[1] = [for (var i = 100; i < 160; i++) msgJ(i, 1, at: '2026-10-29T16:00:00.000+09:00')];
      await app.chat.catchUp();
      expect(app.chat.thread(1).byId.length, 50);
      expect(app.chat.thread(1).hasOlder, isTrue);
      // 열려 있지 않은 방은 다음에 열 때 처음부터(메모리 비움)
      app.chat.viewClosed(1);
      await app.chat.catchUp();
      expect(app.chat.thread(1).loaded, isFalse);
      app.stream.dispose();
    });

    test('위 끝 = before=<가장 오래된 id> · hasMore 없으면 더 안 부름', () async {
      final f = FakeChat()..rooms = [roomJ(1)];
      f.messages[1] = [for (var i = 1; i <= 60; i++) msgJ(i, 1)];
      final app = chatApp(f);
      await app.chat.loadLatest(1);
      expect(app.chat.thread(1).oldestId, 11);
      expect(app.chat.thread(1).hasOlder, isTrue);
      await app.chat.loadOlder(1);
      expect(f.where('GET', '/api/chat/rooms/1/messages').last.url.queryParameters, {'before': '11'});
      expect(app.chat.thread(1).byId.length, 60);
      expect(app.chat.thread(1).hasOlder, isFalse);
      await app.chat.loadOlder(1);
      expect(f.where('GET', '/api/chat/rooms/1/messages').length, 2);
      app.stream.dispose();
    });
  });

  group('삭제(S9a · S9b)', () {
    testWidgets('내 메시지 길게 → [삭제] → 확인 → DELETE · 「삭제된 메시지예요」 · 남의 것 = [삭제] 없음(r3 D9-54 · FAIL-1) · SSE 삭제', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1, last: preview(2))]
        ..messages[1] = [msgJ(1, 1, text: '상대 글'), msgJ(2, 1, sender: 1, senderName: '가간호', text: '내 글')];
      final app = await openRoom(t, f, '나의사');
      await t.longPress(find.text('상대 글'));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-delete-menu')), findsNothing);
      expect(find.byKey(const Key('chat-menu-copy')), findsOneWidget);
      await t.tapAt(const Offset(5, 5)); // 막 = 닫기
      await t.pumpAndSettle();
      await t.longPress(find.text('내 글'));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-delete-menu')));
      await t.pumpAndSettle();
      expect(find.text('메시지를 삭제할까요?'), findsOneWidget);
      expect(find.text('대화방의 모두에게 「삭제된 메시지예요」로 보여요. 되돌릴 수 없어요.'), findsOneWidget);
      await t.tap(find.text('삭제'));
      await t.pumpAndSettle();
      await settle(t);
      expect(f.where('DELETE', '/api/chat/messages/2'), hasLength(1));
      expect(find.text('내 글'), findsNothing);
      expect(find.text('삭제된 메시지예요'), findsOneWidget);
      // 다른 사람이 지움(SSE)
      app.chat.onEvent('chat_message_deleted', {'roomId': 1, 'messageId': 1, 'updatedAt': '2026-10-29T15:00:00.000+09:00'});
      await t.pump();
      expect(find.text('삭제된 메시지예요'), findsNWidgets(2));
      expect(app.chat.room(1)!.lastMessage!.deleted, isTrue);
      await teardown(t, app);
    });
  });

  group('삭제 뒤 since(review-code r1 FAIL-1)', () {
    test('delete() 뒤 since = 서버가 준 가장 늦은 updatedAt(+09:00) — 앱 로컬 시각을 섞지 않음 · SSE 가 먼저 와도 HTTP 가 덮지 않음', () async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = chatApp(f);
      app.chat.viewOpened(1);
      f.messages[1] = [
        msgJ(1, 1, sender: 1, senderName: '가간호', text: 'a', at: '2026-10-29T14:03:07.215+09:00'),
        msgJ(2, 1, sender: 1, senderName: '가간호', text: 'b', at: '2026-10-29T14:03:08.000+09:00'),
      ];
      await app.chat.loadLatest(1);
      // HTTP 만(응답 = {ok}) — 지운 메시지의 updatedAt 은 서버 값 그대로
      await app.chat.delete(app.chat.thread(1).byId[1]!);
      expect(app.chat.thread(1).byId[1]!.deleted, isTrue);
      expect(app.chat.thread(1).latestUpdatedAt, '2026-10-29T14:03:08.000+09:00');
      f.messages[1] = [];
      await app.chat.catchUp();
      expect(f.where('GET', '/api/chat/rooms/1/messages').last.url.queryParameters['since'], '2026-10-29T14:03:08.000+09:00');
      // SSE(서버 updatedAt) 가 먼저 → 뒤따른 HTTP 처리가 덮지 않음
      final m2 = app.chat.thread(1).byId[2]!;
      app.chat.onEvent('chat_message_deleted', {'roomId': 1, 'messageId': 2, 'updatedAt': '2026-10-29T14:10:00.123+09:00'});
      await app.chat.delete(m2);
      await app.chat.catchUp();
      expect(f.where('GET', '/api/chat/rooms/1/messages').last.url.queryParameters['since'], '2026-10-29T14:10:00.123+09:00');
      app.stream.dispose();
    });
  });

  group('사진(S7b · S8 · r3 [+] 시트 카메라 칸)', () {
    late PhotoPicker saved;
    late RecentMedia savedRecent;
    setUp(() {
      saved = pickChatPhoto;
      savedRecent = recentMedia;
      recentMedia = FakeRecent();
    });
    tearDown(() {
      pickChatPhoto = saved;
      recentMedia = savedRecent;
    });

    // [+] 시트를 닫는다(카메라 칸은 시트를 닫지 않음 — r3 W-8)
    Future<void> closeSheet(WidgetTester t) async {
      Navigator.of(t.element(find.byType(ChatAttachSheet))).pop();
      await t.pumpAndSettle();
    }

    testWidgets('[+] → 카메라 칸 → 올리기(multipart · roomId · width · height · JPEG) → 보내기 {clientId, photoId}', (t) async {
      final picked = <PhotoSource>[];
      pickChatPhoto = (src) async {
        picked.add(src);
        return PickedPhoto(png, 400, 300);
      };
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await t.tap(find.byKey(const Key('chat-plus')));
      await t.pumpAndSettle();
      expect(find.text('최근 사진'), findsOneWidget);
      expect(find.byKey(const Key('attach-camera')), findsOneWidget);
      final gate = Completer<void>();
      f.delay = gate.future; // 올리기 응답을 붙잡아 진행률을 본다(S7b)
      await t.tap(find.byKey(const Key('attach-camera')));
      await t.pump();
      await settle(t, 4);
      expect(find.byType(ChatAttachSheet), findsOneWidget); // 시트는 그대로
      await closeSheet(t);
      expect(find.text('올리는 중 100%'), findsOneWidget); // 본문 바이트를 다 흘림 · 서버 처리 대기(§10.13 #5)
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      gate.complete();
      await settle(t, 10);
      expect(picked, [PhotoSource.camera]);
      final up = f.where('POST', '/api/chat/photos').single;
      expect(up.headers['Content-Type'], startsWith('multipart/form-data; boundary='));
      expect(up.headers['Authorization'], 'Bearer t');
      final body = latin1.decode(up.bodyBytes);
      expect(body, contains('name="roomId"\r\n\r\n1\r\n'));
      expect(body, contains('name="width"\r\n\r\n400\r\n'));
      expect(body, contains('name="height"\r\n\r\n300\r\n'));
      expect(body, contains('filename="photo.jpg"\r\nContent-Type: image/jpeg'));
      final sent = jsonDecode(f.where('POST', '/api/chat/rooms/1/messages').single.body) as Map;
      expect(sent['photoId'], 501);
      expect(sent.containsKey('text'), isFalse);
      expect(app.chat.photos.get(501), isNotNull); // 올린 바이트를 그대로 캐시(다시 받지 않음)
      // 누르면 크게 보기 — [닫기] · 보낸 사람 · 시각 · 저장 · 공유 없음
      await t.tap(find.byType(Image).last);
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-viewer-close')), findsOneWidget);
      expect(find.text('가간호'), findsOneWidget);
      // F10 — 머리 좌우 칸 같은 폭 = 보낸 사람이 화면 가운데
      expect(t.getCenter(find.text('가간호')).dx, closeTo(t.view.physicalSize.width / t.view.devicePixelRatio / 2, 0.5));
      expect(find.textContaining('저장'), findsNothing);
      expect(find.textContaining('공유'), findsNothing);
      expect(app.chat.watching, isNull); // 루트 위 화면 = 보고 있는 방 아님(W2-4)
      await t.tap(find.byKey(const Key('chat-viewer-close')));
      await t.pumpAndSettle();
      expect(app.chat.watching, 1);
      await teardown(t, app);
    });

    testWidgets('올리기 실패 → [다시 보내기] · 올라간 뒤 보내기만 실패면 photoId 로 보내기만 다시', (t) async {
      pickChatPhoto = (_) async => PickedPhoto(png, 10, 10);
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      f.override['POST /api/chat/rooms/1/messages'] = (_) => http.Response('{}', 502);
      await t.tap(find.byKey(const Key('chat-plus')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('attach-camera')));
      await t.pump();
      await settle(t, 10);
      await closeSheet(t);
      expect(find.text('보내지 못했어요'), findsOneWidget);
      f.override.remove('POST /api/chat/rooms/1/messages');
      await t.tap(find.text('다시 보내기'));
      await settle(t, 10);
      expect(f.where('POST', '/api/chat/photos'), hasLength(1)); // 다시 올리지 않음
      expect(f.where('POST', '/api/chat/rooms/1/messages'), hasLength(2));
      await teardown(t, app);
    });

    testWidgets('권한 거부 → 토스트 「설정에서 카메라(사진) 권한을 켜 주세요」', (t) async {
      pickChatPhoto = (_) async => throw const PhotoDenied();
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await t.tap(find.byKey(const Key('chat-plus')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('attach-camera')));
      await t.pump();
      await settle(t, 2);
      expect(app.toaster.text, '설정에서 카메라(사진) 권한을 켜 주세요');
      await teardown(t, app);
    });

    test('사진 메모리 캐시 — 최근 100장(LRU) · 디스크 없음', () {
      final c = PhotoCache();
      for (var i = 0; i < 101; i++) {
        c.put(i, Uint8List(1));
      }
      expect(c.length, 100);
      expect(c.get(0), isNull);
      c.get(1);
      c.put(200, Uint8List(1));
      expect(c.get(1), isNotNull); // 최근에 본 것은 남음
      expect(c.get(2), isNull);
    });
  });
}
