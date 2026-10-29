// WP-APP4(r3) — 입력창 · [+] 시트 · 여러 개 · 변환 · 동영상 말풍선 · 재생 · 미리보기 · 배너(SPEC-007 §9 · §10.4 ~ §10.6 · §13.2 r3).
// 피커 · 변환기 · 인코더 · 재생기는 가짜로 바꿔 끼운다(1판 pickChatPhoto 꼴)
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/chat/chat_model.dart';
import 'package:procedure_app/chat/chat_state.dart';
import 'package:procedure_app/chat/chat_view.dart';
import 'package:procedure_app/chat/photo_pick.dart';
import 'package:procedure_app/chat/video_pick.dart';
import 'package:procedure_app/screens/chat_attach_sheet.dart';
import 'package:procedure_app/screens/chat_video_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_app2_test.dart' show openRoom;
import 'chat_fixture.dart';
import 'scan_test.dart' show png;

late Directory tmp;
int _n = 0;

// 변환 뒤 MP4 자리(임시 파일 — 보내기 끝 · 실패 말풍선 지움 · 로그아웃 때 지워져야 한다)
String fakeMp4([int bytes = 2048]) {
  final f = File('${tmp.path}/v${_n++}.mp4')..writeAsBytesSync(List.filled(bytes, 7));
  return f.path;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  late FakeRecent recent;
  late RecentMedia savedRecent;
  late VideoConverter savedConvert;
  late VideoProbe savedProbe;
  late PhotoEncoder savedEncode;
  late GalleryPicker savedGallery;
  late VideoPlayerBuilder savedPlayer;
  final converted = <String>[];

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('chat-app4-');
    savedRecent = recentMedia;
    savedConvert = convertChatVideo;
    savedProbe = probeChatVideo;
    savedEncode = encodeChatPhoto;
    savedGallery = pickChatGallery;
    savedPlayer = buildChatVideoPlayer;
    recent = FakeRecent()..thumbBytes = png;
    recentMedia = recent;
    converted.clear();
    encodeChatPhoto = (path, {deleteSource = false}) async => PickedPhoto(png, 400, 300);
    convertChatVideo = (path) async {
      final out = fakeMp4();
      converted.add(out);
      return PreparedVideo(out, png, 720, 1280, 12000, 2048);
    };
    probeChatVideo = (_) async => 12000;
  });
  tearDown(() {
    recentMedia = savedRecent;
    convertChatVideo = savedConvert;
    probeChatVideo = savedProbe;
    encodeChatPhoto = savedEncode;
    pickChatGallery = savedGallery;
    buildChatVideoPlayer = savedPlayer;
    try {
      tmp.deleteSync(recursive: true);
    } catch (_) {}
  });

  // 올리기 조각 사이 Future.delayed(zero) · 파일 IO 가 흐르게(가짜 시계 + 실제 비동기)
  Future<void> drain(WidgetTester t, [int n = 80]) async {
    for (var i = 0; i < n; i++) {
      await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
      await t.pump(const Duration(milliseconds: 5));
    }
  }

  Future<void> openSheet(WidgetTester t) async {
    await t.tap(find.byKey(const Key('chat-plus')));
    await t.pumpAndSettle();
    await settle(t, 3);
  }

  String circle(String id) {
    final c = find.descendant(of: find.byKey(Key('attach-pick-$id')), matching: find.byType(Text));
    return c.evaluate().isEmpty ? '' : (c.evaluate().single.widget as Text).data!;
  }

  group('입력창(D9-47)', () {
    testWidgets('넓은 입력칸(2 ~ 6줄 · 줄바꿈 키) + 아래 줄 [+] · [전송](비면 꺼짐) · 이모지 · 파일 · [사진] 없음', (t) async {
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      final field = t.widget<TextField>(find.byKey(const Key('chat-input')));
      expect(field.minLines, 2);
      expect(field.maxLines, 6);
      expect(field.textInputAction, TextInputAction.newline);
      expect(find.byKey(const Key('chat-plus')), findsOneWidget);
      expect(find.text('전송'), findsOneWidget);
      expect(find.byKey(const Key('chat-photo')), findsNothing);
      expect(find.byIcon(Icons.emoji_emotions_outlined), findsNothing);
      expect(find.byIcon(Icons.attach_file), findsNothing);
      // [+] 는 입력칸 아래 줄 왼쪽 · [전송] 은 오른쪽
      final input = t.getRect(find.byKey(const Key('chat-input')));
      final plus = t.getRect(find.byKey(const Key('chat-plus')));
      final send = t.getRect(find.byKey(const Key('chat-send')));
      expect(plus.top, greaterThanOrEqualTo(input.bottom));
      expect(send.top, greaterThanOrEqualTo(input.bottom));
      expect(plus.left, lessThan(send.left));
      await t.tap(find.byKey(const Key('chat-send')));
      expect(f.where('POST', '/api/chat/rooms/1/messages'), isEmpty); // 비면 꺼짐
      await t.enterText(find.byKey(const Key('chat-input')), '첫 줄\n둘째 줄');
      await t.pump();
      await t.tap(find.byKey(const Key('chat-send')));
      await settle(t, 6);
      expect((jsonDecode(f.where('POST', '/api/chat/rooms/1/messages').single.body) as Map)['text'], '첫 줄\n둘째 줄');
      await teardown(t, app);
    });
  });

  group('[+] 시트(D9-48 ~ D9-52)', () {
    testWidgets('최근 줄 — 카메라 칸 · 동그라미 차례 번호(다시 누르면 빠지고 당겨짐) · 동영상 길이 · 3분 넘음 흐림 · [전송 N] · 아래 메뉴 「사진」 하나', (t) async {
      recent.items = const [
        RecentItem('a'),
        RecentItem('b', video: true, durationMs: 125000),
        RecentItem('c'),
        RecentItem('d', video: true, durationMs: 181000),
      ];
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await openSheet(t);
      expect(find.text('최근 사진'), findsOneWidget);
      expect(find.byKey(const Key('attach-camera')), findsOneWidget);
      // 카메라 칸이 맨 앞
      expect(t.getRect(find.byKey(const Key('attach-camera'))).left, lessThan(t.getRect(find.byKey(const Key('attach-item-a'))).left));
      expect(find.text('2:05'), findsOneWidget);
      await t.ensureVisible(find.byKey(const Key('attach-item-d'), skipOffstage: false));
      await t.pump();
      expect(find.text('3:01'), findsOneWidget);
      final send = find.byKey(const Key('attach-send'));
      expect(find.descendant(of: send, matching: find.text('전송')), findsOneWidget); // 0개 = 꺼짐
      await t.tap(find.byKey(const Key('attach-item-a')));
      await t.tap(find.byKey(const Key('attach-item-b')));
      await t.tap(find.byKey(const Key('attach-item-c')));
      await t.pump();
      expect([circle('a'), circle('b'), circle('c')], ['1', '2', '3']);
      await t.tap(find.byKey(const Key('attach-item-b'))); // 빠짐 → c 가 2 로
      await t.pump();
      expect([circle('a'), circle('b'), circle('c')], ['1', '', '2']);
      expect(find.text('전송 2'), findsOneWidget);
      // 3분 넘는 동영상 = 흐림 · 누르면 토스트 · 안 골라짐
      final dim = t.widget<Opacity>(find.ancestor(of: find.byKey(const Key('attach-pick-d')), matching: find.byType(Opacity)).first);
      expect(dim.opacity, lessThan(1));
      await t.tap(find.byKey(const Key('attach-item-d')));
      await t.pump();
      expect(app.toaster.text, '3분 이하 동영상만 보낼 수 있어요');
      expect(circle('d'), '');
      // 아래 메뉴는 「사진」 하나(통화 · 선물 · 송금 · 지도 없음)
      expect(find.byKey(const Key('attach-gallery')), findsOneWidget);
      for (final x in ['통화', '선물', '송금', '지도', '파일']) {
        expect(find.text(x), findsNothing);
      }
      await t.tap(find.byKey(const Key('attach-gallery')));
      await t.pumpAndSettle();
      await teardown(t, app);
    });

    testWidgets('10개가 차면 남은 칸 흐림 · 더 누르면 토스트 「한 번에 10개까지 보낼 수 있어요」', (t) async {
      recent.items = [for (var i = 0; i < 12; i++) RecentItem('p$i')];
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await openSheet(t);
      for (var i = 0; i < 10; i++) {
        await t.ensureVisible(find.byKey(Key('attach-item-p$i'), skipOffstage: false));
        await t.tap(find.byKey(Key('attach-item-p$i')));
        await t.pump();
      }
      expect(find.text('전송 10'), findsOneWidget);
      await t.ensureVisible(find.byKey(const Key('attach-item-p10'), skipOffstage: false));
      final dim = t.widget<Opacity>(find.ancestor(of: find.byKey(const Key('attach-pick-p10')), matching: find.byType(Opacity)).first);
      expect(dim.opacity, lessThan(1));
      await t.tap(find.byKey(const Key('attach-item-p10')));
      await t.pump();
      expect(app.toaster.text, '한 번에 10개까지 보낼 수 있어요');
      expect(find.text('전송 10'), findsOneWidget);
      await teardown(t, app);
    });

    testWidgets('권한 — 거부 = 「사진 접근을 허용하면 최근 사진이 여기에 보여요」 + [설정 열기] · limited = 줄 끝 [더 고르기]', (t) async {
      recent.state = MediaAccess.denied;
      final f = FakeChat()..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await openSheet(t);
      expect(find.text('사진 접근을 허용하면 최근 사진이 여기에 보여요'), findsOneWidget);
      expect(find.byKey(const Key('attach-camera')), findsOneWidget); // 카메라 칸은 그대로
      await t.tap(find.byKey(const Key('attach-settings')));
      await t.pump();
      expect(recent.settings, 1);
      Navigator.of(t.element(find.byType(ChatAttachSheet))).pop();
      await t.pumpAndSettle();
      recent
        ..state = MediaAccess.limited
        ..items = const [RecentItem('a')];
      await openSheet(t);
      expect(find.text('더 고르기'), findsOneWidget);
      await t.tap(find.byKey(const Key('attach-more')));
      await settle(t, 2);
      expect(recent.limitedPicks, 1);
      await teardown(t, app);
    });
  });

  group('여러 개 · 변환(D9-50 · D9-51 · §10.5)', () {
    testWidgets('고른 차례대로 보내는 중 N개가 한꺼번에 · 「3개 보내는 중 · k/3」 · 하나씩 차례로(사진 → JPEG 길 · 동영상 → 변환 → videos → 보내기) · 보낸 뒤 변환 파일 지움', (t) async {
      recent.items = const [RecentItem('a'), RecentItem('b', video: true, durationMs: 12000), RecentItem('c')];
      final bCopy = fakeMp4(); // photo_manager 가 임시 폴더에 내보낸 사본 자리
      recent.files = {'a': '/fake/a.heic', 'b': bCopy, 'c': '/fake/c.png'};
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)];
      final app = await openRoom(t, f, '나의사');
      await openSheet(t);
      await t.tap(find.byKey(const Key('attach-item-a')));
      await t.tap(find.byKey(const Key('attach-item-c')));
      await t.tap(find.byKey(const Key('attach-item-b')));
      await t.pump();
      final gate = Completer<void>();
      f.delay = gate.future;
      await t.tap(find.byKey(const Key('attach-send')));
      await t.pumpAndSettle();
      await settle(t, 4);
      // 한꺼번에 3개 — 첫째(사진) 올리는 중 · 둘째(사진) · 셋째(동영상) 차례 기다림
      expect(find.text('3개 보내는 중 · 1/3'), findsOneWidget);
      expect(find.text('올리는 중 100%'), findsOneWidget);
      expect(find.text('올리는 중 0%'), findsOneWidget);
      expect(find.text('바꾸는 중…'), findsOneWidget);
      expect(f.where('POST', '/api/chat/photos'), hasLength(1)); // 하나씩
      gate.complete();
      await drain(t);
      final order = [for (final r in f.reqs) if (r.method == 'POST') r.url.path];
      expect(order, ['/api/chat/photos', '/api/chat/rooms/1/messages', '/api/chat/photos', '/api/chat/rooms/1/messages', '/api/chat/videos', '/api/chat/rooms/1/messages']);
      final sent = [for (final r in f.where('POST', '/api/chat/rooms/1/messages')) jsonDecode(r.body) as Map];
      expect(sent.map((b) => b['photoId'] ?? b['videoId']).toList(), [501, 502, 601]);
      expect(sent.last.containsKey('photoId'), isFalse);
      expect(sent.map((b) => b['clientId']).toSet(), hasLength(3));
      // 동영상 multipart — roomId · width · height · durationMs · thumb(JPEG) · video(MP4)
      final up = f.where('POST', '/api/chat/videos').single;
      expect(up.headers['Authorization'], 'Bearer t');
      final body = latin1.decode(up.bodyBytes);
      for (final kv in [('roomId', '1'), ('width', '720'), ('height', '1280'), ('durationMs', '12000')]) {
        expect(body, contains('name="${kv.$1}"\r\n\r\n${kv.$2}\r\n'));
      }
      expect(body, contains('name="thumb"; filename="thumb.jpg"\r\nContent-Type: image/jpeg'));
      expect(body, contains('name="video"; filename="video.mp4"\r\nContent-Type: video/mp4'));
      expect(find.byKey(const Key('chat-batch')), findsNothing); // 다 끝나면 사라짐
      expect(app.chat.thread(1).pending, isEmpty);
      await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
      expect(File(converted.single).existsSync(), isFalse); // 변환 파일 지움
      expect(File(bCopy).existsSync(), isFalse); // 사본 = 그 항목 파일만 지움(전역 clearFileCache 아님 · W-3)
      expect(isTempCopy('/fake/a.heic'), isFalse); // 임시 폴더 밖(사진 보관함 원본 자리)은 안 지움
      expect(app.chat.photos.get(thumbKey(601)), isNotNull); // 올린 썸네일을 그대로 캐시(사진 id 와 다른 키)
      expect(app.chat.photos.get(601), isNull);
      await teardown(t, app);
    });

    testWidgets('하나가 실패하면 그것만 「보내지 못했어요」 · 다음 것은 계속 · 바꾸지 못한 것(3분 · 실패)은 그 하나만 빠지고 토스트 · 로그아웃 = 변환 파일 지움', (t) async {
      pickChatGallery = () async => [
            MediaItem(video: true, prepare: () => prepareVideo('/fake/x.mov')), // 실패(502) → 다시 보내기 대기
            MediaItem(video: true, prepare: () => prepareVideo('/fake/long.mov')), // 3분 넘음(probe)
            MediaItem(video: false, prepare: () async => PreparedPhoto(png, 10, 10)),
          ];
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1)];
      f.override['POST /api/chat/videos'] = (_) => http.Response('{}', 502);
      probeChatVideo = (p) async => p.contains('long') ? 200000 : 12000;
      final app = await openRoom(t, f, '나의사');
      await openSheet(t);
      await t.tap(find.byKey(const Key('attach-gallery')));
      await t.pumpAndSettle();
      await drain(t);
      expect(find.text('보내지 못했어요'), findsOneWidget);
      expect(app.toaster.text, '3분 이하 동영상만 보낼 수 있어요');
      final sent = [for (final r in f.where('POST', '/api/chat/rooms/1/messages')) jsonDecode(r.body) as Map];
      expect(sent.single['photoId'], 501); // 셋째는 보냄
      final failed = app.chat.thread(1).pending.single;
      expect(failed.isVideo, isTrue);
      expect(File(failed.videoPath!).existsSync(), isTrue); // [다시 보내기]가 쓸 파일
      final path = failed.videoPath!;
      app.chat.clear(keepOpen: false); // 로그아웃
      await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
      expect(File(path).existsSync(), isFalse);
      await teardown(t, app);
    });

    test('prepareVideo — 3분 규칙 = 서버와 같은 하나(> 180000 못 보냄 · 봐 주기 없음 · W-1): 바꾸기 전 실제 ms · 바꾼 뒤 ms → 90MB · 실패 문구', () async {
      var calls = 0;
      convertChatVideo = (p) async {
        calls++;
        return PreparedVideo(fakeMp4(), png, 1280, 720, 60000, 2048);
      };
      probeChatVideo = (_) async => 180001;
      await expectLater(prepareVideo('/x'), throwsA(isA<MediaRejected>().having((e) => e.message, 'm', '3분 이하 동영상만 보낼 수 있어요')));
      probeChatVideo = (_) async => 200000;
      await expectLater(prepareVideo('/x'), throwsA(isA<MediaRejected>()));
      expect(calls, 0); // 길이가 넘으면 변환하지 않는다
      probeChatVideo = (_) async => 180000;
      expect((await prepareVideo('/x')).width, 1280); // 딱 3분 = 됨
      // 변환 뒤 길이(서버에 올릴 값)가 180001 이면 1ms 라도 못 보냄 — 서버 400 전에 앱이 막고 변환 파일 지움
      String? over;
      convertChatVideo = (p) async => PreparedVideo(over = fakeMp4(16), png, 1280, 720, 180001, 2048);
      await expectLater(prepareVideo('/x'), throwsA(isA<MediaRejected>().having((e) => e.message, 'm', '3분 이하 동영상만 보낼 수 있어요')));
      expect(File(over!).existsSync(), isFalse);
      convertChatVideo = (p) async => PreparedVideo(fakeMp4(16), png, 1280, 720, 180000, 2048);
      expect((await prepareVideo('/x')).durationMs, 180000);
      String? big;
      convertChatVideo = (p) async => PreparedVideo(big = fakeMp4(16), png, 1280, 720, 60000, maxVideoBytes + 1);
      await expectLater(prepareVideo('/x'), throwsA(isA<MediaRejected>().having((e) => e.message, 'm', '동영상이 90MB 를 넘어요')));
      expect(File(big!).existsSync(), isFalse);
      expect(maxVideoBytes, 90 * 1024 * 1024); // r3 처분 D-58
      convertChatVideo = (p) async => null;
      await expectLater(prepareVideo('/x'), throwsA(isA<MediaRejected>().having((e) => e.message, 'm', '동영상을 보내지 못했어요')));
      final src = fakeMp4();
      convertChatVideo = (p) async => PreparedVideo(fakeMp4(), png, 1, 1, 1000, 10);
      await prepareVideo(src, deleteSource: true);
      expect(File(src).existsSync(), isFalse); // 갤러리 사본은 바꾼 뒤 지움
    });

    test('동영상 올리기 진행률 = 받는 쪽이 가져간 바이트(되밀기) — 받는 쪽이 느리면 파일 읽기도 멈춤 · 메모리에 다 안 쌓임(W-2)', () async {
      final slow = _Slow();
      final api = Api(base: () => 'http://x', token: () => 't', client: slow);
      final path = fakeMp4(2 * 1024 * 1024);
      double last = 0;
      final id = await api.chatUploadVideo(3, path, thumb: png, width: 720, height: 1280, durationMs: 9000, onProgress: (v) {
        last = v;
        slow.progress = v;
      });
      expect(id, 77);
      expect(slow.ahead, isNotEmpty);
      // 받는 쪽이 받은 양보다 진행률이 앞서는 몫 = 조각 몇 개(버퍼) 이내 — 되밀기가 없으면 첫 조각 때 거의 100%
      expect(slow.ahead.reduce((a, b) => a > b ? a : b), lessThan(4 * 64 * 1024));
      expect(last, 1.0);
    });

    test('최근 줄 3:00(초 반올림 180) = 흐리지 않음 · 181 = 흐림 · 보내기 직전 실제 ms 180400 = 바꾸기 전에 막음(W-1)', () async {
      expect(const RecentItem('x', video: true, durationMs: 180000).tooLong, isFalse);
      expect(const RecentItem('x', video: true, durationMs: 181000).tooLong, isTrue);
      final f = FakeRecent()..files = {'x': '/fake/x.mov'};
      var calls = 0;
      convertChatVideo = (p) async {
        calls++;
        return null;
      };
      probeChatVideo = (_) async => 180400;
      final it = f.item(const RecentItem('x', video: true, durationMs: 180000));
      await expectLater(it.prepare(), throwsA(isA<MediaRejected>().having((e) => e.message, 'm', '3분 이하 동영상만 보낼 수 있어요')));
      expect(calls, 0);
    });

    test('동영상 올리기 = Content-Length 를 싣는다(청크 아님 — 서버 413 먼저 · r3 처분) · 300초 · 파일에서 흘림', () async {
      final rec = _Rec();
      final api = Api(base: () => 'http://x', token: () => 't', client: rec);
      final path = fakeMp4(300 * 1024);
      final seen = <double>[];
      final id = await api.chatUploadVideo(3, path, thumb: png, width: 720, height: 1280, durationMs: 9000, onProgress: seen.add);
      expect(id, 77);
      expect(rec.contentLength, isNotNull);
      expect(rec.contentLength, rec.body.length);
      expect(rec.body.length, greaterThan(300 * 1024));
      expect(seen.last, 1.0);
      expect(Api.videoTimeout, const Duration(seconds: 300));
    });
  });

  group('동영상 말풍선 · 재생(D9-53)', () {
    testWidgets('썸네일(#18 · Bearer · 메모리 캐시) + ▶ + 「m:ss」 · 누르면 재생 화면(#17 Bearer 헤더 · 저장 · 공유 없음 · 보고 있는 방 아님)', (t) async {
      Uri? url;
      Map<String, String>? headers;
      final audio = <String>[];
      t.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('procedure/video'), (c) async {
        audio.add(c.method);
        return null;
      });
      addTearDown(() => t.binding.defaultBinaryMessenger.setMockMethodCallHandler(const MethodChannel('procedure/video'), null));
      buildChatVideoPlayer = (u, h, thumb, onReady) {
        url = u;
        headers = h;
        return Builder(builder: (_) {
          if (audio.length == 1) Future.microtask(onReady); // 재생기가 열림
          return const SizedBox(key: Key('fake-player'));
        });
      };
      final f = FakeChat()
        ..photoBytes = png
        ..rooms = [roomJ(1, last: preview(5, kind: 'video', text: null))]
        ..messages[1] = [msgJ(5, 1, kind: 'video', text: null, video: {'id': 7, 'width': 720, 'height': 1280, 'durationMs': 125000})];
      final app = await openRoom(t, f, '나의사');
      expect(find.byKey(const Key('chat-video-7')), findsOneWidget);
      expect(find.text('2:05'), findsOneWidget);
      expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);
      final th = f.where('GET', '/api/chat/videos/7/thumbnail').single;
      expect(th.headers['Authorization'], 'Bearer t');
      expect(th.url.queryParameters, isEmpty); // ?token= 없음
      expect(app.chat.photos.get(thumbKey(7)), isNotNull);
      expect(app.chat.watching, 1);
      await t.tap(find.byKey(const Key('chat-video-7')));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('fake-player')), findsOneWidget);
      expect(find.byKey(const Key('chat-video-close')), findsOneWidget);
      expect(url!.path, '/api/chat/videos/7');
      expect(url!.queryParameters, isEmpty);
      expect(headers, {'Authorization': 'Bearer t'});
      expect(find.text('나의사'), findsWidgets);
      expect(find.textContaining('저장'), findsNothing);
      expect(find.textContaining('공유'), findsNothing);
      expect(app.chat.watching, isNull); // 루트 위 화면
      expect(audio, ['audioSave', 'audioFollowSilent']); // 무음 스위치를 따르게(W-4)
      await t.tap(find.byKey(const Key('chat-video-close')));
      await t.pumpAndSettle();
      expect(app.chat.watching, 1);
      expect(audio, ['audioSave', 'audioFollowSilent', 'audioRestore']); // 닫으면 원래대로
      await teardown(t, app);
    });
  });

  group('미리보기 · 배너 「동영상」(§4.5 · §10.12)', () {
    test('kind video · Message.video · 미리보기 아이콘 + 「동영상」 · 배너 본문 · 모르는 kind = 텍스트', () {
      final m = ChatMessage.fromJson(msgJ(5, 1, kind: 'video', text: null, video: {'id': 7, 'width': 720, 'height': 1280, 'durationMs': 9000}));
      expect(m.kind, MsgKind.video);
      expect(m.video!.durationMs, 9000);
      expect(bodyHead(m), '동영상');
      expect(msgKindOf('sticker'), MsgKind.text);
      final r = Room.fromJson(roomJ(1, group: true, members: [meM, docM, coordM], last: preview(5, kind: 'video', text: null)));
      expect(previewOf(r), (prefix: '나의사: ', body: '동영상', media: MsgKind.video));
      expect(durationText(0), '0:00');
      expect(durationText(180000), '3:00');
      expect(m.asDeleted('2026-10-29T15:00:00.000+09:00').video, isNull);
    });

    testWidgets('보고 있지 않은 방의 동영상 메시지 → 배너 「보낸 사람 — 동영상」', (t) async {
      final f = FakeChat()..rooms = [roomJ(1), roomJ(2, members: [meM, coordM])];
      final app = await openRoom(t, f, '나의사');
      app.chat.onEvent('chat_message', {
        'roomId': 2,
        'message': msgJ(40, 2, sender: 3, senderName: '다코디', role: 'coordinator', kind: 'video', text: null, video: {'id': 9, 'width': 1, 'height': 1, 'durationMs': 1000}),
      });
      expect(app.chat.banner.value?.line, '다코디 — 동영상');
      expect(app.chat.room(2)!.lastMessage!.kind, MsgKind.video);
      await teardown(t, app);
    });
  });
}

// 요청 기록(Content-Length 를 보려고 — MockClient 는 이 값을 넘기지 않는다)
class _Rec extends http.BaseClient {
  int? contentLength;
  Uint8List body = Uint8List(0);
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    contentLength = request.contentLength;
    body = await request.finalize().toBytes();
    return http.StreamedResponse(Stream.value(utf8.encode('{"videoId":77}')), 200, headers: {'content-type': 'application/json'});
  }
}

// 느린 받는 쪽 — 조각마다 멈췄다가 다시 받는다(소켓이 막힌 셈) · 그때마다 진행률이 받은 양보다 얼마나 앞섰는지 적는다
class _Slow extends http.BaseClient {
  final ahead = <int>[];
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final total = request.contentLength!;
    var got = 0;
    final done = Completer<void>();
    late StreamSubscription<List<int>> sub;
    sub = request.finalize().listen((b) {
      got += b.length;
      sub.pause();
      Future<void>.delayed(const Duration(milliseconds: 2), () {
        ahead.add((progress * total).round() - got);
        sub.resume();
      });
    }, onDone: done.complete);
    await done.future;
    return http.StreamedResponse(Stream.value(utf8.encode('{"videoId":77}')), 200, headers: {'content-type': 'application/json'});
  }

  double progress = 0;
}
