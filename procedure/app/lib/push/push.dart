// 원장 호출 푸시(SPEC-004 §5-1.1 · §5-1.3) — APNs 직접 · Firebase 0. 토큰 받기 = Runner AppDelegate 채널 "procedure/push"
import 'package:flutter/services.dart';

// 알림 payload → visitId — {aps, visitId, callId}. 숫자 · 문자열 둘 다 받는다
int? tapVisitId(Object? payload) {
  if (payload is! Map) return null;
  final v = payload['visitId'];
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v);
  return null;
}

enum NotifStatus { unknown, authorized, denied, notDetermined }

class PushChannel {
  final MethodChannel _ch;
  PushChannel([MethodChannel? ch]) : _ch = ch ?? const MethodChannel('procedure/push');

  void Function(String token)? onToken;
  void Function(int visitId)? onTap;

  // 시작 — 앱 쪽 콜백을 걸고, 눌러서 연 알림이 있으면 그 visitId
  Future<int?> ready() async {
    _ch.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'onToken':
          if (call.arguments is String && (call.arguments as String).isNotEmpty) onToken?.call(call.arguments as String);
        case 'onTap':
          final v = tapVisitId(call.arguments);
          if (v != null) onTap?.call(v);
      }
      return null;
    });
    try {
      return tapVisitId(await _ch.invokeMethod<Object?>('ready'));
    } catch (_) {
      return null; // 시험 · 채널 없음
    }
  }

  Future<bool> requestPermission() async {
    try {
      return await _ch.invokeMethod<bool>('requestPermission') ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<NotifStatus> status() async {
    try {
      return switch (await _ch.invokeMethod<String>('status')) {
        'authorized' => NotifStatus.authorized,
        'denied' => NotifStatus.denied,
        'notDetermined' => NotifStatus.notDetermined,
        _ => NotifStatus.unknown,
      };
    } catch (_) {
      return NotifStatus.unknown;
    }
  }

  // 알림 [수락](카테고리 CALL)을 앱 없이 보내려고 네이티브 키체인에 서버 주소 · 토큰을 둔다
  Future<void> setAuth(String base, String token) async {
    try {
      await _ch.invokeMethod<void>('setAuth', {'base': base, 'token': token});
    } catch (_) {}
  }

  Future<void> clearAuth() async {
    try {
      await _ch.invokeMethod<void>('clearAuth');
    } catch (_) {}
  }

  Future<void> register() async {
    try {
      await _ch.invokeMethod<void>('register');
    } catch (_) {}
  }
}
