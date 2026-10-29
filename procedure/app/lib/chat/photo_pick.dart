// 채팅 사진 고르기 · 찍기(§9 · §10.6) — image_picker(긴 변 2048) → 늘 JPEG 로 다시 인코딩(flutter_image_compress · 85).
// iOS image_picker 는 PNG(스크린샷)에 imageQuality 를 안 걸고 PNG 로 돌려줄 수 있어 고른 파일을 그대로 올리지 않는다.
// 카메라 사진은 사진첩에 저장하지 않는다(image_picker 카메라 = 저장 안 함 · D9-24). 받은 임시 파일은 읽은 뒤 바로 지운다
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:flutter_image_compress/flutter_image_compress.dart';
import 'package:image_picker/image_picker.dart';

enum PhotoSource { camera, album }

class PickedPhoto {
  final Uint8List jpeg;
  final int width, height;
  const PickedPhoto(this.jpeg, this.width, this.height);
}

// 권한 거부(§10.6) — 화면이 토스트 「설정에서 카메라(사진) 권한을 켜 주세요」
class PhotoDenied implements Exception {
  const PhotoDenied();
}

const maxPhotoSide = 2048;
const photoQuality = 85;

typedef PhotoPicker = Future<PickedPhoto?> Function(PhotoSource source);

// 시험이 바꿔 끼운다
PhotoPicker pickChatPhoto = _pick;

Future<PickedPhoto?> _pick(PhotoSource source) async {
  XFile? f;
  try {
    f = await ImagePicker().pickImage(
      source: source == PhotoSource.camera ? ImageSource.camera : ImageSource.gallery,
      maxWidth: maxPhotoSide.toDouble(),
      maxHeight: maxPhotoSide.toDouble(),
      requestFullMetadata: false,
    );
  } on PlatformException catch (e) {
    if (e.code.contains('access_denied')) throw const PhotoDenied();
    rethrow;
  }
  if (f == null) return null;
  try {
    var out = await _jpeg(f.path, maxPhotoSide, maxPhotoSide);
    if (out == null) return null;
    var (w, h) = await photoSize(out);
    // 피커가 줄이지 못한 큰 원본 — 긴 변을 2048 로(압축기는 「짧은 쪽 맞춤」이라 목표 크기를 다시 준다)
    if (w > maxPhotoSide || h > maxPhotoSide) {
      final k = maxPhotoSide / (w > h ? w : h);
      out = await _jpeg(f.path, (w * k).floor(), (h * k).floor()) ?? out;
      (w, h) = await photoSize(out);
    }
    return PickedPhoto(out, w, h);
  } finally {
    try {
      await File(f.path).delete();
    } catch (_) {}
  }
}

Future<Uint8List?> _jpeg(String path, int minWidth, int minHeight) =>
    FlutterImageCompress.compressWithFile(path, minWidth: minWidth, minHeight: minHeight, quality: photoQuality, format: CompressFormat.jpeg);

// 픽셀 크기(말풍선 자리 잡기 · 서버 width · height)
Future<(int, int)> photoSize(Uint8List bytes) async {
  final codec = await ui.instantiateImageCodec(bytes);
  final frame = await codec.getNextFrame();
  final r = (frame.image.width, frame.image.height);
  frame.image.dispose();
  codec.dispose();
  return r;
}
