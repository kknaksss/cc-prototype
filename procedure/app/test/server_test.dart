import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
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

  group('release = API_BASE 고정(저장값 무시) · debug = 입력칸으로 바꿈', () {
    test('release 는 저장된 옛 주소를 무시하고 save 도 안 한다', () async {
      SharedPreferences.setMockInitialValues({'server.apiBase': 'http://old.example:8700'});
      final c = ServerConfig(editable: false, defaultBase: 'https://ccc.example');
      await c.load();
      expect(c.base, 'https://ccc.example');
      await c.save('http://other:1');
      expect(c.base, 'https://ccc.example');
      expect((await SharedPreferences.getInstance()).getString('server.apiBase'), 'http://old.example:8700');
    });
    test('debug 는 저장된 주소를 쓰고 바꿀 수 있다', () async {
      SharedPreferences.setMockInitialValues({'server.apiBase': 'http://old.example:8700'});
      final c = ServerConfig(editable: true, defaultBase: 'https://ccc.example');
      await c.load();
      expect(c.base, 'http://old.example:8700');
      await c.save('192.0.2.1:8700/');
      expect(c.base, 'http://192.0.2.1:8700');
    });
  });
}
