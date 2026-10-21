import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/sse/board_stream.dart';

String boardFrame(int version) =>
    'event: board\ndata: ${jsonEncode({'now': '2026-10-21T10:00:00+09:00', 'version': version, 'cards': []})}\n\n';

void main() {
  group('version 규칙', () {
    test('같은 연결 안에서는 가진 것보다 커야 받는다', () {
      expect(acceptVersion(incoming: 5, current: 5, firstOfConnection: false), isFalse);
      expect(acceptVersion(incoming: 4, current: 5, firstOfConnection: false), isFalse);
      expect(acceptVersion(incoming: 6, current: 5, firstOfConnection: false), isTrue);
    });
    test('새 연결의 첫 board 는 무조건(back 재시작이면 0 부터)', () {
      expect(acceptVersion(incoming: 0, current: 40, firstOfConnection: true), isTrue);
    });
  });

  test('재연결 간격 — 3s → 6s → 12s … 최대 30s', () {
    expect(backoff(1), const Duration(seconds: 3));
    expect(backoff(2), const Duration(seconds: 6));
    expect(backoff(3), const Duration(seconds: 12));
    expect(backoff(4), const Duration(seconds: 24));
    expect(backoff(5), const Duration(seconds: 30));
    expect(backoff(9), const Duration(seconds: 30));
    expect(backoff(1, retryMs: 1000), const Duration(seconds: 1));
  });

  test('스트림 — 첫 board 로 그리고, 작거나 같은 version 은 버린다', () async {
    final ctl = StreamController<List<int>>();
    final s = BoardStream(
      uri: () => Uri.parse('http://x/api/board/stream?token=t'),
      onUnauthorized: () {},
      clientFactory: () => MockClient.streaming((req, _) async {
        expect(req.headers['Accept'], 'text/event-stream');
        return http.StreamedResponse(ctl.stream, 200);
      }),
    );
    s.start();
    await Future<void>.delayed(Duration.zero);
    ctl.add(utf8.encode(boardFrame(7)));
    await Future<void>.delayed(Duration.zero);
    expect(s.board?.version, 7);
    expect(s.connected, isTrue);
    ctl.add(utf8.encode(': ping\n\n${boardFrame(7)}'));
    ctl.add(utf8.encode(boardFrame(6)));
    await Future<void>.delayed(Duration.zero);
    expect(s.board?.version, 7);
    ctl.add(utf8.encode(boardFrame(8)));
    await Future<void>.delayed(Duration.zero);
    expect(s.board?.version, 8);
    s.stop();
    await ctl.close();
  });

  test('401 이면 onUnauthorized', () async {
    var hit = false;
    final s = BoardStream(
      uri: () => Uri.parse('http://x/api/board/stream?token=bad'),
      onUnauthorized: () => hit = true,
      clientFactory: () => MockClient.streaming((req, _) async => http.StreamedResponse(const Stream.empty(), 401)),
    );
    s.start();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(hit, isTrue);
    expect(s.running, isFalse);
  });

  test('바이트가 안 오면(유휴) 끊긴 것으로 보고 retry 뒤 다시 연결', () async {
    var opens = 0;
    final ctls = <StreamController<List<int>>>[];
    final s = BoardStream(
      uri: () => Uri.parse('http://x/s'),
      onUnauthorized: () {},
      idleTimeout: const Duration(milliseconds: 40),
      clientFactory: () => MockClient.streaming((req, _) async {
        opens++;
        final c = StreamController<List<int>>();
        ctls.add(c);
        c.add(utf8.encode('retry: 10\n\n${boardFrame(opens)}'));
        return http.StreamedResponse(c.stream, 200);
      }),
    );
    s.start();
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(opens, 1);
    expect(s.connected, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(opens, greaterThanOrEqualTo(2));
    // 새 연결의 첫 board(version 2)를 받는다
    expect(s.board?.version, greaterThanOrEqualTo(2));
    s.stop();
    for (final c in ctls) {
      await c.close();
    }
  });
}
