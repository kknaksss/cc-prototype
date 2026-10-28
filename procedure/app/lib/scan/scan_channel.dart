// 카메라 · 글자 인식 채널(Runner TextScanner.swift · "procedure/scan") — 기기 안에서만 · 외부 서비스 0(D7-49)
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 사진은 메모리(Uint8List)로만 받고 디스크 · 사진첩에 쓰지 않는다(§6.16 원본 · D7-50)
import 'package:flutter/services.dart';

import 'mrz.dart';

class NoCamera implements Exception {
  const NoCamera();
}

class ScanChannel {
  final MethodChannel _ch;
  const ScanChannel([MethodChannel? ch]) : _ch = ch ?? const MethodChannel('procedure/scan');

  Future<T?> _call<T>(String m, [Object? args]) async {
    try {
      return await _ch.invokeMethod<T>(m, args);
    } on PlatformException catch (e) {
      if (e.code == 'no_camera') throw const NoCamera();
      rethrow;
    } on MissingPluginException {
      throw const NoCamera(); // 시험 · 채널 없음
    }
  }

  // QR 글자(닫으면 null)
  Future<String?> scanQr() => _call<String>('scanQr');

  // 여권 연속 스캔(E2E batch 1 #6) — 네이티브가 영상 프레임의 MRZ 자리를 계속 읽다가 후보 줄을 checkMrz 로 묻고,
  // 검사 숫자가 맞으면 그 프레임을 찍어 돌려준다. [닫기] = null · windowSec 초씩 windows 번 못 읽음 · [손으로 입력] = failed
  Future<PassportShot?> scanPassport({int windows = 3, double windowSec = 8}) async {
    _ch.setMethodCallHandler((c) async {
      if (c.method != 'checkMrz') return null;
      return isMrz([for (final x in (c.arguments is List ? c.arguments as List : const [])) if (x is String) x]);
    });
    final m = await _call<Map<Object?, Object?>>('scanPassport', {'windows': windows, 'windowSec': windowSec});
    if (m == null) return null;
    if (m['failed'] == true) return const PassportShot.failed();
    final photo = m['photo'];
    return PassportShot(
      photo: photo is Uint8List ? photo : null,
      lines: [for (final x in (m['lines'] is List ? m['lines'] as List : const [])) if (x is String) x],
    );
  }
}

// 네이티브가 묻는 후보 줄 — mrz.dart 의 검사 숫자 규칙 그대로(규칙 한 곳)
bool isMrz(List<String> lines) => findMrz(lines) != null;

class PassportShot {
  final Uint8List? photo; // 메모리만(법적 검토 필요 — 위 머리 주석)
  final List<String> lines;
  final bool failed;
  const PassportShot({this.photo, this.lines = const [], this.failed = false});
  const PassportShot.failed()
      : photo = null,
        lines = const [],
        failed = true;
}
