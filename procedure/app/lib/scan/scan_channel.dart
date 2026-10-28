// 카메라 · 글자 인식 채널(Runner TextScanner.swift · "procedure/scan") — 기기 안에서만 · 외부 서비스 0(D7-49)
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 사진은 메모리(Uint8List)로만 받고 디스크 · 사진첩에 쓰지 않는다(§6.16 원본 · D7-50)
import 'package:flutter/foundation.dart' show kDebugMode;
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

  // 문진 QR 화면(SPEC-006 §8.2) — qrUrl → QR PNG(기기 안 CoreImage) · 못 그리면 null
  Future<Uint8List?> qrImage(String text, {double size = 600}) async {
    try {
      return await _ch.invokeMethod<Uint8List>('qrImage', {'text': text, 'size': size});
    } catch (_) {
      return null;
    }
  }

  // 화면 꺼짐 막기(QR 화면이 떠 있는 동안) — 시험 · 채널 없음 = 조용히
  Future<void> keepAwake(bool on) async {
    try {
      await _ch.invokeMethod<void>('keepAwake', on);
    } catch (_) {}
  }

  // 여권 연속 스캔(E2E batch 1 #6 · batch 2 #4) — 네이티브가 영상 프레임의 MRZ 자리를 계속 읽어 줄마다 checkMrz 로 묻는다.
  // 답 = none(줄 없음) · lines(두 줄 읽음 · 검사 숫자 안 맞음) · pending(맞음 한 번 · 확인 중) · confirmed(같은 판독 연속 두 번 → 자동 촬영)
  // [촬영] = 사람이 찍은 그 사진의 글자(shutter) · [닫기] = null · windowSec 초씩 windows 번 못 읽음 · [손으로 입력] = failed
  // debug = 인식 글자 오버레이(debug 빌드만 · 원인 확인용)
  Future<PassportShot?> scanPassport({int windows = 3, double windowSec = 8, bool debug = kDebugMode}) async {
    final confirm = MrzConfirm();
    _ch.setMethodCallHandler((c) async {
      if (c.method != 'checkMrz') return null;
      return confirm.feed([for (final x in (c.arguments is List ? c.arguments as List : const [])) if (x is String) x]);
    });
    final m = await _call<Map<Object?, Object?>>('scanPassport', {'windows': windows, 'windowSec': windowSec, 'debug': debug});
    if (m == null) return null;
    if (m['failed'] == true) return const PassportShot.failed();
    final photo = m['photo'];
    return PassportShot(
      photo: photo is Uint8List ? photo : null,
      lines: [for (final x in (m['lines'] is List ? m['lines'] as List : const [])) if (x is String) x],
      shutter: m['shutter'] == true,
    );
  }
}

// 네이티브가 묻는 후보 줄 — mrz.dart 의 검사 숫자 규칙 그대로(규칙 한 곳)
bool isMrz(List<String> lines) => findMrz(lines) != null;

class PassportShot {
  final Uint8List? photo; // 메모리만(법적 검토 필요 — 위 머리 주석)
  final List<String> lines;
  final bool failed;
  final bool shutter; // [촬영] 버튼으로 사람이 찍음(자동 확정 아님)
  const PassportShot({this.photo, this.lines = const [], this.failed = false, this.shutter = false});
  const PassportShot.failed()
      : photo = null,
        lines = const [],
        failed = true,
        shutter = false;
}
