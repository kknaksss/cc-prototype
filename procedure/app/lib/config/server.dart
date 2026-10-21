// 서버 주소(SPEC-004 §2.2) — 빌드 기본값 = --dart-define=API_BASE.
// debug 빌드만 로그인 화면 입력칸으로 바꾸고 기기에 저장(로컬 시뮬레이터 확인용) · release(TestFlight)는 API_BASE 고정 —
// 저장돼 있던 옛 주소도 무시한다(2026-10-21 사용자 결정). 맥 IP 값은 레포에 쓰지 않는다(빌드 인자 · 입력칸에만).
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String kDefaultApiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://localhost:8700');
const _key = 'server.apiBase';

// 입력값 정리 — 앞뒤 공백 · 끝 / 제거, 스킴이 없으면 http://
String normalizeBase(String raw) {
  var v = raw.trim();
  while (v.endsWith('/')) {
    v = v.substring(0, v.length - 1);
  }
  if (v.isEmpty) return v;
  if (!v.contains('://')) v = 'http://$v';
  return v;
}

// 맞는 주소인가 — http(s) · 호스트 있음
bool isValidBase(String base) {
  final u = Uri.tryParse(base);
  return u != null && (u.scheme == 'http' || u.scheme == 'https') && u.host.isNotEmpty;
}

// 통역 주소 — http → ws · https → wss + /api/interpret
Uri interpretUri(String base) {
  final u = Uri.parse(normalizeBase(base));
  final scheme = u.scheme == 'https' ? 'wss' : 'ws';
  final path = '${u.path.endsWith('/') ? u.path.substring(0, u.path.length - 1) : u.path}/api/interpret';
  return u.replace(scheme: scheme, path: path, query: null, fragment: null);
}

class ServerConfig {
  // 주소를 바꿀 수 있나 — debug 빌드만(시험에서는 넘겨 준다)
  final bool editable;
  final String defaultBase;
  ServerConfig({bool? editable, String? defaultBase})
      : editable = editable ?? kDebugMode,
        defaultBase = normalizeBase(defaultBase ?? kDefaultApiBase);

  late String _base = defaultBase;
  String get base => _base;

  Future<void> load() async {
    if (!editable) return; // release — 저장값 무시 · API_BASE 그대로
    try {
      final p = await SharedPreferences.getInstance();
      final saved = p.getString(_key);
      if (saved != null && isValidBase(saved)) _base = saved;
    } catch (_) {
      // 저장소를 못 읽으면 빌드 기본값
    }
  }

  Future<void> save(String raw) async {
    if (!editable) return;
    _base = normalizeBase(raw);
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString(_key, _base);
    } catch (_) {}
  }
}
