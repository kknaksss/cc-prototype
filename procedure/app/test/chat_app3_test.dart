// WORK-011 WP-APP3 — 푸시(PushKind.chat · 누름 · 앞) · 앱 안 배너 거름(보는 방 · 알림 끈 방 · 내 것 · 시스템 줄 · 겹침) ·
// 다른 탭 = 배너 · 읽음 없음(D9-40) · 띄우기 화면 세 길(대기열 QR · 예약 상세 QR · 예약 상세 여권 스캔 — 실제 show* 를 거침 · D9-44 · W2-3) ·
// 생명주기 · 다시 연결 메우기 · 로그아웃 · 계정 바뀜 · 아이패드 두 칸(S13a ~ d) · 방 정보(S10a ~ e)
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/chat/chat_model.dart';
import 'package:procedure_app/chat/chat_state.dart';
import 'package:procedure_app/model/display.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/screens/chat_list_screen.dart';
import 'package:procedure_app/screens/qr_show_screen.dart';
import 'package:procedure_app/screens/reservation_detail_screen.dart';
import 'package:procedure_app/screens/scan_screen.dart';
import 'package:procedure_app/screens/shell.dart';
import 'package:procedure_app/sse/board_stream.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'autosave_test.dart' show detailJson;
import 'chat_fixture.dart';
import 'push_test.dart' show MemStore;
import 'qr_show_test.dart' show fakeUrl;

const pushCh = MethodChannel('procedure/push');

Widget chatTab(AppState app) => AppScope(
      state: app,
      child: MaterialApp(
        navigatorObservers: [app.chat.rootRoutes],
        home: Scaffold(
          body: Navigator(observers: [app.chat.chatRoutes], onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => const ChatScreen())),
        ),
      ),
    );

Map<String, dynamic> ev(int id, int room, {int sender = 2, String name = '나의사', String kind = 'text', String? text = '3번 방 마취 들어갔어요'}) =>
    {'roomId': room, 'message': msgJ(id, room, sender: sender, senderName: name, kind: kind, text: text, at: '2026-10-29T15:0${id % 10}:00.000+09:00')};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('푸시(§8)', () {
    test('PushTap.parse — chat 은 roomId 가 있어야 받음 · 제목 · 본문 · 옛 3종 그대로', () {
      final t = PushTap.parse({'kind': 'chat', 'roomId': '7', 'messageId': 41, 'title': '나의사 · 4층', 'body': '사진'})!;
      expect((t.kind, t.roomId, t.messageId, t.title, t.body), (PushKind.chat, 7, 41, '나의사 · 4층', '사진'));
      expect(PushTap.parse({'kind': 'chat', 'messageId': 41}), isNull);
      expect(PushTap.parse({'visitId': 3})!.kind, PushKind.doctorCall);
      expect(PushTap.parse({'kind': 'counselor_call', 'reservationId': 9})!.kind, PushKind.counselorCall);
      expect(PushTap.parse({'kind': 'display', 'requestId': 2})!.kind, PushKind.display);
      expect(PushTap.parse({'kind': 'display'}), isNull);
    });

    test('누름 → 「채팅」 탭 · 그 방 열기 요청 · 알림 읽음 호출 없음 / 앞에서 받은 채팅 = 앱 안 배너(onTap 아님)', () async {
      messenger.setMockMethodCallHandler(pushCh, (c) async => c.method == 'status' ? 'denied' : null);
      final f = FakeChat()..rooms = [roomJ(7, group: true, title: '4층', members: [meM, docM, coordM])];
      late AppState app;
      final api = Api(base: () => 'http://x', token: () => app.session?.token, client: f.client);
      final push = PushChannel(pushCh);
      app = AppState(store: MemStore([]), api: api, push: push);
      f.override['/api/auth/login'] = (_) => http.Response('{"token":"t","id":"n","role":"nurse","name":"가간호","staffId":null}', 200, headers: jsonHeaders);
      await app.boot();
      await app.login('n', 'pw');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      push.onTap!(const PushTap(PushKind.chat, roomId: 7, messageId: 41));
      expect(app.tab.value, AppTab.chat);
      expect(app.chat.openRequest.value, 7);
      expect(f.where('POST', '/api/notifications/read'), isEmpty);
      // Runner → onForeground(kind = chat) → 배너 원천
      app.tab.value = AppTab.reservations;
      await messenger.handlePlatformMessage('procedure/push',
          const StandardMethodCodec().encodeMethodCall(const MethodCall('onForeground', {'kind': 'chat', 'roomId': 7, 'messageId': 42, 'title': '나의사 · 4층', 'body': '사진'})), (_) {});
      expect(app.chat.banner.value?.line, '나의사 · 4층 — 사진');
      expect(app.tab.value, AppTab.reservations); // 눌러 열기 아님
      app.chat.clear();
      app.stream.dispose();
    });

    test('로그아웃 상태에서 채팅 푸시 누름 → 로그인(계정 바뀜) 뒤에도 그 방 열기 요청이 남음 · 로그아웃은 지움(review-code r1 WARN-1)', () async {
      messenger.setMockMethodCallHandler(pushCh, (c) async => c.method == 'status' ? 'denied' : null);
      final f = FakeChat()..rooms = [roomJ(7, group: true, title: '4층', members: [meM, docM, coordM])];
      late AppState app;
      final api = Api(base: () => 'http://x', token: () => app.session?.token, client: f.client);
      final push = PushChannel(pushCh);
      app = AppState(store: MemStore([]), api: api, push: push);
      f.override['/api/auth/login'] = (_) => http.Response('{"token":"t","id":"n","role":"nurse","name":"가간호","staffId":null}', 200, headers: jsonHeaders);
      await app.boot();
      expect(app.session, isNull);
      push.onTap!(const PushTap(PushKind.chat, roomId: 7, messageId: 41));
      await app.login('n', 'pw'); // session null → 「계정 바뀜」 분기 = chat.clear()
      expect(app.tab.value, AppTab.chat);
      expect(app.chat.openRequest.value, 7);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await app.logout();
      expect(app.chat.openRequest.value, isNull);
      app.stream.dispose();
    });

    testWidgets('누른 방이 내 목록에 없으면(나감) 토스트 「대화방을 찾을 수 없어요」 → 방 목록 · 있으면 그 방 대화', (t) async {
      phone(t);
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = chatApp(f)..tab.value = AppTab.chat;
      await t.pumpWidget(chatTab(app));
      await settle(t);
      app.chat.openRoom(99);
      await settle(t);
      expect(app.toaster.text, '대화방을 찾을 수 없어요');
      app.chat.openRoom(1);
      await settle(t);
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-input')), findsOneWidget);
      await teardown(t, app);
    });
  });

  group('앱 안 배너(§10.12)', () {
    test('거름 — 내 것 · 시스템 줄 · 알림 끈 방 · 같은 messageId(SSE 뒤 푸시 · 푸시 뒤 SSE) · 백그라운드 · 4초 뒤 사라짐', () {
      final f = FakeChat();
      final app = chatApp(f);
      app.chat.onEvent('chat_room', {'room': roomJ(1)});
      app.chat.onEvent('chat_room', {'room': roomJ(2, group: true, title: '4층', members: [meM, docM, coordM], muted: true)});
      app.chat.onEvent('chat_room', {'room': roomJ(3, group: true, members: [meM, docM, coordM])});
      app.chat.onEvent('chat_message', ev(10, 1, sender: 1, name: '가간호'));
      expect(app.chat.banner.value, isNull);
      app.chat.onEvent('chat_message', ev(11, 1, kind: 'system', text: '나의사 님이 나갔어요'));
      expect(app.chat.banner.value, isNull);
      app.chat.onEvent('chat_message', ev(12, 2));
      expect(app.chat.banner.value, isNull);
      app.chat.onEvent('chat_message', ev(13, 1));
      expect(app.chat.banner.value!.line, '나의사 — 3번 방 마취 들어갔어요'); // 1:1 = 보낸 사람
      app.chat.banner.value = null;
      app.chat.offerBanner(const ChatBanner(1, 13, '나의사', '3번 방 마취 들어갔어요')); // 같은 메시지 푸시
      expect(app.chat.banner.value, isNull);
      app.chat.offerBanner(const ChatBanner(3, 14, '나의사 · 나의사, 다코디', '먼저 온 푸시'));
      app.chat.banner.value = null;
      app.chat.onEvent('chat_message', ev(14, 3)); // 같은 메시지 SSE
      expect(app.chat.banner.value, isNull);
      app.chat.onEvent('chat_message', ev(15, 3, kind: 'photo', text: null));
      expect(app.chat.banner.value!.line, '나의사 · 나의사, 다코디 — 사진'); // 그룹 = 「보낸 사람 · 방 이름」
      app.chat.setForeground(false);
      expect(app.chat.banner.value, isNull);
      app.chat.onEvent('chat_message', ev(16, 1));
      expect(app.chat.banner.value, isNull);
      app.chat.clear();
      app.stream.dispose();
    });

    testWidgets('셸 안 층에 뜸 · [보기] → 채팅 탭 그 방 · 4초 뒤 사라짐', (t) async {
      ipad(t);
      final f = FakeChat()..rooms = [roomJ(1, last: preview(1))];
      final app = chatApp(f);
      await t.pumpWidget(AppScope(state: app, child: MaterialApp(navigatorObservers: [app.chat.rootRoutes], home: const Shell())));
      await t.runAsync(() => app.chat.refreshRooms());
      await t.pump();
      app.chat.onEvent('chat_message', ev(20, 1));
      await t.pump();
      expect(find.byKey(const Key('chat-banner')), findsOneWidget);
      expect(find.text('나의사 — 3번 방 마취 들어갔어요'), findsOneWidget);
      await t.tap(find.text('보기'));
      await settle(t);
      await t.pump(const Duration(milliseconds: 400));
      expect(app.tab.value, AppTab.chat);
      expect(find.byKey(const Key('chat-banner')), findsNothing);
      app.chat.onEvent('chat_message', ev(21, 1, sender: 3, name: '다코디'));
      await t.pump();
      expect(find.byKey(const Key('chat-banner')), findsNothing); // 그 방을 보고 있음
      expect(app.chat.watching, 1);
      await teardown(t, app);
    });

    testWidgets('대화를 연 채 다른 탭 = 보고 있는 방 아님 → 배너 뜸 · 읽음 없음 · 채팅 탭으로 돌아오면 읽음(D9-40)', (t) async {
      phone(t);
      final f = FakeChat()
        ..rooms = [roomJ(1, last: preview(1))]
        ..messages[1] = [msgJ(1, 1)];
      final app = chatApp(f)..tab.value = AppTab.chat;
      await t.pumpWidget(chatTab(app));
      await settle(t);
      await t.tap(find.text('나의사'));
      await t.pumpAndSettle();
      await settle(t);
      expect(f.where('POST', '/api/chat/rooms/1/read'), hasLength(1));
      app.tab.value = AppTab.reservations;
      await t.pump();
      app.chat.onEvent('chat_message', ev(2, 1));
      await t.pump(const Duration(milliseconds: 1500));
      await settle(t);
      expect(app.chat.banner.value, isNotNull);
      expect(app.chat.room(1)!.unread, 1);
      expect(f.where('POST', '/api/chat/rooms/1/read'), hasLength(1)); // 읽음 안 보냄
      app.tab.value = AppTab.chat;
      await settle(t);
      expect(jsonDecode(f.where('POST', '/api/chat/rooms/1/read').last.body), {'messageId': 2});
      expect(app.chat.room(1)!.unread, 0);
      await teardown(t, app);
    });
  });

  // W2-3 — openQrScreen · openPassportScan 을 바꿔 끼우지 않고 실제 showQrScreen · showPassportScan 을 거친다
  group('띄우기 화면 중 배너 없음 — 세 길(D9-44)', () {
    Future<void> expectBlocked(WidgetTester t, AppState app, int id) async {
      expect(openDisplayScreens.value, 1);
      app.chat.onEvent('chat_message', ev(id, 1));
      await t.pump();
      expect(app.chat.banner.value, isNull);
    }

    Future<void> expectReopened(WidgetTester t, AppState app, int id) async {
      expect(openDisplayScreens.value, 0);
      expect(app.chat.banner.value, isNull); // 가려진 동안 온 것은 닫은 뒤에도 안 뜸
      app.chat.onEvent('chat_message', ev(id, 1));
      expect(app.chat.banner.value?.messageId, id);
      app.chat.banner.value = null;
    }

    testWidgets('예약 상세 [이 기기에 QR 보이기](showQuestionnaireQrHere → openQrScreen) · [여권 스캔](openPassportScan)', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      f.override['GET /api/reservations/9'] = (_) => http.Response(jsonEncode(detailJson()), 200, headers: jsonHeaders);
      f.override['POST /api/display-requests'] =
          (_) => http.Response(jsonEncode({'id': 43, 'qrToken': null, 'qrUrl': fakeUrl, 'expiresAt': '2026-10-29T16:10:00+09:00'}), 200, headers: jsonHeaders);
      final app = chatApp(f);
      await app.chat.refreshRooms();
      t.view.physicalSize = const Size(1179, 2556 * 3);
      t.view.devicePixelRatio = 3;
      addTearDown(t.view.reset);
      await t.pumpWidget(AppScope(
          state: app, child: MaterialApp(navigatorObservers: [app.chat.rootRoutes], home: const ReservationDetailScreen(reservationId: 9))));
      await settle(t);
      // ① 예약 상세 → QR(reservation_detail_screen _questionnaireHere)
      await t.tap(find.text('이 기기에 QR 보이기'));
      await settle(t);
      await t.pump(const Duration(milliseconds: 400));
      expect(find.byType(QrShowScreen), findsOneWidget);
      await expectBlocked(t, app, 50);
      await t.tap(find.text('닫기'));
      await t.pump(const Duration(milliseconds: 400));
      await settle(t);
      await expectReopened(t, app, 51);
      // ② 예약 상세 → 여권 스캔(reservation_detail_screen _scan → openPassportScan = showPassportScan)
      await t.pump(const Duration(seconds: 1)); // QR 화면 닫힘 애니메이션 끝
      await t.ensureVisible(find.text('여권 스캔'));
      await t.pump();
      await t.tap(find.text('여권 스캔'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));
      expect(find.byType(ScanScreen), findsOneWidget);
      await expectBlocked(t, app, 52);
      await t.tap(find.text('닫기'));
      await t.pump(const Duration(milliseconds: 400));
      await settle(t);
      await expectReopened(t, app, 53);
      await teardown(t, app);
    });

    testWidgets('대기열(SSE display · pending)로 연 QR — Shell._next → openDisplay → showQrScreen', (t) async {
      ipad(t);
      final f = FakeChat()..rooms = [roomJ(1)];
      f.override['GET /api/reservations/9'] = (_) => http.Response(jsonEncode(detailJson()), 200, headers: jsonHeaders);
      final app = chatApp(f);
      await t.pumpWidget(AppScope(state: app, child: MaterialApp(navigatorObservers: [app.chat.rootRoutes], home: const Shell())));
      await t.runAsync(() => app.chat.refreshRooms());
      await t.pump();
      app.enqueueDisplays([const DisplayReq(requestId: 41, kind: 'questionnaire', reservationId: 9, qrUrl: fakeUrl, expiresAt: '2026-10-29T16:10:00+09:00')]);
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));
      expect(find.byType(QrShowScreen), findsOneWidget);
      await expectBlocked(t, app, 60);
      expect(find.byKey(const Key('chat-banner')), findsNothing);
      await t.tap(find.text('닫기'));
      await t.pump(const Duration(milliseconds: 400));
      await settle(t);
      await expectReopened(t, app, 61);
      await teardown(t, app);
    });
  });

  group('생명주기 · 메우기 · 비우기(§11)', () {
    test('앞으로 옴 = GET rooms + 열린 방 since · 백그라운드 = 배너 없음 · 읽기 실패는 조용히', () async {
      final f = FakeChat()..rooms = [roomJ(1)];
      f.messages[1] = [msgJ(1, 1)];
      final app = chatApp(f);
      await app.chat.loadLatest(1);
      app.chat.viewOpened(1);
      app.didChangeAppLifecycleState(AppLifecycleState.paused);
      expect(app.chat.foreground, isFalse);
      f.reqs.clear();
      app.didChangeAppLifecycleState(AppLifecycleState.resumed);
      await Future<void>.delayed(const Duration(milliseconds: 30));
      expect(app.chat.foreground, isTrue);
      expect(f.where('GET', '/api/chat/rooms'), isNotEmpty);
      expect(f.where('GET', '/api/chat/rooms/1/messages').single.url.queryParameters['since'], t0);
      f.override['GET /api/chat/rooms'] = (_) => http.Response('', 404);
      app.didChangeAppLifecycleState(AppLifecycleState.resumed);
      await Future<void>.delayed(const Duration(milliseconds: 30));
      expect(app.toaster.text, isNull);
      app.stream.dispose();
    });

    test('SSE 가 (다시) 붙으면(_onStreamChange) 채팅 메우기', () async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final sse = StreamController<List<int>>.broadcast();
      late AppState app;
      final api = Api(base: () => 'http://x', token: () => 't', client: f.client);
      final stream = BoardStream(
        uri: () => Uri.parse('http://x/api/board/stream?token=t'),
        onUnauthorized: () {},
        clientFactory: () => MockClient.streaming((req, _) async => http.StreamedResponse(sse.stream, 200)),
      );
      app = AppState(api: api, stream: stream);
      app.session = chatApp(f).session;
      stream.start();
      await Future<void>.delayed(Duration.zero);
      sse.add(utf8.encode('event: board\ndata: ${jsonEncode({'now': t0, 'version': 1, 'cards': []})}\n\n'));
      await Future<void>.delayed(const Duration(milliseconds: 30));
      expect(stream.connected, isTrue);
      expect(f.where('GET', '/api/chat/rooms'), hasLength(1));
      expect(app.chat.rooms.single.id, 1);
      stream.stop();
      await sse.close();
    });

    test('로그아웃 · 계정 바뀜 = 방 · 메시지 · 사진 · 실패 말풍선 · 배지 비움', () async {
      messenger.setMockMethodCallHandler(pushCh, (c) async => null);
      final f = FakeChat()..rooms = [roomJ(1, unread: 1)];
      f.messages[1] = [msgJ(1, 1)];
      var who = 'n';
      f.override['/api/auth/login'] = (_) => http.Response('{"token":"t","id":"$who","role":"nurse","name":"x","staffId":null}', 200, headers: jsonHeaders);
      final app = AppState(store: MemStore([]), api: Api(base: () => 'http://x', token: () => 't', client: f.client), push: PushChannel(pushCh));
      await app.login('n', 'pw');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await app.chat.loadLatest(1);
      app.chat.photos.put(5, Uint8List(1));
      expect(app.chat.unreadRooms.value, 1);
      who = 'other';
      await app.login('other', 'pw'); // 계정 바뀜
      expect(app.chat.threads, isEmpty);
      expect(app.chat.photos.length, 0);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await app.chat.loadLatest(1);
      app.chat.photos.put(5, Uint8List(1));
      await app.logout();
      expect(app.chat.rooms, isEmpty);
      expect(app.chat.threads, isEmpty);
      expect(app.chat.photos.length, 0);
      expect(app.chat.unreadRooms.value, 0);
      expect(app.chat.meId, isNull);
      app.stream.dispose();
    });
  });

  group('아이패드(S13a ~ d)', () {
    testWidgets('두 칸 — 공통 헤더 · 목록 칸 위 [새 대화] · 처음 「왼쪽에서 대화를 골라 주세요」 · 고르면 오른쪽 대화(뒤로 없음) · 방 정보 = 오른쪽 시트', (t) async {
      ipad(t);
      final f = FakeChat()
        ..rooms = [roomJ(1, unread: 1, last: preview(1)), roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, coordM], last: preview(2))]
        ..messages[1] = [msgJ(1, 1, text: '안녕하세요 패드')];
      final app = chatApp(f)..tab.value = AppTab.chat;
      await t.pumpWidget(chatTab(app));
      await settle(t);
      expect(find.text('Céramique'), findsOneWidget);
      expect(find.text('채팅'), findsOneWidget);
      expect(find.byKey(const Key('chat-new')), findsOneWidget);
      expect(find.text('왼쪽에서 대화를 골라 주세요'), findsOneWidget);
      await t.tap(find.text('나의사').first);
      await settle(t);
      await t.pump();
      expect(find.text('안녕하세요 패드'), findsOneWidget);
      expect(find.text('채팅'), findsOneWidget); // 대화 칸에 「‹ 채팅」 없음
      expect(app.chat.watching, 1);
      expect(jsonDecode(f.where('POST', '/api/chat/rooms/1/read').single.body), {'messageId': 1});
      await t.tap(find.byTooltip('방 정보'));
      await t.pumpAndSettle();
      expect(find.text('방 정보'), findsOneWidget);
      expect(find.text('닫기'), findsOneWidget);
      expect(app.chat.watching, isNull); // 시트가 덮음(W2-4)
      await t.tap(find.text('닫기'));
      await t.pumpAndSettle();
      expect(app.chat.watching, 1);
      await teardown(t, app);
    });
  });

  group('방 정보(S10a ~ e)', () {
    Future<AppState> openInfo(WidgetTester t, FakeChat f, String row) async {
      phone(t);
      final app = chatApp(f)..tab.value = AppTab.chat;
      await t.pumpWidget(chatTab(app));
      await settle(t);
      await t.tap(find.text(row).first);
      await t.pumpAndSettle();
      await settle(t);
      await t.tap(find.byTooltip('방 정보'));
      await t.pumpAndSettle();
      return app;
    }

    testWidgets('그룹(S10a) — 그룹 이름 · 알림 Toggle(PUT mute) · 참여자(「나」 맨 위) · [+ 참여자 추가](이미 참여 중 · POST members) · [나가기] 확인', (t) async {
      final f = FakeChat()..rooms = [roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, offM])];
      final app = await openInfo(t, f, '4층 시술실');
      expect(find.text('대화'), findsOneWidget); // ‹ 대화
      expect(find.text('그룹 이름'), findsOneWidget);
      expect(find.text('참여자 3명'), findsOneWidget);
      expect(find.text('이 방만 · 끄면 푸시 · 앱 안 배너 없음'), findsOneWidget);
      expect(find.text('(비활성)'), findsOneWidget);
      expect(t.getTopLeft(find.text('가간호')).dy, lessThan(t.getTopLeft(find.text('나의사')).dy));
      expect(find.text('나'), findsOneWidget);
      // F10 — 「나」 = 줄 오른쪽 끝(이름 길이와 상관없이 · Flexible + Spacer 아님)
      final w = t.view.physicalSize.width / t.view.devicePixelRatio;
      expect(t.getRect(find.text('나')).right, greaterThan(w - 60));
      await t.tap(find.byType(Switch));
      await settle(t);
      expect(jsonDecode(f.where('PUT', '/api/chat/rooms/2/mute').single.body), {'muted': true});
      expect(app.chat.room(2)!.muted, isTrue);
      // 참여자 추가
      f.people = [docM, coordM, consM];
      f.override['POST /api/chat/rooms/2/members'] =
          (_) => http.Response(jsonEncode(roomJ(2, group: true, title: '4층 시술실', members: [meM, docM, offM, coordM])), 200, headers: jsonHeaders);
      await t.tap(find.byKey(const Key('chat-add-members')));
      await t.pumpAndSettle();
      await settle(t);
      expect(find.text('이미 참여 중'), findsOneWidget);
      expect(t.getRect(find.text('이미 참여 중')).right, greaterThan(w - 60)); // F10 — 오른쪽 끝
      expect(find.text('0명 선택 · 지금 3명 · 최대 20명'), findsOneWidget);
      await t.tap(find.text('나의사')); // 이미 참여 — 못 고름
      await t.tap(find.text('다코디'));
      await t.pump();
      await t.tap(find.text('추가'));
      await settle(t);
      await t.pumpAndSettle();
      expect(jsonDecode(f.where('POST', '/api/chat/rooms/2/members').single.body), {'accountIds': [3]});
      expect(find.byKey(const Key('chat-input')), findsOneWidget); // 대화로 돌아옴
      // 나가기
      await t.tap(find.byTooltip('방 정보'));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('chat-leave')));
      await t.pumpAndSettle();
      expect(find.text('4층 시술실에서 나갈까요?'), findsOneWidget);
      expect(find.text('내 목록에서 이 방이 사라져요. 다시 초대받으면 다시 볼 수 있어요.'), findsOneWidget);
      await t.tap(find.text('나가기').last);
      await settle(t);
      await t.pumpAndSettle();
      expect(f.where('POST', '/api/chat/rooms/2/leave'), hasLength(1));
      expect(app.chat.room(2), isNull);
      expect(find.byKey(const Key('chat-new')), findsOneWidget); // 방 목록
      await teardown(t, app);
    });

    testWidgets('1:1(S10b) — 그룹 이름 · 추가 · 나가기 없음 · 안내 한 줄 · [목록에서 숨기기](확인 없음) → 목록', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openInfo(t, f, '나의사');
      expect(find.text('그룹 이름'), findsNothing);
      expect(find.byKey(const Key('chat-add-members')), findsNothing);
      expect(find.byKey(const Key('chat-leave')), findsNothing);
      expect(find.text('참여자 2명'), findsOneWidget);
      expect(find.text('1:1 에는 참여자를 더할 수 없어요. 여럿이 이야기하려면 [새 대화] 에서 그룹을 만들어요.'), findsOneWidget);
      expect(find.text('새 메시지가 오면 목록에 다시 보여요'), findsOneWidget);
      await t.tap(find.byKey(const Key('chat-hide')));
      await settle(t);
      await t.pumpAndSettle();
      expect(f.where('POST', '/api/chat/rooms/1/hide'), hasLength(1));
      expect(find.text('아직 대화가 없어요'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('다른 기기에서 나감(SSE chat_room_removed) — 열린 대화가 닫힘', (t) async {
      phone(t);
      final f = FakeChat()..rooms = [roomJ(1), roomJ(3, members: [meM, coordM])];
      final app = chatApp(f)..tab.value = AppTab.chat;
      await t.pumpWidget(chatTab(app));
      await settle(t);
      await t.tap(find.text('나의사'));
      await t.pumpAndSettle();
      app.chat.onEvent('chat_room_removed', {'roomId': 1});
      await t.pumpAndSettle();
      expect(find.byKey(const Key('chat-input')), findsNothing);
      expect(find.text('다코디'), findsOneWidget);
      await teardown(t, app);
    });
  });
}

