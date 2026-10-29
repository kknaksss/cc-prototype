// 채팅 사진 고르기 · 찍기(§9 · §10.6) — image_picker(긴 변 2048) → 늘 JPEG 로 다시 인코딩(flutter_image_compress · 85).
// iOS image_picker 는 PNG(스크린샷)에 imageQuality 를 안 걸고 PNG 로 돌려줄 수 있어 고른 파일을 그대로 올리지 않는다.
// 카메라 사진은 사진첩에 저장하지 않는다(image_picker 카메라 = 저장 안 함 · D9-24). 받은 임시 파일은 읽은 뒤 바로 지운다.
// r3(§10.6 · §9.3): [+] 시트 최근 줄 = photo_manager(사진 보관함 읽기 · limited) · 「사진」 메뉴 = pickMultipleMedia(limit: 10) ·
// 어디서 왔든 사진 = 이 JPEG 길(jpegOf) · 동영상 = video_pick.dart
import 'dart:io' show Directory, File;
import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:flutter_image_compress/flutter_image_compress.dart';
import 'package:image_picker/image_picker.dart';
import 'package:photo_manager/photo_manager.dart';

import 'chat_model.dart';
import 'video_pick.dart';

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
  return jpegOf(f.path, deleteSource: true);
}

// 파일(HEIC · HEIF · JPEG · PNG · 라이브 포토 정지 컷) → 긴 변 2048 JPEG 85(§9.1 · D9-51) — 못 읽으면 null
Future<PickedPhoto?> jpegOf(String path, {bool deleteSource = false}) async {
  try {
    var out = await _jpeg(path, maxPhotoSide, maxPhotoSide);
    if (out == null) return null;
    var (w, h) = await photoSize(out);
    // 피커가 줄이지 못한 큰 원본 — 긴 변을 2048 로(압축기는 「짧은 쪽 맞춤」이라 목표 크기를 다시 준다)
    if (w > maxPhotoSide || h > maxPhotoSide) {
      final k = maxPhotoSide / (w > h ? w : h);
      out = await _jpeg(path, (w * k).floor(), (h * k).floor()) ?? out;
      (w, h) = await photoSize(out);
    }
    return PickedPhoto(out, w, h);
  } finally {
    if (deleteSource) await deleteTemp(path);
  }
}

typedef PhotoEncoder = Future<PickedPhoto?> Function(String path, {bool deleteSource});

PhotoEncoder encodeChatPhoto = jpegOf; // 시험이 바꿔 끼운다(네이티브 인코더 없음)

// 사진 하나 → 보낼 것(실패 = 1판 문구 토스트 · 그 하나만 빠짐)
Future<PreparedMedia> _photoMedia(Future<String?> Function() file, {bool deleteSource = false}) async {
  final path = await file();
  if (path == null) throw const MediaRejected(photoFailed);
  PickedPhoto? p;
  try {
    p = await encodeChatPhoto(path, deleteSource: deleteSource);
  } catch (_) {}
  if (p == null) throw const MediaRejected(photoFailed);
  return PreparedPhoto(p.jpeg, p.width, p.height);
}

const photoFailed = '사진을 불러오지 못했어요';
const pickLimit = 10; // 한 번에 10개(D9-50)
const pickLimitText = '한 번에 10개까지 보낼 수 있어요';

// ─── 「사진」 메뉴 = 기기 갤러리(iOS 사진 고르기 · 사진 + 동영상 · 여러 개 · 권한 없이 됨) — 고른 차례 · 앞 10개(플랫폼이 limit 을 안 받을 수 있음)
typedef GalleryPicker = Future<List<MediaItem>> Function();

GalleryPicker pickChatGallery = _gallery; // 시험이 바꿔 끼운다

const _videoExt = {'mov', 'mp4', 'm4v', '3gp', 'avi', 'hevc'};

bool isVideoPath(String path, String? mime) =>
    (mime?.startsWith('video/') ?? false) || _videoExt.contains(path.split('.').last.toLowerCase());

Future<List<MediaItem>> _gallery() async {
  final List<XFile> files;
  try {
    files = await ImagePicker().pickMultipleMedia(
        maxWidth: maxPhotoSide.toDouble(), maxHeight: maxPhotoSide.toDouble(), limit: pickLimit, requestFullMetadata: false);
  } on PlatformException catch (e) {
    if (e.code.contains('access_denied')) throw const PhotoDenied();
    rethrow;
  }
  for (final f in files.skip(pickLimit)) {
    await deleteTemp(f.path);
  }
  return [
    for (final f in files.take(pickLimit))
      isVideoPath(f.path, f.mimeType)
          ? MediaItem(video: true, prepare: () => prepareVideo(f.path, deleteSource: true))
          : MediaItem(video: false, prepare: () => _photoMedia(() async => f.path, deleteSource: true)),
  ];
}

// ─── 최근 줄(사진 보관함 · 새것 왼쪽 · 60개씩) — 읽기 권한이 있어야 그린다 · limited = 고른 항목만 + [더 고르기]
enum MediaAccess { full, limited, denied }

class RecentItem {
  final String id;
  final bool video;
  final int durationMs; // 동영상 길이(사진 보관함 값 — photo_manager 는 초로 반올림한 값만 준다) · 사진 = 0
  const RecentItem(this.id, {this.video = false, this.durationMs = 0});
  // 흐림 = 181초 이상(반올림 181 = 실제 180.5초 이상 → 확실히 3분 넘음). 3:00 으로 보이는 180.0 ~ 180.49초는 흐리지 않고
  // 보내기 직전 실제 ms(prepareVideo 의 probe)로 다시 막는다(review-code r2 W-1)
  bool get tooLong => video && durationMs > maxVideoMs;
}

// 앱 임시 폴더 안 사본인가(photo_manager 는 NSTemporaryDirectory 아래에 내보낸다) — 그 파일만 지운다(사진 보관함 원본은 건드리지 않음)
bool isTempCopy(String path) {
  try {
    final tmp = Directory.systemTemp.resolveSymbolicLinksSync();
    return File(path).resolveSymbolicLinksSync().startsWith('$tmp/');
  } catch (_) {
    return false;
  }
}

abstract class RecentMedia {
  Future<MediaAccess> access();
  Future<List<RecentItem>> page(int page, {int size = 60});
  Future<Uint8List?> thumb(RecentItem item);
  Future<String?> file(RecentItem item);
  Future<void> pickMoreLimited();
  Future<void> openSettings();
  // 고른 항목 → 보낼 것(사진 = JPEG 길 · 동영상 = 3분 검사 → 변환). photo_manager 가 내보낸 사본은 항목마다 바꾼 뒤 그 파일만 지운다
  // (전역 clearFileCache 를 쓰지 않음 — 다른 묶음이 아직 쓰는 사본을 지우지 않게 · review-code r2 W-3)
  MediaItem item(RecentItem it, {Uint8List? preview}) => it.video
      ? MediaItem(
          video: true,
          preview: preview,
          prepare: () async {
            if (it.tooLong) throw const MediaRejected(videoTooLong);
            final path = await file(it);
            if (path == null) throw const MediaRejected(videoFailed);
            return prepareVideo(path, deleteSource: isTempCopy(path));
          })
      : MediaItem(
          video: false,
          preview: preview,
          prepare: () async {
            final path = await file(it);
            return _photoMedia(() async => path, deleteSource: path != null && isTempCopy(path));
          });
}

class PhotoManagerMedia extends RecentMedia {
  @override
  Future<MediaAccess> access() async {
    try {
      final s = await PhotoManager.requestPermissionExtend();
      return switch (s) {
        PermissionState.authorized => MediaAccess.full,
        PermissionState.limited => MediaAccess.limited,
        _ => MediaAccess.denied,
      };
    } catch (_) {
      return MediaAccess.denied;
    }
  }

  @override
  Future<List<RecentItem>> page(int page, {int size = 60}) async {
    final l = await PhotoManager.getAssetListPaged(
      page: page,
      pageCount: size,
      type: RequestType.common,
      filterOption: FilterOptionGroup(orders: [const OrderOption(type: OrderOptionType.createDate, asc: false)]),
    );
    return [for (final a in l) RecentItem(a.id, video: a.type == AssetType.video, durationMs: a.type == AssetType.video ? a.duration * 1000 : 0)];
  }

  @override
  Future<Uint8List?> thumb(RecentItem item) async =>
      (await AssetEntity.fromId(item.id))?.thumbnailDataWithSize(const ThumbnailSize.square(240), quality: 80);

  @override
  Future<String?> file(RecentItem item) async => (await (await AssetEntity.fromId(item.id))?.file)?.path;

  @override
  Future<void> pickMoreLimited() => PhotoManager.presentLimited();

  @override
  Future<void> openSettings() => PhotoManager.openSetting();
}

RecentMedia recentMedia = PhotoManagerMedia(); // 시험이 바꿔 끼운다

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
