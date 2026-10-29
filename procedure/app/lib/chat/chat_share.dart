// 바깥으로 — 공유 시트 · 링크 열기(SPEC-007 §10.7 · §10.4 · D9-46 · D9-56 · r3)
// 공유 = iOS 공유 시트(share_plus) · 「이미지 저장」 · 「비디오 저장」(saveToCameraRoll)을 뺀다(D9-24 · D9-56) — 다른 앱으로 보내기는 막지 않는다.
// 사진 · 동영상은 앱 임시 폴더에 파일로 넘기고 시트가 닫히면 지운다(OQ-956). 아이패드 = 그 말풍선에서 나오는 팝오버(sharePositionOrigin).
// 링크 = 기기 브라우저(url_launcher externalApplication · 앱 안 브라우저 · 미리보기 카드 없음)
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' show Rect;

import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

const shareExcluded = [CupertinoActivityType.saveToCameraRoll];
const shareFailed = '공유하지 못했어요';

typedef ShareFn = Future<void> Function(ShareParams params);
typedef LinkOpener = Future<void> Function(Uri uri);

// 시험이 바꿔 끼운다(인자 확인 · 플랫폼 시트 없음)
ShareFn shareChat = (p) async {
  await SharePlus.instance.share(p);
};
LinkOpener openChatLink = (u) async {
  await launchUrl(u, mode: LaunchMode.externalApplication);
};

Future<void> shareText(String text, {Rect? origin}) =>
    shareChat(ShareParams(text: text, sharePositionOrigin: origin, excludedCupertinoActivities: shareExcluded));

// 공유용 임시 폴더(시트가 닫히면 통째로 지움)
Future<Directory> shareDir() => Directory.systemTemp.createTemp('chat-share-');

Future<void> shareFileIn(Directory dir, String path, String mime, {Rect? origin}) async {
  try {
    await shareChat(ShareParams(files: [XFile(path, mimeType: mime)], sharePositionOrigin: origin, excludedCupertinoActivities: shareExcluded));
  } finally {
    try {
      await dir.delete(recursive: true);
    } catch (_) {}
  }
}

// 사진(메모리의 JPEG) → 임시 파일 → 공유 → 지움
Future<void> sharePhoto(Uint8List jpeg, {Rect? origin}) async {
  final dir = await shareDir();
  final f = File('${dir.path}/photo.jpg');
  await f.writeAsBytes(jpeg, flush: true);
  await shareFileIn(dir, f.path, 'image/jpeg', origin: origin);
}
