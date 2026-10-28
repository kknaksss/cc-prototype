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
  // ccc:// 링크로 앱이 열림(웹 QR 을 iOS 기본 카메라로 · E2E batch 1 #5)
  void Function(String url)? onLink;

  // 시작 — 앱 쪽 콜백을 걸고, 눌러서 연 알림이 있으면 그 payload
  Future<PushTap?> ready() async {
    _ch.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'onToken':
          if (call.arguments is String && (call.arguments as String).isNotEmpty) onToken?.call(call.arguments as String);
        case 'onTap':
          final t = PushTap.parse(call.arguments);
          if (t != null) onTap?.call(t);
        case 'onForeground':
          // 앞에서 받은 띄우기 푸시(배너 없음) — 누른 것과 같은 길(pending 읽어 엶)
          final t = PushTap.parse(call.arguments);
          if (t != null) onTap?.call(t);
        case 'onLink':
          if (call.arguments is String) onLink?.call(call.arguments as String);
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

  // 기본 기기 이름 = 기종 이름(E2E batch 2 #3) — 기종 코드(utsname.machine) → 「iPhone 15 Pro」 · 「iPad Pro 11-inch」.
  // POST /api/devices name 의 처음 값(§5-1.1 · D7-27). iOS 16+ 의 UIDevice.name 은 entitlement 없이 늘 「iPhone」이라 쓰지 않는다
  Future<String?> deviceName() async {
    try {
      final code = await _ch.invokeMethod<String>('deviceModel');
      return code == null || code.isEmpty ? null : modelName(code);
    } catch (_) {
      return null;
    }
  }

  // 설치 단위 id(identifierForVendor · 키체인 · E2E batch 1 #1) — POST /api/devices installId. 토큰이 바뀌어도 같은 값
  Future<String?> installId() async {
    try {
      final v = await _ch.invokeMethod<String>('installId');
      return v == null || v.isEmpty ? null : v;
    } catch (_) {
      return null;
    }
  }

  // 꺼진 상태에서 링크로 열렸으면 그 링크(한 번만)
  Future<String?> takeLink() async {
    try {
      return await _ch.invokeMethod<String>('takeLink');
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

// 기종 코드 → 이름(E2E batch 2 #3). 모르는 코드 = 「iPhone (iPhone19,1)」 · 「iPad (iPad17,1)」 꼴 — 코드는 남겨 구분이 된다
String modelName(String code) {
  final n = _models[code];
  if (n != null) return n;
  if (code.startsWith('iPhone')) return 'iPhone ($code)';
  if (code.startsWith('iPad')) return 'iPad ($code)';
  return code;
}

const _models = {
  'iPhone10,3': 'iPhone X', 'iPhone10,6': 'iPhone X',
  'iPhone11,2': 'iPhone XS', 'iPhone11,4': 'iPhone XS Max', 'iPhone11,6': 'iPhone XS Max', 'iPhone11,8': 'iPhone XR',
  'iPhone12,1': 'iPhone 11', 'iPhone12,3': 'iPhone 11 Pro', 'iPhone12,5': 'iPhone 11 Pro Max', 'iPhone12,8': 'iPhone SE (2nd)',
  'iPhone13,1': 'iPhone 12 mini', 'iPhone13,2': 'iPhone 12', 'iPhone13,3': 'iPhone 12 Pro', 'iPhone13,4': 'iPhone 12 Pro Max',
  'iPhone14,4': 'iPhone 13 mini', 'iPhone14,5': 'iPhone 13', 'iPhone14,2': 'iPhone 13 Pro', 'iPhone14,3': 'iPhone 13 Pro Max',
  'iPhone14,6': 'iPhone SE (3rd)',
  'iPhone14,7': 'iPhone 14', 'iPhone14,8': 'iPhone 14 Plus', 'iPhone15,2': 'iPhone 14 Pro', 'iPhone15,3': 'iPhone 14 Pro Max',
  'iPhone15,4': 'iPhone 15', 'iPhone15,5': 'iPhone 15 Plus', 'iPhone16,1': 'iPhone 15 Pro', 'iPhone16,2': 'iPhone 15 Pro Max',
  'iPhone17,3': 'iPhone 16', 'iPhone17,4': 'iPhone 16 Plus', 'iPhone17,1': 'iPhone 16 Pro', 'iPhone17,2': 'iPhone 16 Pro Max',
  'iPhone17,5': 'iPhone 16e',
  'iPhone18,1': 'iPhone 17 Pro', 'iPhone18,2': 'iPhone 17 Pro Max', 'iPhone18,3': 'iPhone 17', 'iPhone18,4': 'iPhone Air',
  'iPad12,1': 'iPad (9th)', 'iPad12,2': 'iPad (9th)', 'iPad13,18': 'iPad (10th)', 'iPad13,19': 'iPad (10th)',
  'iPad15,7': 'iPad (A16)', 'iPad15,8': 'iPad (A16)',
  'iPad14,1': 'iPad mini (6th)', 'iPad14,2': 'iPad mini (6th)', 'iPad16,1': 'iPad mini (A17 Pro)', 'iPad16,2': 'iPad mini (A17 Pro)',
  'iPad13,1': 'iPad Air (4th)', 'iPad13,2': 'iPad Air (4th)', 'iPad13,16': 'iPad Air (5th)', 'iPad13,17': 'iPad Air (5th)',
  'iPad14,8': 'iPad Air 11-inch (M2)', 'iPad14,9': 'iPad Air 11-inch (M2)', 'iPad14,10': 'iPad Air 13-inch (M2)', 'iPad14,11': 'iPad Air 13-inch (M2)',
  'iPad15,3': 'iPad Air 11-inch (M3)', 'iPad15,4': 'iPad Air 11-inch (M3)', 'iPad15,5': 'iPad Air 13-inch (M3)', 'iPad15,6': 'iPad Air 13-inch (M3)',
  'iPad13,4': 'iPad Pro 11-inch (3rd)', 'iPad13,5': 'iPad Pro 11-inch (3rd)', 'iPad13,6': 'iPad Pro 11-inch (3rd)', 'iPad13,7': 'iPad Pro 11-inch (3rd)',
  'iPad13,8': 'iPad Pro 12.9-inch (5th)', 'iPad13,9': 'iPad Pro 12.9-inch (5th)', 'iPad13,10': 'iPad Pro 12.9-inch (5th)', 'iPad13,11': 'iPad Pro 12.9-inch (5th)',
  'iPad14,3': 'iPad Pro 11-inch (4th)', 'iPad14,4': 'iPad Pro 11-inch (4th)', 'iPad14,5': 'iPad Pro 12.9-inch (6th)', 'iPad14,6': 'iPad Pro 12.9-inch (6th)',
  'iPad16,3': 'iPad Pro 11-inch (M4)', 'iPad16,4': 'iPad Pro 11-inch (M4)', 'iPad16,5': 'iPad Pro 13-inch (M4)', 'iPad16,6': 'iPad Pro 13-inch (M4)',
};
