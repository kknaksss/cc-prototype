// 실기기 E2E batch 1 — #1 installId · #3 SSE display → 화면 열림(다른 탭) · #5 ccc 링크
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/screens/launchers.dart';
import 'package:procedure_app/screens/shell.dart';
import 'package:procedure_app/sse/board_stream.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'push_test.dart' show MemStore;

const ch = MethodChannel('procedure/push');
final json = {'content-type': 'application/json; charset=utf-8'};

String boardFrame(int v) => 'event: board\nid: $v\ndata: ${jsonEncode({'now': '2026-10-28T10:00:00+09:00', 'version': v, 'cards': []})}\n\n';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  // 공통 — 로그인 응답 · 기기 등록 응답 기록 · 그 밖 {ok}
  (Api, List<http.Request>) api(AppState Function() app, {int deviceId = 9}) {
    final reqs = <http.Request>[];
    return (
      Api(
        base: () => 'http://x',
        token: () => app().session?.token,
        client: MockClient((req) async {
          reqs.add(req);
          return switch (req.url.path) {
            '/api/auth/login' => http.Response('{"token":"t","id":"coord","role":"coordinator","name":"코디","staffId":null}', 200, headers: json),
            '/api/devices' => http.Response('{"ok":true,"deviceId":$deviceId}', 200),
            '/api/display-requests/claim' =>
              http.Response('{"requestId":31,"kind":"scan","reservationId":9,"deviceId":$deviceId,"status":"opened"}', 200),
            '/api/display-requests/pending' => http.Response('{"items":[]}', 200),
            _ => http.Response('{"ok":true,"unread":0,"items":[]}', 200),
          };
        }),
      ),
      reqs
    );
  }

  test('#1 기기 등록에 installId(키체인 값) — 토큰 · 이름 등록 · 이름 고치기 모두', () async {
    SharedPreferences.setMockInitialValues({'device.name': '코디 폰'});
    messenger.setMockMethodCallHandler(ch, (c) async => switch (c.method) {
          'status' => 'authorized',
          'requestPermission' => true,
          'installId' => 'abcd-1234',
          _ => null,
        });
    late AppState app;
    final (a, reqs) = api(() => app);
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: a, push: push);
    await app.boot();
    await app.login('coord', 'pw');
    push.onToken!('beef01');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    final dev = reqs.where((r) => r.url.path == '/api/devices').map((r) => jsonDecode(r.body) as Map).toList();
    expect(dev.first, {'token': 'beef01', 'name': '코디 폰', 'kind': anyOf('phone', 'tablet'), 'installId': 'abcd-1234'}); // name = 처음 등록만(batch 2)
    await app.renameDevice('데스크 태블릿');
    final last = jsonDecode(reqs.lastWhere((r) => r.url.path == '/api/devices').body) as Map;
    expect(last['installId'], 'abcd-1234');
    expect(last['name'], '데스크 태블릿');
    app.stream.dispose();
  });

  test('#1 installId 를 못 얻으면(옛 빌드 · 시험) 키를 뺀다', () async {
    SharedPreferences.setMockInitialValues({});
    messenger.setMockMethodCallHandler(ch, (c) async => c.method == 'status' ? 'authorized' : null);
    late AppState app;
    final (a, reqs) = api(() => app);
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: a, push: push);
    await app.boot();
    await app.login('coord', 'pw');
    push.onToken!('beef02');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    final body = jsonDecode(reqs.lastWhere((r) => r.url.path == '/api/devices').body) as Map;
    expect(body.containsKey('installId'), isFalse);
    app.stream.dispose();
  });

  test('#3 등록이 겹쳐도 deviceId = 마지막 토큰의 행(늦게 온 옛 응답이 되돌리지 않음)', () async {
    SharedPreferences.setMockInitialValues({'device.name': 'x'});
    messenger.setMockMethodCallHandler(ch, (c) async => c.method == 'status' ? 'denied' : null);
    late AppState app;
    final a = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          return http.Response('{"token":"t","id":"coord","role":"coordinator","name":"코디","staffId":null}', 200, headers: json);
        }
        if (req.url.path == '/api/devices') {
          final old = (jsonDecode(req.body) as Map)['token'] == 'old';
          if (old) await Future<void>.delayed(const Duration(milliseconds: 40)); // 옛 토큰 응답이 늦게
          return http.Response('{"ok":true,"deviceId":${old ? 8 : 9}}', 200);
        }
        return http.Response('{"ok":true,"unread":0,"items":[]}', 200);
      }),
    );
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: a, push: push);
    await app.boot();
    await app.login('coord', 'pw');
    push.onToken!('old');
    push.onToken!('new');
    await Future<void>.delayed(const Duration(milliseconds: 120));
    expect(app.deviceId, 9);
    app.stream.dispose();
  });

  testWidgets('#3 SSE display(이 기기) → 다른 탭에 있어도 스캔 화면이 열림 · pending 실패해도', (t) async {
    SharedPreferences.setMockInitialValues({'push.deviceToken': 'beef09', 'device.name': 'x'});
    messenger.setMockMethodCallHandler(ch, (c) async => c.method == 'status' ? 'authorized' : null);
    final sse = StreamController<List<int>>.broadcast();
    late AppState app;
    final opened = <(int, int?)>[];
    final saved = openPassportScan;
    openPassportScan = (ctx, d, {displayRequestId}) async => opened.add((d.reservationId, displayRequestId));
    final client = MockClient((req) async => switch (req.url.path) {
          '/api/auth/login' => http.Response('{"token":"t","id":"coord","role":"coordinator","name":"코디","staffId":null}', 200, headers: json),
          '/api/devices' => http.Response('{"ok":true,"deviceId":9}', 200),
          '/api/display-requests/pending' => http.Response('{"error":{"code":"x","message":"x"}}', 500), // pending 이 실패해도 프레임으로 연다
          '/api/reservations/9' => http.Response(jsonEncode(_detail()), 200, headers: json),
          _ => http.Response('{"ok":true,"unread":0,"items":[]}', 200),
        });
    final a = Api(base: () => 'http://x', token: () => app.session?.token, client: client);
    final stream = BoardStream(
      uri: () => a.streamUri('t', deviceId: app.deviceId),
      onUnauthorized: () {},
      clientFactory: () => MockClient.streaming((req, _) async => http.StreamedResponse(sse.stream, 200)),
    );
    app = AppState(store: MemStore([]), api: a, push: PushChannel(ch), stream: stream);
    await t.runAsync(() async {
      await app.boot();
      await app.login('coord', 'pw');
      for (var i = 0; i < 100 && app.deviceId != 9; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
    });
    expect(app.deviceId, 9);
    await t.pumpWidget(AppScope(state: app, child: const MaterialApp(home: _ShellOnly())));
    app.tab.value = AppTab.settings; // 다른 탭
    await t.pump();
    await t.runAsync(() async {
      for (var i = 0; i < 100 && !app.stream.connected; i++) {
        sse.add(utf8.encode(boardFrame(1)));
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
      sse.add(utf8.encode('event: display\ndata: {"requestId":10,"deviceId":9,"kind":"scan","reservationId":9}\n\n'));
    });
    for (var i = 0; i < 100 && opened.isEmpty; i++) {
      await t.pump();
      await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
    }
    expect(opened, [(9, 10)]);
    // 같은 요청이 다시 와도(재연결 · pending) 또 열지 않음
    await t.runAsync(() async {
      sse.add(utf8.encode('event: display\ndata: {"requestId":10,"deviceId":9,"kind":"scan","reservationId":9}\n\n'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await t.pump();
    expect(opened.length, 1);
    // 다른 기기 것은 안 엶
    await t.runAsync(() async {
      sse.add(utf8.encode('event: display\ndata: {"requestId":11,"deviceId":8,"kind":"scan","reservationId":9}\n\n'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await t.pump();
    expect(opened.length, 1);
    openPassportScan = saved;
    app.stream.stop();
    await sse.close();
    await t.pumpWidget(const SizedBox());
  });

  test('#5 ccc 링크 — 로그인 돼 있으면 claim · 아니면 로그인 뒤 claim · 다른 링크는 무시', () async {
    SharedPreferences.setMockInitialValues({'push.deviceToken': 'beef05', 'device.name': 'x'});
    messenger.setMockMethodCallHandler(ch, (c) async => switch (c.method) {
          'status' => 'authorized',
          'takeLink' => 'ccc://display?t=TOKEN1', // 꺼진 상태에서 링크로 열림
          _ => null,
        });
    late AppState app;
    final (a, reqs) = api(() => app);
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: a, push: push);
    await app.boot();
    expect(app.phase, Phase.loggedOut);
    expect(reqs.where((r) => r.url.path == '/api/display-requests/claim'), isEmpty); // 로그인 전 = 기다림
    await app.login('coord', 'pw');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    final claims = reqs.where((r) => r.url.path == '/api/display-requests/claim').map((r) => jsonDecode(r.body)).toList();
    expect(claims, [
      {'qrToken': 'TOKEN1', 'deviceId': 9},
    ]);
    expect(app.displays.value.map((x) => x.requestId), [31]);
    // 켜진 상태에서 링크
    push.onLink!('https://example.com/x');
    push.onLink!('ccc://display?t=TOKEN2');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(reqs.where((r) => r.url.path == '/api/display-requests/claim').map((r) => jsonDecode(r.body)['qrToken']), ['TOKEN1', 'TOKEN2']);
    app.stream.dispose();
  });
}

// 탭 화면은 빼고 Shell 의 띄우기 · 이름 시트만 — 탭 본문(예약 · 판)은 다른 시험이 본다
class _ShellOnly extends StatelessWidget {
  const _ShellOnly();
  @override
  Widget build(BuildContext context) => const Shell();
}

Map<String, dynamic> _detail() => {
      'reservationId': 9, 'day': '2026-10-28', 'state': {'main': 'reception', 'sub': null},
      'customer': {
        'customerId': 3, 'name': '고객 A', 'isNew': true, 'personal': {},
        'identity': {'status': 'unconfirmed', 'kind': 'foreign', 'fields': [], 'complete': false},
      },
      'reservation': {'sedationRequired': false, 'doctors': []}, 'health': {'state': 'none', 'items': []}, 'previousVisits': [],
      'can': {}, 'rooms': [], 'counselors': [],
    };
