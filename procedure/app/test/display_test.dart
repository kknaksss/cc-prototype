// 띄우기 · 알림(SPEC-004 §5-3 · §5-4 · §7.1 · §8.7) — 자기 기기만 · QR 꼴 · 차례 · SSE board 만 version · id 없는 display/notification · 배지
import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/display.dart';
import 'package:procedure_app/model/notification.dart';
import 'package:procedure_app/sse/board_stream.dart';
import 'package:shared_preferences/shared_preferences.dart';

String board(int v) => 'event: board\nid: $v\ndata: ${jsonEncode({'now': '2026-10-27T10:00:00+09:00', 'version': v, 'cards': []})}\n\n';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('SSE display — 자기 deviceId 일 때만 · 기기 행 없으면 안 연다', () {
    expect(isMyDisplay({'deviceId': 7, 'requestId': 1}, 7), isTrue);
    expect(isMyDisplay({'deviceId': 8}, 7), isFalse);
    expect(isMyDisplay({'deviceId': 7}, null), isFalse);
  });

  test('QR = ccc://display?t= 만', () {
    expect(qrTokenOf('ccc://display?t=abc'), 'abc');
    expect(qrTokenOf('https://ccc.example/display?t=abc'), isNull);
    expect(qrTokenOf('ccc://display'), isNull);
    expect(qrTokenOf(null), isNull);
  });

  test('pending 항목(코디 확정 모양) · 모르는 kind 버림', () {
    final l = DisplayReq.listFrom({
      'items': [
        {'requestId': 3, 'kind': 'scan', 'reservationId': 9, 'customerId': 2, 'deviceId': 7, 'status': 'opened', 'expiresAt': 'x'},
        {'requestId': 4, 'kind': 'other', 'reservationId': 9},
      ],
    });
    expect(l.single.requestId, 3);
    expect(l.single.kind, 'scan');
  });

  test('열 차례 — 같은 요청 두 번 안 넣음 · 닫힌 상태 안 넣음 · 오래된 것 먼저', () {
    SharedPreferences.setMockInitialValues({});
    final app = AppState(api: Api(base: () => 'http://x', token: () => null, client: MockClient((_) async => http.Response('{}', 200))));
    DisplayReq r(int id, [String st = 'pending']) => DisplayReq(requestId: id, kind: 'questionnaire', reservationId: 1, status: st);
    app.enqueueDisplays([r(1), r(2), r(3, 'done')]);
    app.enqueueDisplays([r(2), r(4, 'opened')]);
    expect(app.displays.value.map((x) => x.requestId), [1, 2, 4]);
    expect(app.takeDisplay()?.requestId, 1);
    expect(app.displays.value.map((x) => x.requestId), [2, 4]);
    // 이미 연 요청(1)은 pending 이 opened 로 다시 돌려줘도 안 넣는다(r1 W1) · 대기 화면이 직접 연 것(2)도
    app.markDisplayOpened(2);
    app.enqueueDisplays([r(1, 'opened'), r(2, 'opened'), r(5)]);
    expect(app.displays.value.map((x) => x.requestId), [4, 5]);
    app.stream.dispose();
  });

  test('스트림 — board 만 version 규칙 · id 없는 display · notification 은 onEvent 로', () async {
    final ctl = StreamController<List<int>>();
    final events = <String>[];
    final s = BoardStream(
      uri: () => Uri.parse('http://x/api/board/stream?token=t&deviceId=7'),
      onUnauthorized: () {},
      clientFactory: () => MockClient.streaming((req, _) async => http.StreamedResponse(ctl.stream, 200)),
    );
    s.onEvent = (e, d) => events.add('$e:${jsonEncode(d)}');
    s.start();
    await Future<void>.delayed(Duration.zero);
    ctl.add(utf8.encode(board(5)));
    ctl.add(utf8.encode('event: display\ndata: {"requestId":1,"deviceId":7,"kind":"scan","reservationId":9}\n\n'));
    ctl.add(utf8.encode('event: notification\ndata: {"unread":3}\n\n'));
    ctl.add(utf8.encode(board(5))); // 같은 version — 버림
    await Future<void>.delayed(Duration.zero);
    expect(s.board?.version, 5);
    expect(events, ['display:{"requestId":1,"deviceId":7,"kind":"scan","reservationId":9}', 'notification:{"unread":3}']);
    ctl.add(utf8.encode(board(6)));
    await Future<void>.delayed(Duration.zero);
    expect(s.board?.version, 6); // display · notification 이 version 을 건드리지 않음
    s.dispose();
    await ctl.close();
  });

  test('SSE notification → 종 배지', () {
    SharedPreferences.setMockInitialValues({});
    final app = AppState(api: Api(base: () => 'http://x', token: () => null, client: MockClient((_) async => http.Response('{}', 200))));
    app.stream.onEvent!('notification', {'unread': 4});
    expect(app.unread.value, 4);
    app.stream.dispose();
  });

  test('알림 목록 — 둘만 · target(visitId · callId · reservationId)', () {
    final l = NotificationList.fromJson({
      'unread': 1,
      'items': [
        {'id': 1, 'kind': 'doctor_call', 'title': '원장 호출', 'body': 'A-룸1 · 시술 2건 · 전체 호출', 'createdAt': '', 'readAt': null, 'target': {'visitId': 3, 'callId': 5}},
        {'id': 2, 'kind': 'counselor_call', 'title': '상담사 호출', 'body': 'A-룸2 · 상담 대기', 'createdAt': '', 'readAt': 'x', 'target': {'reservationId': 9}},
        {'id': 3, 'kind': 'display', 'title': 'x', 'body': '', 'createdAt': '', 'target': {}},
      ],
    });
    expect(l.items.map((n) => n.kind), ['doctor_call', 'counselor_call']);
    expect(l.items.first.unread, isTrue);
    expect(l.items.first.callId, 5);
    expect(l.items.last.reservationId, 9);
  });
}
