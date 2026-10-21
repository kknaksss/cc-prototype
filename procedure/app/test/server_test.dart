import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/config/server.dart';

void main() {
  test('서버 주소 → 통역 주소: http → ws · https → wss + /api/interpret', () {
    expect(interpretUri('http://192.0.2.10:8700').toString(), 'ws://192.0.2.10:8700/api/interpret');
    expect(interpretUri('https://example.test').toString(), 'wss://example.test/api/interpret');
    expect(interpretUri('https://example.test/').toString(), 'wss://example.test/api/interpret');
    expect(interpretUri('http://localhost:8700/base').toString(), 'ws://localhost:8700/base/api/interpret');
  });

  test('입력값 정리 · 형식 확인', () {
    expect(normalizeBase('  192.0.2.10:8700/ '), 'http://192.0.2.10:8700');
    expect(normalizeBase('https://example.test//'), 'https://example.test');
    expect(isValidBase('http://192.0.2.10:8700'), isTrue);
    expect(isValidBase('ftp://x'), isFalse);
    expect(isValidBase('http://'), isFalse);
  });
}
