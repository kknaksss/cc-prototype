// WP-APP7(r5) — 사진 · 동영상 모아보기(§10.16 · D9-67) · 초대(§10.9 · §10.17 · D9-68) · 들어온 뒤 대화만(§4.6 · D9-69 · 처분 W-3 · W-4)
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:procedure_app/screens/chat_media_screen.dart';
import 'package:procedure_app/screens/chat_video_screen.dart';
import 'package:procedure_app/widgets/ui.dart' show MsButton;
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_app2_test.dart' show chatTab, openRoom;
import 'chat_fixture.dart';
import 'scan_test.dart' show png;

Map<String, dynamic> photoMsg(int id, int room, {int pid = 0, String at = t0}) =>
    msgJ(id, room, kind: 'photo', text: null, photo: {'id': pid == 0 ? 500 + id : pid, 'width': 400, 'height': 300}, at: at);
Map<String, dynamic> videoMsg(int id, int room, {int ms = 65000}) =>
    msgJ(id, room, kind: 'video', text: null, video: {'id': 700 + id, 'width': 720, 'height': 1280, 'durationMs': ms});

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> openInfo(WidgetTester t) async {
    await t.tap(find.byTooltip('방 정보'));
    await t.pumpAndSettle();
  }

  Future<void> openMedia(WidgetTester t) async {
    await openInfo(t);
    await t.tap(find.byKey(const Key('chat-media')));
    await t.pumpAndSettle();
    await settle(t, 6);
  }

  List<int> cells() => [
        for (final e in find.byWidgetPredicate((w) => w.key is ValueKey<String> && (w.key as ValueKey<String>).value.startsWith('chat-media-') && w is GestureDetector).evaluate())
          int.parse(((e.widget.key as ValueKey<String>).value).substring('chat-media-'.length))
      ];

  group('사진 · 동영상 모아보기(§10.16)', () {
    testWidgets('방 정보 「사진 · 동영상」 줄(그룹 · 1:1 · 알림 아래 · 참여자 위) → 격자 3열 · 최근 것 왼쪽 위 · 사진 칸 · 동영상 칸(▶ · m:ss) · 텍스트 없음', (t) async {
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)]
        ..messages[1] = [photoMsg(1, 1), msgJ(2, 1, text: '글'), videoMsg(3, 1), photoMsg(4, 1), photoMsg(5, 1, at: t0)..['deletedAt'] = t0];
      final app = await openRoom(t, f, '나의사');
      await openInfo(t);
      final row = t.getRect(find.byKey(const Key('chat-media')));
      expect(row.top, greaterThan(t.getRect(find.byKey(const Key('chat-mute'))).bottom));
      expect(row.bottom, lessThan(t.getRect(find.text('참여자 2명')).top));
      expect(find.text('사진 · 동영상'), findsOneWidget);
      await t.tap(find.byKey(const Key('chat-media')));
      await t.pumpAndSettle();
      await settle(t, 6);
      expect(find.text('방 정보'), findsWidgets); // 머리 「‹ 방 정보 · 사진 · 동영상」
      final get = f.where('GET', '/api/chat/rooms/1/attachments').single;
      expect(get.url.queryParameters['limit'], '60');
      expect(get.headers['Authorization'], 'Bearer t');
      expect(cells(), [4, 3, 1]); // 최근 위 · 글 · 지운 것 없음
      final grid = t.widget<GridView>(find.byKey(const Key('chat-media-grid')));
      expect((grid.gridDelegate as SliverGridDelegateWithFixedCrossAxisCount).crossAxisCount, 3);
      final a = t.getRect(find.byKey(const Key('chat-media-4'))), b = t.getRect(find.byKey(const Key('chat-media-3')));
      expect(a.width, closeTo(a.height, 0.5)); // 정사각
      expect(a.top, b.top); // 한 줄에
      expect(find.text('1:05'), findsOneWidget); // 동영상 길이
      expect(f.where('GET', '/api/chat/photos/504'), hasLength(1)); // 사진 칸 = Bearer · 메모리 캐시
      expect(f.where('GET', '/api/chat/videos/703/thumbnail'), hasLength(1));
      // 길게 누르기 = 메뉴 없음
      await t.longPress(find.byKey(const Key('chat-media-4')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-menu-share')), findsNothing);
      expect(find.byKey(const Key('chat-delete-menu')), findsNothing);
      await teardown(t, app);
    });

    testWidgets('빈 상태 「아직 주고받은 사진 · 동영상이 없어요」 · 실패 = 「사진 · 동영상을 불러오지 못했어요」 + [다시 시도]', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      f.override['GET /api/chat/rooms/1/attachments'] = (_) => http.Response('{}', 502);
      final app = await openRoom(t, f, '나의사');
      await openMedia(t);
      expect(find.text('사진 · 동영상을 불러오지 못했어요'), findsOneWidget);
      f.override.remove('GET /api/chat/rooms/1/attachments');
      await t.tap(find.byKey(const Key('chat-media-retry')));
      await settle(t, 6);
      expect(find.text('아직 주고받은 사진 · 동영상이 없어요'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('끝에 닿으면 before=<가장 오래된 id> 로 60 더 · hasMore:false 면 멈춤', (t) async {
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)]
        ..messages[1] = [for (var i = 1; i <= 70; i++) photoMsg(i, 1)];
      final app = await openRoom(t, f, '나의사');
      await openMedia(t);
      expect(cells().length, greaterThan(0));
      await t.drag(find.byKey(const Key('chat-media-grid')), const Offset(0, -6000));
      await settle(t, 6);
      await t.drag(find.byKey(const Key('chat-media-grid')), const Offset(0, -6000));
      await settle(t, 6);
      final gets = f.where('GET', '/api/chat/rooms/1/attachments');
      expect(gets, hasLength(2));
      expect(gets.last.url.queryParameters['before'], '11'); // 첫 60 = 70 ~ 11
      await teardown(t, app);
    });

    testWidgets('칸 누름 = 크게 보기 · 재생(전체 화면) · 그새 지워짐(404) = 토스트 + 칸 뺌', (t) async {
      final saved = buildChatVideoPlayer;
      addTearDown(() => buildChatVideoPlayer = saved);
      buildChatVideoPlayer = (u, h, thumb, onReady) => const SizedBox(key: Key('fake-player'));
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)]
        ..messages[1] = [photoMsg(1, 1), videoMsg(2, 1), photoMsg(3, 1, pid: 999)];
      // 그새 지워진 사진(대화 말풍선도 못 받음 — 캐시에 없음)
      f.override['GET /api/chat/photos/999'] = (_) => http.Response(jsonEncode({'error': {'code': 'chat_photo_not_found', 'message': '없음'}}), 404, headers: jsonHeaders);
      final app = await openRoom(t, f, '나의사');
      await openMedia(t);
      await t.tap(find.byKey(const Key('chat-media-1')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-viewer-close')), findsOneWidget); // 크게 보기
      expect(find.textContaining('저장'), findsNothing);
      await t.tap(find.byKey(const Key('chat-viewer-close')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-media-2')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('fake-player')), findsOneWidget); // 재생
      await t.tap(find.byKey(const Key('chat-video-close')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-media-3')));
      await settle(t, 4);
      await t.pumpAndSettle();
      expect(app.toaster.text, '사진을 찾을 수 없어요');
      expect(cells(), [2, 1]);
      await teardown(t, app);
    });

    testWidgets('바로 고침 — SSE 새 사진 · 동영상 = 맨 앞 · 다른 방 · 글 = 그대로 · 지움 = 뺌 · 로그아웃 = 비움', (t) async {
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1), roomJ(2, members: [meM, coordM])]
        ..messages[1] = [photoMsg(1, 1)];
      final app = await openRoom(t, f, '나의사');
      await openMedia(t);
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': videoMsg(9, 1)});
      app.chat.onEvent('chat_message', {'roomId': 2, 'message': photoMsg(10, 2)});
      app.chat.onEvent('chat_message', {'roomId': 1, 'message': msgJ(11, 1, text: '글')});
      await t.pump();
      expect(cells(), [9, 1]);
      app.chat.onEvent('chat_message_deleted', {'roomId': 1, 'messageId': 1, 'updatedAt': t0});
      await t.pump();
      expect(cells(), [9]);
      app.chat.clear(keepOpen: false);
      await t.pump();
      expect(cells(), isEmpty);
      await teardown(t, app);
    });

    testWidgets('아이패드 — 방 정보 오른쪽 시트 안에서 격자로 넘어감 · [‹ 방 정보]로 돌아감(처분 W-3)', (t) async {
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)]
        ..messages[1] = [photoMsg(1, 1)];
      final app = chatApp(f);
      ipad(t);
      await t.pumpWidget(chatTab(app));
      await settle(t);
      await t.tap(find.text('나의사').first);
      await t.pumpAndSettle();
      await settle(t);
      await openInfo(t);
      await t.tap(find.byKey(const Key('chat-media')));
      await t.pumpAndSettle();
      await settle(t, 6);
      final grid = t.getRect(find.byType(ChatMediaScreen));
      expect(grid.width, closeTo(420, 0.5)); // 시트 폭 그대로
      expect(cells(), [1]);
      await t.tap(find.text('방 정보').first);
      await t.pumpAndSettle();
      expect(find.byType(ChatMediaScreen), findsNothing);
      expect(find.byKey(const Key('chat-media')), findsOneWidget); // 시트 안 방 정보로 돌아옴
      await teardown(t, app);
    });
  });

  group('초대(§10.9 · §10.17)', () {
    testWidgets('1:1 [+ 초대] → 머리 「초대」 · 상대 = 이미 참여 중 · 「N명 선택 · 나 포함 N+2명」 → POST rooms {accountIds:[상대, …]} 제목 없음 → 새 그룹 대화가 열림 · 1:1 남음', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await openInfo(t);
      expect(find.textContaining('그룹을 만들어요'), findsNothing); // 안내 줄 없음
      await t.tap(find.byKey(const Key('chat-invite')));
      await t.pumpAndSettle();
      await settle(t);
      expect(find.text('초대'), findsWidgets);
      expect(find.text('이미 참여 중'), findsOneWidget); // 나의사
      expect(find.text('0명 선택 · 나 포함 2명 · 최대 20명'), findsOneWidget);
      expect(find.byKey(const Key('chat-group-title')), findsNothing); // 이름 입력 없음
      await t.tap(find.text('라상담'));
      await t.tap(find.text('다코디'));
      await t.pump();
      expect(find.text('2명 선택 · 나 포함 4명 · 최대 20명'), findsOneWidget);
      await t.tap(find.widgetWithText(MsButton, '초대'));
      await settle(t, 8);
      await t.pumpAndSettle();
      await settle(t, 4);
      final body = jsonDecode(f.where('POST', '/api/chat/rooms').single.body) as Map;
      expect(body, {'accountIds': [2, 4, 3]}); // 상대 먼저 · 고른 차례 · 제목 없음
      final newId = f.rooms.last['id'] as int;
      expect(app.chat.room(1), isNotNull); // 1:1 그대로
      expect(app.chat.room(newId)!.group, isTrue);
      expect(find.byKey(const Key('chat-input')), findsOneWidget); // 새 그룹 대화
      expect(find.text('나의사, 라상담, 다코디'), findsWidgets);
      await teardown(t, app);
    });

    testWidgets('비활성 상대 1:1 = [+ 초대] 없음 · 1:1 초대 18명 상한', (t) async {
      final f = FakeChat()..rooms = [roomJ(3, members: [meM, offM])];
      final app = await openRoom(t, f, '마관리');
      await openInfo(t);
      expect(find.byKey(const Key('chat-invite')), findsNothing);
      await teardown(t, app);
    });

    testWidgets('1:1 초대 = 18명까지(20 − 나 − 상대)', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1)]
        ..people = [docM, for (var i = 0; i < 20; i++) {'id': 100 + i, 'name': '직원${i.toString().padLeft(2, '0')}', 'role': 'nurse'}];
      final app = await openRoom(t, f, '나의사');
      await openInfo(t);
      await t.tap(find.byKey(const Key('chat-invite')));
      await t.pumpAndSettle();
      await settle(t);
      for (var i = 0; i < 19; i++) {
        final k = find.text('직원${i.toString().padLeft(2, '0')}', skipOffstage: false);
        await t.ensureVisible(k);
        await t.tap(k);
        await t.pump();
      }
      expect(find.text('18명 선택 · 나 포함 20명 · 최대 20명'), findsOneWidget);
      await teardown(t, app);
    });
  });

  group('들어온 뒤 대화만(§4.6 · D9-69)', () {
    testWidgets('나감(chat_room_removed) → 그 방 메모리 없음 → 다시 초대(chat_room) → 대화 열면 서버에서 처음부터(since 없이) · 옛 메시지 화면에 없음', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM])]
        ..messages[2] = [msgJ(20, 2, text: '옛 메시지')];
      final app = await openRoom(t, f, '4층 시술실');
      expect(find.text('옛 메시지'), findsOneWidget);
      app.chat.onEvent('chat_room_removed', {'roomId': 2});
      await t.pumpAndSettle();
      expect(app.chat.threads[2]?.byId.isEmpty ?? true, isTrue); // 옛 메시지 메모리 없음(닫히는 대화가 빈 칸을 다시 만들 수는 있음)
      // 다시 초대 — 서버는 들어온 뒤 것만 준다(경계 = 그 순간 마지막 id)
      f.messages[2] = [msgJ(30, 2, kind: 'system', text: '나의사님이 가간호님을 초대했습니다')];
      app.chat.onEvent('chat_room', {'room': roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM])});
      await t.pump();
      await t.tap(find.text('4층 시술실').first);
      await t.pumpAndSettle();
      await settle(t);
      final last = f.where('GET', '/api/chat/rooms/2/messages').last;
      expect(last.url.queryParameters.containsKey('since'), isFalse);
      expect(find.text('옛 메시지'), findsNothing);
      expect(find.text('나의사님이 가간호님을 초대했습니다'), findsOneWidget); // 새 시스템 줄 문구 그대로 그림
      await teardown(t, app);
    });

    testWidgets('멤버가 바뀐 방(내 chat_room) = 열려 있지 않으면 다음에 열 때 처음부터(처분 W-4)', (t) async {
      final f = FakeChat()
        ..rooms = [roomJ(1), roomJ(2, group: true, title: '4층 시술실', members: [meM, docM])]
        ..messages[2] = [msgJ(20, 2, text: '옛 메시지')];
      final app = await openRoom(t, f, '4층 시술실');
      Navigator.of(t.element(find.byKey(const Key('chat-input')))).pop();
      await t.pumpAndSettle();
      expect(app.chat.thread(2).loaded, isTrue);
      app.chat.onEvent('chat_room', {'room': roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM])});
      expect(app.chat.thread(2).loaded, isFalse);
      expect(app.chat.thread(2).byId, isEmpty);
      // 알림 끄기처럼 멤버가 그대로인 chat_room 은 그대로
      app.chat.thread(1).loaded = true;
      app.chat.onEvent('chat_room', {'room': roomJ(1, muted: true)});
      expect(app.chat.thread(1).loaded, isTrue);
      await teardown(t, app);
    });
  });
}
