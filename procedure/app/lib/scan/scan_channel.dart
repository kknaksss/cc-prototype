// 카메라 · 글자 인식 채널(Runner TextScanner.swift · "procedure/scan") — 기기 안에서만 · 외부 서비스 0(D7-49)
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 사진은 메모리(Uint8List)로만 받고 디스크 · 사진첩에 쓰지 않는다(§6.16 원본 · D7-50)
import 'package:flutter/services.dart';

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

  // 여권 사진면 JPEG(긴 변 2000 · 0.8 · 닫으면 null)
  Future<Uint8List?> takePassportPhoto() => _call<Uint8List>('takePassportPhoto');

  // 기기 안 글자 인식(iOS Vision) — 줄 목록
  Future<List<String>> recognizeText(Uint8List jpeg) async {
    final l = await _call<List<Object?>>('recognizeText', jpeg);
    return [for (final x in l ?? const []) if (x is String) x];
  }
}
