// 채팅 사진(SPEC-007 §10.6 · DS:S7a · S8) — [사진] 시트(카메라로 찍기 · 앨범에서 고르기 · 1장씩) · 크게 보기(검정 전체 화면 ·
// [닫기] · 보낸 사람 · 시각 · 저장 · 공유 · 확대 · 넘기기 없음 — D9-24 · D9-36). 크게 보기에서는 삭제하지 않는다(§10.7)
import 'package:flutter/material.dart';

import '../chat/chat_model.dart';
import '../chat/chat_view.dart';
import '../chat/photo_pick.dart';
import '../theme/tokens.dart';
import '../widgets/header.dart' show isTabletWidth;
import '../widgets/ui.dart';
import 'chat_room_screen.dart' show ChatPhoto;

// [사진] → 시트(폰 = 아래 · 아이패드 = 가운데)
Future<PhotoSource?> pickPhotoSource(BuildContext context) {
  Widget body(BuildContext ctx) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('사진 보내기', style: Typo.titleSm600),
            const SizedBox(width: 8),
            Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('1장씩', style: Typo.caption500.copyWith(color: Ms.gray600))),
          ]),
          const SizedBox(height: 14),
          MsButton('카메라로 찍기', key: const Key('chat-camera'), icon: Icons.photo_camera_outlined, variant: BtnVariant.outlined, size: BtnSize.lg, expand: true,
              onPressed: () => Navigator.of(ctx).pop(PhotoSource.camera)),
          const SizedBox(height: 8),
          MsButton('앨범에서 고르기', key: const Key('chat-album'), icon: Icons.photo_library_outlined, variant: BtnVariant.outlined, size: BtnSize.lg, expand: true,
              onPressed: () => Navigator.of(ctx).pop(PhotoSource.album)),
          const SizedBox(height: 8),
          MsButton('취소', variant: BtnVariant.outlined, color: BtnColor.gray, size: BtnSize.lg, expand: true, onPressed: () => Navigator.of(ctx).pop()),
        ]),
      );
  if (isTabletWidth(context)) {
    return showDialog<PhotoSource>(
      context: context,
      barrierColor: Ms.dim,
      builder: (ctx) => Dialog(
        backgroundColor: Ms.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 400), child: Padding(padding: const EdgeInsets.only(top: 12), child: body(ctx))),
      ),
    );
  }
  return showModalBottomSheet<PhotoSource>(
    context: context,
    backgroundColor: Ms.white,
    barrierColor: Ms.dim,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (ctx) => SafeArea(top: false, child: Column(mainAxisSize: MainAxisSize.min, children: [const SheetHandle(), body(ctx)])),
  );
}

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
                TextButton(
                  key: const Key('chat-viewer-close'),
                  onPressed: () => Navigator.of(context).pop(),
                  child: Text('닫기', style: Typo.headingMd500.copyWith(color: Ms.white)),
                ),
                Expanded(
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Text(message.sender.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600.copyWith(color: Ms.white)),
                    Text(viewerTime(message.createdAt), style: Typo.caption400.copyWith(color: Ms.gray500)),
                  ]),
                ),
                const SizedBox(width: 64),
              ]),
            ),
            Expanded(child: Center(child: ChatPhoto(photoId: message.photo!.id, fit: BoxFit.contain))),
          ]),
        ),
      );
}
