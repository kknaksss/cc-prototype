// 채팅 동영상 바꾸기(SPEC-007 §9.2 · D9-51 · D9-52 · r3) — iOS 네이티브 채널 "procedure/video"(Runner AppDelegate.swift VideoConverter):
//   probe({path}) → {durationMs} · convert({path}) → {path, width, height, durationMs, bytes, thumb}
//   = AVAssetExportSession(AVAssetExportPreset1280x720 · .mp4 · H.264 · AAC) + AVAssetImageGenerator(0초 · JPEG 80 · 변환 뒤와 같은 크기).
// video_compress 3.1.4(§9.3 권장)는 쓰지 않는다 — 내보내기 실패를 오류로 돌려주지 않고(빈 결과 → Dart 쪽 path! 에서 죽음) ·
// 한 번에 하나만 받아(isCompressing) 여러 개 · 다시 보내기 길에 맞지 않는다. §9.3 의 대안(네이티브 채널) 그대로.
// 변환 뒤 파일 · 썸네일은 앱 임시 폴더에만 — 보내기 끝 · 실패 말풍선 지움 · 로그아웃 때 지운다(D9-24 · §9.2 「변환 파일」)
import 'dart:io';

import 'package:flutter/services.dart';

import 'chat_model.dart';

const maxVideoMs = 180000; // 3분(D9-52)
const maxVideoBytes = 90 * 1024 * 1024; // 변환 뒤 본 파일 90MB(r3 처분 D-58 — SPEC 100MB 자리 전부)
const videoTooLong = '3분 이하 동영상만 보낼 수 있어요';
const videoTooLarge = '동영상이 90MB 를 넘어요';
const videoFailed = '동영상을 보내지 못했어요';

class VideoChannel {
  final MethodChannel _ch;
  const VideoChannel([MethodChannel? ch]) : _ch = ch ?? const MethodChannel('procedure/video');

  // 길이(밀리초) — 못 읽으면 null
  Future<int?> durationMs(String path) async {
    try {
      final r = await _ch.invokeMapMethod<String, dynamic>('probe', {'path': path});
      final v = r?['durationMs'];
      return v is num ? v.toInt() : null;
    } catch (_) {
      return null;
    }
  }

  // H.264 MP4 1280 + 0초 썸네일 — 실패 = null
  Future<PreparedVideo?> convert(String path) async {
    try {
      final r = await _ch.invokeMapMethod<String, dynamic>('convert', {'path': path});
      if (r == null) return null;
      final out = r['path'], thumb = r['thumb'];
      if (out is! String || thumb is! Uint8List) return null;
      int n(Object? v) => v is num ? v.toInt() : 0;
      return PreparedVideo(out, thumb, n(r['width']), n(r['height']), n(r['durationMs']), n(r['bytes']));
    } catch (_) {
      return null;
    }
  }

  // 재생 화면 오디오 세션(무음 스위치를 따름 · W-4) — 채널 없음(시험) = 조용히
  Future<void> _audio(String m) async {
    try {
      await _ch.invokeMethod<Object?>(m);
    } catch (_) {}
  }

  Future<void> audioSave() => _audio('audioSave');
  Future<void> audioFollowSilent() => _audio('audioFollowSilent');
  Future<void> audioRestore() => _audio('audioRestore');
}

typedef VideoConverter = Future<PreparedVideo?> Function(String path);
typedef VideoProbe = Future<int?> Function(String path);

// 시험이 바꿔 끼운다
VideoConverter convertChatVideo = const VideoChannel().convert;
VideoProbe probeChatVideo = const VideoChannel().durationMs;

// 고른 원본 → 길이 검사(3분) → 변환 → 90MB 검사. 넘거나 실패 = MediaRejected(토스트 문구) · 변환 파일은 거절 때 바로 지움.
// 3분 규칙 = 서버와 같은 하나(durationMs > 180000 = 못 보냄 · 봐 주기 없음 — review-code r2 W-1): 바꾸기 전 받은 파일의 실제 ms(probe) ·
// 바꾼 뒤 올릴 값(변환 뒤 실제 ms) 둘 다 같은 규칙. 최근 줄 길이(사진 보관함 · 초 반올림)는 흐림에만 쓰고 여기서는 쓰지 않는다
Future<PreparedVideo> prepareVideo(String source, {bool deleteSource = false}) async {
  try {
    final ms = await probeChatVideo(source);
    if (ms != null && ms > maxVideoMs) throw const MediaRejected(videoTooLong);
    final v = await convertChatVideo(source);
    if (v == null) throw const MediaRejected(videoFailed);
    if (v.durationMs > maxVideoMs) {
      await deleteTemp(v.path);
      throw const MediaRejected(videoTooLong);
    }
    if (v.bytes > maxVideoBytes) {
      await deleteTemp(v.path);
      throw const MediaRejected(videoTooLarge);
    }
    return v;
  } finally {
    if (deleteSource) await deleteTemp(source);
  }
}

Future<void> deleteTemp(String? path) async {
  if (path == null) return;
  try {
    await File(path).delete();
  } catch (_) {}
}
