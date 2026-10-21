import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/api/session_store.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/account.dart';
import 'package:procedure_app/model/board.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/screens/board_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fixture.dart';

class MemStore extends SessionStore {
  Session? s;
  final List<String> log;
  MemStore(this.log);
  @override
  Future<Session?> read() async => s;
  @override
  Future<void> write(Session v) async => s = v;
  @override
  Future<void> clear() async {
    log.add('store.clear');
    s = null;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('알림 payload → 룸 상세', () {
    test('visitId 숫자 · 문자열 · 없음', () {
      expect(tapVisitId({'aps': {}, 'visitId': 12, 'callId': 3}), 12);
      expect(tapVisitId({'visitId': '7'}), 7);
      expect(tapVisitId({'callId': 3}), isNull);
      expect(tapVisitId(null), isNull);
    });
    test('그 방이 스냅샷에 있으면 그 카드 · 없으면 null(토스트 → 목록)', () {
      final b = board(cards: [card(1), card(2)]);
      expect(pushTarget(b, 2)?.visitId, 2);
      expect(pushTarget(b, 9), isNull);
      expect(pushTarget(Board.fromJson({'now': ''}), 1), isNull);
    });
    test('예시 .apns 파일 payload 도 visitId 를 준다', () {
      expect(tapVisitId({'visitId': 1, 'callId': 1, 'aps': {'alert': {'title': '원장 호출'}}}), 1);
    });
  });

  test('로그아웃 = 기기 토큰 DELETE 먼저 → 저장 토큰 지움', () async {
    SharedPreferences.setMockInitialValues({'push.deviceToken': 'ab12'});
    const ch = MethodChannel('procedure/push');
    final calls = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (call) async {
      calls.add(call.method);
      if (call.method == 'setAuth') expect(call.arguments, {'base': 'http://localhost:8700', 'token': 't'});
      return switch (call.method) {
        'status' => 'authorized',
        'requestPermission' => true,
        _ => null,
      };
    });
    final log = <String>[];
    final store = MemStore(log);
    late AppState app;
    final api = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        log.add('${req.method} ${req.url.path}');
        if (req.url.path == '/api/auth/login') {
          return http.Response('{"token":"t","expiresAt":"","id":"doctor","role":"doctor","name":"원장","staffId":5}', 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response('{"ok":true}', 200);
      }),
    );
    app = AppState(store: store, api: api, push: PushChannel(ch));
    await app.boot();
    await app.login('doctor', 'pw');
    await Future<void>.delayed(Duration.zero);
    expect(app.notif, NotifStatus.authorized);
    expect(log, contains('POST /api/devices')); // 저장된 토큰 다시 등록(멱등)
    expect(calls, contains('setAuth')); // 알림 [수락] 용 키체인
    log.clear();
    await app.logout();
    expect(log.first, 'DELETE /api/devices/ab12');
    expect(calls, contains('clearAuth'));
    expect(log.indexOf('store.clear'), greaterThan(0));
    expect(app.session, isNull);
    app.stream.dispose();
  });

  test('새 기기 토큰이 오면 POST /api/devices {token}', () async {
    SharedPreferences.setMockInitialValues({});
    const ch = MethodChannel('procedure/push');
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(ch, (call) async => call.method == 'status' ? 'authorized' : true);
    final bodies = <String>[];
    late AppState app;
    final api = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        if (req.url.path == '/api/devices') bodies.add(req.body);
        if (req.url.path == '/api/auth/login') {
          return http.Response('{"token":"t","id":"admin","role":"admin","name":"관리자","staffId":null}', 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response('{"ok":true}', 200);
      }),
    );
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: api, push: push);
    await app.boot();
    await app.login('admin', 'pw');
    push.onToken!('cafe01');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies, contains('{"token":"cafe01"}'));
    expect(app.deviceToken, 'cafe01');
    app.stream.dispose();
  });
}
