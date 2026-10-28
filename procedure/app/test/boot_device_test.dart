// 「띄우기 실기기 안 열림」 — 업데이트 뒤 저장된 로그인으로 시작할 때 기기 등록 · SSE deviceId
import 'package:flutter/widgets.dart' show AppLifecycleState;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/account.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/sse/board_stream.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'push_test.dart' show MemStore;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const ch = MethodChannel('procedure/push');

  test('저장된 로그인 + 옛 deviceId(8) → 시작 때 등록 → 9 · SSE · pending 이 9', () async {
    SharedPreferences.setMockInitialValues({'push.deviceToken': 'aa', 'push.deviceId': 8, 'device.name': 'x', 'device.nameSent': true});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (c) async => switch (c.method) {
          'status' => 'authorized',
          'installId' => 'iid',
          _ => null,
        });
    final log = <String>[];
    final uris = <Uri>[];
    late AppState app;
    final api = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        log.add('${req.method} ${req.url.path}${req.url.query.isEmpty ? '' : '?${req.url.query}'}');
        if (req.url.path == '/api/auth/me') {
          return http.Response('{"id":"coord","role":"coordinator","name":"코디","staffId":null}', 200, headers: {'content-type': 'application/json'});
        }
        if (req.url.path == '/api/devices') return http.Response('{"ok":true,"deviceId":9}', 200);
        if (req.url.path == '/api/display-requests/pending') return http.Response('{"items":[]}', 200);
        return http.Response('{"ok":true,"unread":0,"items":[]}', 200);
      }),
    );
    final store = MemStore([])..s = const Session(token: 't', id: 'coord', role: Role.coordinator, name: '코디');
    late BoardStream stream;
    stream = BoardStream(
      uri: () => api.streamUri('t', deviceId: app.deviceId),
      onUnauthorized: () {},
      clientFactory: () => MockClient.streaming((req, _) async {
        uris.add(req.url);
        return http.StreamedResponse(const Stream.empty(), 200);
      }),
    );
    app = AppState(store: store, api: api, push: PushChannel(ch), stream: stream);
    await app.boot();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(app.deviceId, 9);
    expect(uris.last.queryParameters['deviceId'], '9');
    expect(log.where((l) => l.startsWith('GET /api/display-requests/pending')).last, contains('deviceId=9'));
    app.stream.dispose();
  });

  // 실기기 빌드 8 업데이트 뒤: 저장된 deviceId 가 맞아도(9) 시작 SSE 가 등록 전에 열려 back 이 기기로 못 알아본 채 붙으면
  // 등록이 같은 9 를 돌려줘 「바뀜 없음」 → 다시 안 붙었다 → 이제 등록 뒤 한 번 다시 연다 · 앞으로 올 때도 다시 등록 → 다시 연다
  test('시작 · 앞으로 올 때 — 등록 응답이 같은 id 여도 SSE 를 등록 뒤 다시 연다', () async {
    SharedPreferences.setMockInitialValues({'push.deviceToken': 'aa', 'push.deviceId': 9, 'device.name': 'x', 'device.nameSent': true});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (c) async => switch (c.method) {
          'status' => 'authorized',
          'installId' => 'iid',
          _ => null,
        });
    final events = <String>[];
    late AppState app;
    final api = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        if (req.url.path == '/api/devices') events.add('register');
        if (req.url.path == '/api/auth/me') {
          return http.Response('{"id":"coord","role":"coordinator","name":"코디","staffId":null}', 200, headers: {'content-type': 'application/json'});
        }
        if (req.url.path == '/api/devices') return http.Response('{"ok":true,"deviceId":9}', 200);
        if (req.url.path == '/api/display-requests/pending') return http.Response('{"items":[]}', 200);
        return http.Response('{"ok":true,"unread":0,"items":[]}', 200);
      }),
    );
    final store = MemStore([])..s = const Session(token: 't', id: 'coord', role: Role.coordinator, name: '코디');
    final stream = BoardStream(
      uri: () => api.streamUri('t', deviceId: app.deviceId),
      onUnauthorized: () {},
      clientFactory: () => MockClient.streaming((req, _) async {
        events.add('sse:${req.url.queryParameters['deviceId']}');
        return http.StreamedResponse(const Stream.empty(), 200);
      }),
    );
    app = AppState(store: store, api: api, push: PushChannel(ch), stream: stream);
    await app.boot();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    // 시작: 저장된 9 로 먼저 열림 → 등록(9) → 다시 열림
    expect(events.take(3).toList(), ['sse:9', 'register', 'sse:9']);
    events.clear();
    app.didChangeAppLifecycleState(AppLifecycleState.paused);
    app.didChangeAppLifecycleState(AppLifecycleState.resumed);
    await Future<void>.delayed(const Duration(milliseconds: 50));
    // 앞으로 옴: 바로 열고(판) → 다시 등록 → 확인된 id 로 다시
    expect(events.where((e) => e == 'register'), isNotEmpty);
    expect(events.last, 'sse:9');
    expect(events.indexOf('register'), lessThan(events.lastIndexOf('sse:9')));
    app.stream.dispose();
  });
}
