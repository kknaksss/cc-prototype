// WP-APP5(r3) — 길게 누르기 5메뉴 · 복사 · 선택 복사 · 수정 · 링크 · SSE chat_message_edited(SPEC-007 §5 · §7 · §10.4 · §10.7 · §13.2 r3).
// r4: [공유] = 앱 안 전달 — 시스템 공유 시험은 chat_app6_test.dart(전달 시트)로 옮김. 링크 열기는 가짜로 바꿔 끼운다
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:procedure_app/chat/chat_model.dart';
import 'package:procedure_app/chat/chat_link.dart';
import 'package:procedure_app/chat/chat_view.dart';
import 'package:procedure_app/screens/chat_room_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_app2_test.dart' show openRoom;
import 'chat_fixture.dart';
import 'scan_test.dart' show png;

ChatMessage msg(Map<String, dynamic> j) => ChatMessage.fromJson(j);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  late LinkOpener savedLink;
  final opened = <Uri>[];
  setUp(() {
    savedLink = openChatLink;
    opened.clear();
    openChatLink = (u) async => opened.add(u);
  });
  tearDown(() => openChatLink = savedLink);

  List<String> menuShown() => [
        for (final m in ChatMenu.values)
          if (find.byKey(Key(m == ChatMenu.delete ? 'chat-delete-menu' : 'chat-menu-${m.name}')).evaluate().isNotEmpty) m.label
      ];

  Future<void> closeMenu(WidgetTester t) async {
    await t.tapAt(const Offset(5, 5));
    await t.pumpAndSettle();
  }

  group('길게 누르기 메뉴(§10.7 · D9-54)', () {
    test('메뉴 표 다섯 줄 — 내 텍스트 · 남의 텍스트 · 내 사진 · 동영상 · 남의 사진 · 동영상 · 시스템 · 지움 · 비활성 1:1 = [수정] 숨김(FAIL-2)', () {
      final text = msg(msgJ(1, 1));
      final photo = msg(msgJ(2, 1, kind: 'photo', text: null, photo: {'id': 5, 'width': 1, 'height': 1}));
      final video = msg(msgJ(3, 1, kind: 'video', text: null, video: {'id': 6, 'width': 1, 'height': 1, 'durationMs': 1000}));
      final sys = msg(msgJ(4, 1, kind: 'system', text: '나의사 님이 나갔어요'));
      final gone = msg(msgJ(5, 1, deletedAt: t0));
      const c = ChatMenu.copy, s = ChatMenu.select, sh = ChatMenu.share, e = ChatMenu.edit, d = ChatMenu.delete;
      expect(chatMenuOf(text, mine: true), [c, s, sh, e, d]);
      expect(chatMenuOf(text, mine: false), [c, s, sh]);
      expect(chatMenuOf(photo, mine: true), [sh, d]);
      expect(chatMenuOf(video, mine: true), [sh, d]);
      expect(chatMenuOf(photo, mine: false), [sh]);
      expect(chatMenuOf(video, mine: false), [sh]);
      expect(chatMenuOf(sys, mine: true), isEmpty);
      expect(chatMenuOf(gone, mine: true), isEmpty);
      expect(chatMenuOf(text, mine: true, peerInactive: true), [c, s, sh, d]);
      expect([for (final m in ChatMenu.values) m.label], ['복사', '선택 복사', '공유', '수정', '삭제']);
    });

    testWidgets('화면 — 내 글 = 5줄 · 남의 글 = 3줄(남의 것도 떠오름) · 내 사진 = 공유 · 삭제 · 시스템 · 지운 것 · 보내는 중 = 메뉴 없음 · 비활성 1:1 = 수정 없음', (t) async {
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1, last: preview(5))]
        ..messages[1] = [
          msgJ(1, 1, text: '상대 글'),
          msgJ(2, 1, sender: 1, senderName: '가간호', text: '내 글'),
          msgJ(3, 1, sender: 1, senderName: '가간호', kind: 'photo', text: null, photo: {'id': 50, 'width': 400, 'height': 300}),
          msgJ(4, 1, kind: 'system', text: '시스템 줄'),
          msgJ(5, 1, deletedAt: t0),
        ];
      final app = await openRoom(t, f, '나의사');
      await t.longPress(find.text('내 글'));
      await t.pumpAndSettle();
      expect(menuShown(), ['복사', '선택 복사', '공유', '수정', '삭제']);
      await closeMenu(t);
      await t.longPress(find.text('상대 글'));
      await t.pumpAndSettle();
      expect(menuShown(), ['복사', '선택 복사', '공유']);
      expect(find.text('상대 글'), findsNWidgets(2)); // 떠오른 복사본
      // 상대 메뉴 = 왼쪽 맞춤
      expect(t.getRect(find.byKey(const Key('chat-menu-copy'))).left, lessThan(200));
      await closeMenu(t);
      await t.longPress(find.byKey(const Key('chat-msg-3')));
      await t.pumpAndSettle();
      expect(menuShown(), ['공유', '삭제']);
      await closeMenu(t);
      await t.longPress(find.text('시스템 줄'));
      await t.pumpAndSettle();
      expect(menuShown(), isEmpty);
      await t.longPress(find.text('삭제된 메시지예요'));
      await t.pumpAndSettle();
      expect(menuShown(), isEmpty);
      await teardown(t, app);
    });

    testWidgets('비활성 1:1(입력줄 없음 · D9-42) — [수정] 숨김 · 복사 · 선택 복사 · 공유 · 삭제 그대로(FAIL-2)', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(3, members: [meM, offM], last: preview(31, sender: 1, mine: true))]
        ..messages[3] = [msgJ(31, 3, sender: 1, senderName: '가간호', text: '옛 내 글')];
      final app = await openRoom(t, f, '마관리');
      expect(find.byKey(const Key('chat-inactive')), findsOneWidget);
      await t.longPress(find.text('옛 내 글'));
      await t.pumpAndSettle();
      expect(menuShown(), ['복사', '선택 복사', '공유', '삭제']);
      await closeMenu(t);
      await teardown(t, app);
    });

    testWidgets('보내는 중 말풍선 = 길게 눌러도 메뉴 없음', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      f.override['POST /api/chat/rooms/1/messages'] = (_) => http.Response('{}', 502);
      await t.enterText(find.byKey(const Key('chat-input')), '못 간 글');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-send')));
      await settle(t, 6);
      expect(find.text('보내지 못했어요'), findsOneWidget);
      await t.longPress(find.text('못 간 글'));
      await t.pumpAndSettle();
      expect(menuShown(), isEmpty);
      await teardown(t, app);
    });
  });

  group('복사 · 선택 복사', () {
    testWidgets('[복사] = 본문 전체 클립보드 + 토스트 「복사했어요」 · [선택 복사] = 시트에 본문 · 처음부터 전부 골라 둠 · [닫기]', (t) async {
      final clip = <String>[];
      t.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') clip.add((call.arguments as Map)['text'] as String);
        return null;
      });
      addTearDown(() => t.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
      final f = FakeChat()
        ..rooms = [roomJ(1)]
        ..messages[1] = [msgJ(1, 1, text: '마취 크림 2시에\n바를게요')];
      final app = await openRoom(t, f, '나의사');
      await t.longPress(find.text('마취 크림 2시에\n바를게요'));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-menu-copy')));
      await t.pumpAndSettle();
      expect(clip, ['마취 크림 2시에\n바를게요']);
      expect(app.toaster.text, '복사했어요');
      await t.longPress(find.text('마취 크림 2시에\n바를게요'));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-menu-select')));
      await t.pumpAndSettle();
      expect(find.text('선택 복사'), findsOneWidget);
      final field = t.widget<TextField>(find.byKey(const Key('chat-select-text')));
      expect(field.readOnly, isTrue);
      expect(field.controller!.text, '마취 크림 2시에\n바를게요');
      expect(field.controller!.selection, TextSelection(baseOffset: 0, extentOffset: '마취 크림 2시에\n바를게요'.length));
      await t.tap(find.byKey(const Key('chat-select-close')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-select-text')), findsNothing);
      await teardown(t, app);
    });
  });

  group('수정(D9-55)', () {
    testWidgets('[수정] → 「메시지 수정」 줄 + [✕] · 원문 · [+] 꺼짐 · [저장](같거나 비면 꺼짐) → PATCH {text} · 「수정됨」 · since = 서버 updatedAt', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1, last: preview(2, sender: 1, mine: true, text: '3시에 와요'))]
        ..messages[1] = [msgJ(2, 1, sender: 1, senderName: '가간호', text: '3시에 와요')];
      final app = await openRoom(t, f, '나의사');
      await t.longPress(find.text('3시에 와요'));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-menu-edit')));
      await t.pumpAndSettle();
      expect(find.text('메시지 수정'), findsOneWidget);
      expect(find.byKey(const Key('chat-edit-cancel')), findsOneWidget);
      expect(t.widget<TextField>(find.byKey(const Key('chat-input'))).controller!.text, '3시에 와요');
      expect(t.widget<IconButton>(find.byKey(const Key('chat-plus'))).onPressed, isNull);
      expect(find.byKey(const Key('chat-send')), findsNothing);
      await t.tap(find.byKey(const Key('chat-save')));
      expect(f.where('PATCH', '/api/chat/messages/2'), isEmpty); // 원문과 같음 = 꺼짐
      await t.enterText(find.byKey(const Key('chat-input')), '   ');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-save')));
      expect(f.where('PATCH', '/api/chat/messages/2'), isEmpty); // 비면 꺼짐
      await t.enterText(find.byKey(const Key('chat-input')), '4시에 와요');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-save')));
      await settle(t, 6);
      expect(jsonDecode(f.where('PATCH', '/api/chat/messages/2').single.body), {'text': '4시에 와요'});
      expect(find.text('4시에 와요'), findsOneWidget);
      expect(find.byKey(const Key('chat-edited')), findsOneWidget);
      expect(find.text('수정됨'), findsOneWidget);
      expect(find.text('메시지 수정'), findsNothing); // 수정 모드 끝
      expect(t.widget<TextField>(find.byKey(const Key('chat-input'))).controller!.text, isEmpty);
      expect(app.chat.room(1)!.lastMessage!.text, '4시에 와요'); // 미리보기 글
      // since 원천 = 서버가 준 updatedAt(PATCH 응답 — W-6) · 앱 시각 아님
      expect(app.chat.thread(1).latestUpdatedAt, '2026-10-29T15:00:00.456+09:00');
      await app.chat.catchUp();
      expect(f.where('GET', '/api/chat/rooms/1/messages').last.url.queryParameters['since'], '2026-10-29T15:00:00.456+09:00');
      await teardown(t, app);
    });

    testWidgets('[✕] = 수정 취소(입력칸 비움) · 실패 = 4xx 토스트 message · 네트워크 · 5xx 「고치지 못했어요」 · 수정 모드 그대로', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1)]
        ..messages[1] = [msgJ(2, 1, sender: 1, senderName: '가간호', text: '원문')];
      final app = await openRoom(t, f, '나의사');
      Future<void> edit() async {
        await t.longPress(find.text('원문').last);
        await t.pumpAndSettle();
        await t.tap(find.byKey(const Key('chat-menu-edit')));
        await t.pumpAndSettle();
      }

      await edit();
      await t.tap(find.byKey(const Key('chat-edit-cancel')));
      await t.pump();
      expect(find.text('메시지 수정'), findsNothing);
      expect(t.widget<TextField>(find.byKey(const Key('chat-input'))).controller!.text, isEmpty);
      expect(find.byKey(const Key('chat-send')), findsOneWidget);
      await edit();
      await t.enterText(find.byKey(const Key('chat-input')), '새 글');
      await t.pump();
      f.override['PATCH /api/chat/messages/2'] =
          (_) => http.Response(jsonEncode({'error': {'code': 'chat_not_editable', 'message': '글만 고칠 수 있어요'}}), 400, headers: jsonHeaders);
      await t.tap(find.byKey(const Key('chat-save')));
      await settle(t, 4);
      expect(app.toaster.text, '글만 고칠 수 있어요');
      expect(find.text('메시지 수정'), findsOneWidget);
      f.override['PATCH /api/chat/messages/2'] = (_) => http.Response('{}', 502);
      await t.tap(find.byKey(const Key('chat-save')));
      await settle(t, 4);
      expect(app.toaster.text, '고치지 못했어요');
      expect(find.text('메시지 수정'), findsOneWidget);
      expect(find.text('원문'), findsWidgets); // 말풍선은 원문 그대로 · 실패 말풍선 없음
      expect(find.text('보내지 못했어요'), findsNothing);
      await teardown(t, app);
    });

    testWidgets('SSE chat_message_edited — 같은 id 바꿔 끼움 · 「수정됨」 · 미리보기 글 · 안 읽음 · 배지 · 배너 · 방 순서 그대로 · 더 옛 값은 안 덮음', (t) async {
      final f = FakeChat()
        ..rooms = [
          roomJ(1, last: preview(9, text: '처음 글', at: '2026-10-29T14:00:00.000+09:00')),
          roomJ(2, members: [meM, coordM], unread: 2, last: preview(9, sender: 3, senderName: '다코디', text: '처음 글', at: '2026-10-29T13:00:00.000+09:00')),
        ]
        ..messages[1] = [msgJ(9, 1, text: '처음 글', at: '2026-10-29T14:00:00.000+09:00')];
      final app = await openRoom(t, f, '나의사');
      final order = [for (final r in app.chat.rooms) r.id];
      final edited = msgJ(9, 1, text: '고친 글', at: '2026-10-29T14:00:00.000+09:00', editedAt: '2026-10-29T15:10:00.000+09:00');
      app.chat.onEvent('chat_message_edited', {'roomId': 1, 'message': edited});
      await t.pump();
      expect(find.text('고친 글'), findsOneWidget);
      expect(find.text('처음 글'), findsNothing);
      expect(find.text('수정됨'), findsOneWidget);
      expect(app.chat.room(1)!.lastMessage!.text, '고친 글');
      expect(app.chat.thread(1).latestUpdatedAt, '2026-10-29T15:10:00.000+09:00');
      // 남의 방 수정 — 안 읽음 · 배지 · 배너 · 순서 그대로
      app.chat.onEvent('chat_message_edited', {
        'roomId': 2,
        'message': msgJ(9, 2, sender: 3, senderName: '다코디', role: 'coordinator', text: '고친 남의 글', at: '2026-10-29T13:00:00.000+09:00', editedAt: '2026-10-29T15:11:00.000+09:00'),
      });
      expect(app.chat.room(2)!.unread, 2);
      expect(app.chat.unreadRooms.value, 1);
      expect(app.chat.banner.value, isNull);
      expect([for (final r in app.chat.rooms) r.id], order);
      expect(app.chat.room(2)!.lastMessage!.text, '고친 남의 글');
      // 늦게 온 옛 값(updatedAt 더 이름)은 덮지 않는다
      app.chat.onEvent('chat_message_edited', {'roomId': 1, 'message': msgJ(9, 1, text: '옛 고침', editedAt: '2026-10-29T15:00:00.000+09:00')});
      await t.pump();
      expect(find.text('고친 글'), findsOneWidget);
      await teardown(t, app);
    });
  });

  group('링크(D9-46 · U-3)', () {
    test('찾기 — http(s) 만 · ASCII 주소 문자까지(한글에서 끊음) · 끝 문장부호 빠짐 · www. · 메일 = 글자', () {
      List<String> links(String s) => [for (final l in findLinks(s)) s.substring(l.start, l.end)];
      expect(links('https://example.com에서 봐요'), ['https://example.com']);
      expect(links('자료 http://a.example/b?c=1&d=2. 확인'), ['http://a.example/b?c=1&d=2']);
      expect(links('(https://x.example/y)'), ['https://x.example/y']);
      expect(links('「https://x.example」'), ['https://x.example']);
      expect(links('봐요 https://x.example/a!? 네'), ['https://x.example/a']);
      expect(links('"https://x.example/q"'), ['https://x.example/q']);
      expect(links('두 개 https://a.example 와 http://b.example/c'), ['https://a.example', 'http://b.example/c']);
      expect(links('www.example.com · a@b.example · ftp://x · https://'), isEmpty);
    });

    testWidgets('말풍선 — 밑줄 · 누르면 기기 브라우저(openChatLink) · 길게 누르면 말풍선 메뉴', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1)]
        ..messages[1] = [msgJ(1, 1, text: '여기 https://example.com에서 봐요')];
      final app = await openRoom(t, f, '나의사');
      final rich = t.widget<RichText>(find.descendant(of: find.byKey(const Key('chat-link-text')), matching: find.byType(RichText)));
      final spans = <TextSpan>[];
      rich.text.visitChildren((s) {
        if (s is TextSpan && s.text != null) spans.add(s);
        return true;
      });
      final link = spans.firstWhere((s) => s.text == 'https://example.com');
      expect(link.style!.decoration, TextDecoration.underline);
      expect(spans.map((s) => s.text), ['여기 ', 'https://example.com', '에서 봐요']);
      (link.recognizer! as dynamic).onTap();
      expect(opened, [Uri.parse('https://example.com')]);
      await t.longPress(find.byKey(const Key('chat-msg-1')));
      await t.pumpAndSettle();
      expect(menuShown(), ['복사', '선택 복사', '공유']);
      await closeMenu(t);
      await teardown(t, app);
    });
  });
}
