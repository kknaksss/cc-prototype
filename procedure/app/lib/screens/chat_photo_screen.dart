// 채팅 사진 크게 보기(SPEC-007 §10.6 · DS:S8) — 검정 전체 화면 · [닫기] · 보낸 사람 · 시각 · 저장 · 공유 · 확대 · 넘기기 없음(D9-24 · D9-36).
// 크게 보기에서는 메뉴가 없다(§10.7). 1판 [사진] 시트(1장씩)는 r3 [+] 시트(chat_attach_sheet.dart)로 바뀌었다(D9-48)
import 'package:flutter/material.dart';

import '../chat/chat_model.dart';
import '../chat/chat_view.dart';
import '../theme/tokens.dart';
import 'chat_room_screen.dart' show ChatPhoto;

// 크게 보기 — 루트 전체 화면(탭 · 배너 위 · OQ-933)
Future<void> openPhotoViewer(BuildContext context, ChatMessage m) {
  final ref = m.photo;
  if (ref == null || m.deleted) return Future.value();
  return Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(fullscreenDialog: true, builder: (_) => ChatPhotoViewer(message: m)));
}

class ChatPhotoViewer extends StatelessWidget {
  final ChatMessage message;
  const ChatPhotoViewer({super.key, required this.message});

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Ms.black,
        body: SafeArea(
          child: Column(children: [
            SizedBox(
              height: 52,
              child: Row(children: [
                // 좌우 칸 = 같은 폭(72) — 보낸 사람 · 시각이 화면 가운데(F10)
                SizedBox(
                  width: 72,
                  child: TextButton(
                    key: const Key('chat-viewer-close'),
                    onPressed: () => Navigator.of(context).pop(),
                    child: Text('닫기', style: Typo.headingMd500.copyWith(color: Ms.white)),
                  ),
                ),
                Expanded(
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Text(message.sender.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600.copyWith(color: Ms.white)),
                    Text(viewerTime(message.createdAt), style: Typo.caption400.copyWith(color: Ms.gray500)),
                  ]),
                ),
                const SizedBox(width: 72),
              ]),
            ),
            Expanded(child: Center(child: ChatPhoto(photoId: message.photo!.id, fit: BoxFit.contain))),
          ]),
        ),
      );
}
