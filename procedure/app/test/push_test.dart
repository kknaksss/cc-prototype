import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/api/session_store.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/account.dart';
import 'package:procedure_app/model/board.dart';
import 'package:procedure_app/model/notification.dart';
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

  group('payload 종류(§5-2 · §5-3)', () {
    test('kind 없음 = 원장 호출(옛 빌드) · 상담사 호출 = reservationId · 띄우기 = requestId', () {
      expect(PushTap.parse({'visitId': 3, 'callId': 1})?.kind, PushKind.doctorCall);
      final c = PushTap.parse({'kind': 'counselor_call', 'reservationId': '41'});
      expect(c?.kind, PushKind.counselorCall);
      expect(c?.reservationId, 41);
      expect(PushTap.parse({'kind': 'display', 'requestId': 9})?.requestId, 9);
      expect(PushTap.parse({'kind': 'counselor_call'}), isNull); // 갈 곳 없음
      expect(tapVisitId({'kind': 'counselor_call', 'reservationId': 41, 'visitId': 2}), isNull);
    });
  });

  test('새 기기 토큰이 오면 POST /api/devices {token, name, kind} → deviceId 저장 · SSE 쿼리 · 로그아웃 때 지움', () async {
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
        if (req.url.path == '/api/devices') {
          bodies.add(req.body);
          return http.Response('{"ok":true,"deviceId":7}', 200);
        }
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
    final sent = bodies.map((b) => jsonDecode(b) as Map).where((b) => b['token'] == 'cafe01').toList();
    expect(sent, isNotEmpty);
    expect(sent.first['kind'], isIn(['phone', 'tablet'])); // 시험 화면 800×600 = 짧은 변 600 → tablet
    expect(app.deviceToken, 'cafe01');
    expect(app.deviceId, 7);
    expect((await SharedPreferences.getInstance()).getInt('push.deviceId'), 7);
    expect(app.api.streamUri('t', deviceId: app.deviceId).queryParameters, {'token': 't', 'deviceId': '7'});
    await app.logout();
    expect(app.deviceId, isNull);
    expect((await SharedPreferences.getInstance()).getInt('push.deviceId'), isNull);
    app.stream.dispose();
  });

  test('알림 누름 → 탭 바꾸기(원장 호출 = 시술 현황 · 상담사 호출 = 예약 현황) · 그 발송 읽음', () async {
    SharedPreferences.setMockInitialValues({});
    const ch = MethodChannel('procedure/push');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (c) async => c.method == 'status' ? 'denied' : null);
    final bodies = <String>[];
    late AppState app;
    final api = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        if (req.url.path == '/api/notifications/read') bodies.add(req.body);
        if (req.url.path == '/api/auth/login') {
          return http.Response('{"token":"t","id":"c","role":"counselor","name":"상담","staffId":4}', 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response('{"ok":true,"unread":0,"items":[]}', 200);
      }),
    );
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: api, push: push);
    await app.boot();
    await app.login('c', 'pw');
    expect(app.tab.value, AppTab.reservations); // 첫 화면 = 예약 현황(D7-60)
    push.onTap!(const PushTap(PushKind.doctorCall, visitId: 3, callId: 8));
    expect(app.tab.value, AppTab.board);
    expect(app.openVisit.value, 3);
    push.onTap!(const PushTap(PushKind.counselorCall, reservationId: 41));
    expect(app.tab.value, AppTab.reservations);
    expect(app.openReservation.value, 41);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies.map(jsonDecode), [
      {'callId': 8},
      {'reservationId': 41},
    ]);
    expect(app.session?.isAdmin, isTrue); // 상담사 = 수락 관리자 묶음(§3.4)
    // 알림 목록 항목 누름 = 목록이 ids 로 읽음 — 여기선 callId · reservationId 로 또 읽지 않는다(r1 W3)
    bodies.clear();
    app.openNotification(const AppNotification(id: 7, kind: 'doctor_call', title: '', body: '', createdAt: '', visitId: 3, callId: 8));
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies, isEmpty);
    expect(app.openVisit.value, 3);
    app.stream.dispose();
  });
}
