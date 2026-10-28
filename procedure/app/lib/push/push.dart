// 푸시(SPEC-004 §5-1 · §5-2 · §5-3) — APNs 직접 · Firebase 0. 토큰 받기 = Runner AppDelegate 채널 "procedure/push"
import 'package:flutter/services.dart';

int? _int(Object? v) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v);
  return null;
}

// 알림 payload 종류 — 없으면 doctor_call(옛 빌드 · §5-2 「원장 호출 payload」)
enum PushKind { doctorCall, counselorCall, display }

// 누른 알림 — 원장 호출 {visitId, callId} · 상담사 호출 {kind, reservationId} · 띄우기 {kind, requestId}
class PushTap {
  final PushKind kind;
  final int? visitId;
  final int? callId;
  final int? reservationId;
  final int? requestId;
  const PushTap(this.kind, {this.visitId, this.callId, this.reservationId, this.requestId});

  static PushTap? parse(Object? payload) {
    if (payload is! Map) return null;
    final kind = switch (payload['kind']) {
      'counselor_call' => PushKind.counselorCall,
      'display' => PushKind.display,
      _ => PushKind.doctorCall,
    };
    final t = PushTap(kind,
        visitId: _int(payload['visitId']),
        callId: _int(payload['callId']),
        reservationId: _int(payload['reservationId']),
        requestId: _int(payload['requestId']));
    final ok = switch (kind) {
      PushKind.doctorCall => t.visitId != null,
      PushKind.counselorCall => t.reservationId != null,
      PushKind.display => t.requestId != null,
    };
    return ok ? t : null;
  }
}

// 알림 payload → visitId(원장 호출만) — 숫자 · 문자열 둘 다 받는다
int? tapVisitId(Object? payload) {
  final t = PushTap.parse(payload);
  return t?.kind == PushKind.doctorCall ? t!.visitId : null;
}

enum NotifStatus { unknown, authorized, denied, notDetermined }

class PushChannel {
  final MethodChannel _ch;
  PushChannel([MethodChannel? ch]) : _ch = ch ?? const MethodChannel('procedure/push');

  void Function(String token)? onToken;
  void Function(PushTap tap)? onTap;

  // 시작 — 앱 쪽 콜백을 걸고, 눌러서 연 알림이 있으면 그 payload
  Future<PushTap?> ready() async {
    _ch.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'onToken':
          if (call.arguments is String && (call.arguments as String).isNotEmpty) onToken?.call(call.arguments as String);
        case 'onTap':
          final t = PushTap.parse(call.arguments);
          if (t != null) onTap?.call(t);
      }
      return null;
    });
    try {
      return PushTap.parse(await _ch.invokeMethod<Object?>('ready'));
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

  // iOS 기기 이름(UIDevice.name) — POST /api/devices name 의 처음 값(§5-1.1 · D7-27)
  Future<String?> deviceName() async {
    try {
      return await _ch.invokeMethod<String>('deviceName');
    } catch (_) {
      return null;
    }
  }

  // 앱 버전 · 빌드(Info.plist) — 설정 「앱 정보」(§6.14)
  Future<String?> appVersion() async {
    try {
      final m = await _ch.invokeMapMethod<String, Object?>('appVersion');
      if (m == null) return null;
      final v = '${m['version'] ?? ''}', b = '${m['build'] ?? ''}';
      return b.isEmpty ? v : '$v ($b)';
    } catch (_) {
      return null;
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
