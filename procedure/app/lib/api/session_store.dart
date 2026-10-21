// 토큰 · 로그인 계정 — iOS Keychain(flutter_secure_storage · SPEC-004 §3.2)
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../model/account.dart';

class SessionStore {
  static const _key = 'session';
  final FlutterSecureStorage _s = const FlutterSecureStorage(
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
  );

  Future<Session?> read() async {
    try {
      final raw = await _s.read(key: _key);
      if (raw == null) return null;
      final s = Session.fromJson((jsonDecode(raw) as Map).cast<String, dynamic>());
      return s.token.isEmpty ? null : s;
    } catch (_) {
      return null;
    }
  }

  Future<void> write(Session s) async {
    try {
      await _s.write(key: _key, value: jsonEncode(s.toJson()));
    } catch (_) {}
  }

  // 마지막 로그인 아이디(키체인 · 비밀번호는 저장하지 않는다) — 로그아웃해도 남긴다
  static const _idKey = 'login.lastId';
  Future<String?> readLastId() async {
    try {
      return await _s.read(key: _idKey);
    } catch (_) {
      return null;
    }
  }

  Future<void> writeLastId(String id) async {
    try {
      await _s.write(key: _idKey, value: id);
    } catch (_) {}
  }

  Future<void> clear() async {
    try {
      await _s.delete(key: _key);
    } catch (_) {}
  }
}
