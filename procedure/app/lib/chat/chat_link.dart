// 링크 열기(SPEC-007 §10.4 · D9-46) — 기기 브라우저(url_launcher externalApplication · 앱 안 브라우저 · 미리보기 카드 없음).
// r4(D9-62): iOS 시스템 공유 시트 · 공유용 임시 파일 · 동영상 내려받기는 없어졌다 — [공유] = 앱 안 전달(chat_forward_sheet.dart)
import 'package:url_launcher/url_launcher.dart';

typedef LinkOpener = Future<void> Function(Uri uri);

// 시험이 바꿔 끼운다
LinkOpener openChatLink = (u) async {
  await launchUrl(u, mode: LaunchMode.externalApplication);
};
