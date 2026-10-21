import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/sse/sse_parser.dart';

void main() {
  test('여러 줄 data 는 \\n 으로 잇고 빈 줄에서 끝난다', () {
    final p = SseParser();
    final ev = p.addText('event: board\nid: 3\ndata: {"a":\ndata: 1}\n\n');
    expect(ev, hasLength(1));
    expect(ev.single.event, 'board');
    expect(ev.single.id, '3');
    expect(ev.single.data, '{"a":\n1}');
  });

  test('주석(: ping)은 무시 · event 없으면 message', () {
    final p = SseParser();
    expect(p.addText(': ping\n\n'), isEmpty);
    final ev = p.addText('data: x\n\n');
    expect(ev.single.event, 'message');
  });

  test('retry: 는 콜백으로', () {
    int? got;
    final p = SseParser(onRetry: (ms) => got = ms);
    p.addText('retry: 5000\n\n');
    expect(got, 5000);
  });

  test('줄 중간에서 끊긴 조각 · CRLF 가 조각 경계에 걸려도', () {
    final p = SseParser();
    expect(p.addText('event: bo'), isEmpty);
    expect(p.addText('ard\r'), isEmpty);
    expect(p.addText('\ndata: {"v":1}\r'), isEmpty);
    final ev = p.addText('\n\r\n');
    expect(ev.single.event, 'board');
    expect(ev.single.data, '{"v":1}');
  });

  test('UTF-8 글자가 바이트 조각 경계에 걸려도 깨지지 않는다', () {
    final p = SseParser();
    final bytes = utf8.encode('event: board\ndata: 가 원장\n\n');
    final out = <SseEvent>[];
    for (var i = 0; i < bytes.length; i++) {
      out.addAll(p.addBytes([bytes[i]]));
    }
    expect(out.single.data, '가 원장');
  });

  test('이벤트 두 개가 한 조각에', () {
    final p = SseParser();
    final ev = p.addText('event: board\ndata: 1\n\nevent: board\ndata: 2\n\n');
    expect(ev.map((e) => e.data), ['1', '2']);
  });
}
