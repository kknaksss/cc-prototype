// 방 정보(SPEC-007 §10.8 ~ §10.10 · §10.16 · §10.17 · DS:S10a ~ S10e · S13c) — 폰 = 채팅 탭 스택 「‹ 대화 · 방 정보」 · 아이패드 = 오른쪽 시트 420.
// 그룹: 그룹 이름(바꾸기 없음) · 알림 Toggle · 「사진 · 동영상」 줄 · 참여자(「나」 맨 위 · 강퇴 없음) · [+ 초대] · [나가기].
// 1:1: 알림 · 「사진 · 동영상」 줄 · 참여자 2명 · [+ 초대](= 새 그룹 · 비활성 상대면 없음 — r5 D9-68) · [목록에서 숨기기](확인 없음).
// 값은 Room 그대로 — 방 정보 API 없음(모아보기 격자만 #20)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_ui.dart';
import '../chat/chat_view.dart';
import '../theme/tokens.dart';
import '../view/view.dart' show BadgeVariant;
import '../widgets/header.dart';
import '../widgets/ui.dart';
import 'chat_media_screen.dart';
import 'chat_new_screen.dart';
import 'chat_room_screen.dart' show chatRoomRouteName;

// 아이패드 오른쪽 시트 — 안에 작은 Navigator(방 정보 → 사진 · 동영상 · [‹ 방 정보]로 돌아감 · r5 처분 W-3)
class ChatInfoSheet extends StatelessWidget {
  final int roomId;
  const ChatInfoSheet({super.key, required this.roomId});
  @override
  Widget build(BuildContext context) => Navigator(
        onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => ChatInfoScreen(roomId: roomId, sheet: true)),
      );
}

class ChatInfoScreen extends StatelessWidget {
  final int roomId;
  final bool sheet; // 아이패드 오른쪽 시트
  const ChatInfoScreen({super.key, required this.roomId, this.sheet = false});

  // 나가기 · 숨기기 뒤 — 시트는 닫고(시트 = 루트 위 · 안쪽 Navigator 가 아님), 폰 스택은 목록까지(ChatRoomView 가 removed 로 닫음)
  void _close(BuildContext context) {
    if (sheet) Navigator.of(context, rootNavigator: true).pop();
  }

  // 사진 · 동영상 모아보기(§10.16) — 폰 = 채팅 탭 스택 · 아이패드 = 같은 시트 안
  void _media(BuildContext context, Room r) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => ChatMediaScreen(roomId: r.id, sheet: sheet)));

  Future<void> _mute(BuildContext context, Room r, bool on) async {
    final app = AppScope.read(context);
    await app.run(() => app.chat.setMuted(r.id, !on));
  }

  // [+ 초대](§10.9 · §10.17) — 그룹 = 그 방에 초대 → 대화로 돌아감 · 1:1 = 새 그룹(나 + 상대 + 고른 사람) → 새 그룹 대화가 열림(1:1 은 그대로)
  Future<void> _invite(BuildContext context, Room r) async {
    final screen = ChatPeopleScreen(addTo: r);
    final made = sheet
        ? await showCenterPanel<Room>(context, screen)
        : await Navigator.of(context).push<Room>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => screen));
    if (made == null || !context.mounted) return;
    if (sheet) Navigator.of(context, rootNavigator: true).pop();
    if (!r.group) {
      // 새 그룹으로 — 채팅 탭이 연다(폰 = 스택을 목록까지 · 새 방 / 아이패드 = 오른쪽 칸 · ChatListScreen.open)
      AppScope.read(context).chat.openRoom(made.id);
      return;
    }
    // 그룹 초대 → 대화로 돌아감(시스템 줄 「<나>님이 <B>님을 초대했습니다」 · DS:S10d)
    if (!sheet) Navigator.of(context).popUntil((x) => x.settings.name == chatRoomRouteName || x.isFirst);
  }

  Future<void> _leave(BuildContext context, Room r) async {
    final ok = await confirmChat(context,
        title: '${roomTitle(r)}에서 나갈까요?', body: '내 목록에서 이 방이 사라져요. 다시 초대받아도 지금까지의 대화는 볼 수 없어요.', ok: '나가기');
    if (!ok || !context.mounted) return;
    final app = AppScope.read(context);
    if (await app.run(() => app.chat.leave(r.id)) && context.mounted) _close(context);
  }

  Future<void> _hide(BuildContext context, Room r) async {
    final app = AppScope.read(context);
    if (await app.run(() => app.chat.hide(r.id)) && context.mounted) _close(context);
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final body = ListenableBuilder(
      listenable: app.chat,
      builder: (context, _) {
        final r = app.chat.room(roomId);
        return Column(children: [
          DetailHeader(
            back: sheet ? '닫기' : '대화',
            chevron: !sheet,
            title: '방 정보',
            onBack: sheet ? () => Navigator.of(context, rootNavigator: true).pop() : null,
          ),
          Expanded(child: r == null ? const SizedBox.shrink() : _content(context, r)),
        ]);
      },
    );
    if (sheet) return Material(color: Ms.gray100, child: SafeArea(left: false, child: body));
    return Scaffold(backgroundColor: Ms.gray100, body: SafeArea(bottom: false, child: body));
  }

  Widget _content(BuildContext context, Room r) => ListView(padding: const EdgeInsets.all(16), children: [
        if (r.group) ...[
          MsCard(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const MsLabel('그룹 이름'),
              const SizedBox(height: 4),
              Text(roomTitle(r), style: Typo.body500),
            ]),
          ),
          const SizedBox(height: 12),
        ],
        MsCard(
          padding: EdgeInsets.zero,
          child: SwitchRow('알림', !r.muted, (v) => _mute(context, r, v), sub: '이 방만 · 끄면 푸시 · 앱 안 배너 없음', key: const Key('chat-mute')),
        ),
        const SizedBox(height: 12),
        // 「사진 · 동영상」 줄(r5 · §10.8 · OQ-966) — 알림 카드 아래 · 참여자 위 · 개수 없음 · API 안 부름
        MsCard(
          key: const Key('chat-media'),
          onTap: () => _media(context, r),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(children: [
            const Icon(Icons.photo_library_outlined, size: 20, color: Ms.gray700),
            const SizedBox(width: 10),
            Expanded(child: Text('사진 · 동영상', style: Typo.body500)),
            const Icon(Icons.chevron_right_rounded, size: 22, color: Ms.gray500),
          ]),
        ),
        const SizedBox(height: 20),
        Row(children: [
          Expanded(child: Text('참여자 ${r.memberCount}명', style: Typo.body600)),
          if (!peerInactive(r)) // 비활성 상대 1:1 = 초대 없음(§4.7 · OQ-967)
            MsButton('+ 초대', key: const Key('chat-invite'), variant: BtnVariant.outlined, size: BtnSize.sm, onPressed: () => _invite(context, r)),
        ]),
        const SizedBox(height: 8),
        MsCard(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Column(children: [
            for (final m in r.members)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(children: [
                  // 이름 + 배지 = 남는 폭(이름만 줄임표) · 「나」 = 늘 오른쪽 끝(F10)
                  Expanded(
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Flexible(child: Text(m.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body500)),
                      const SizedBox(width: 6),
                      roleBadge(m.role),
                      if (!m.active) ...[const SizedBox(width: 4), Text(inactiveMark, style: Typo.caption500.copyWith(color: Ms.gray600))],
                    ]),
                  ),
                  if (m.me) const MsBadge('나', BadgeVariant.neutral, dot: false),
                ]),
              ),
          ]),
        ),
        const SizedBox(height: 20),
        if (r.group)
          MsButton('나가기', key: const Key('chat-leave'), variant: BtnVariant.outlined, color: BtnColor.red, expand: true, onPressed: () => _leave(context, r))
        else ...[
          MsButton('목록에서 숨기기', key: const Key('chat-hide'), variant: BtnVariant.outlined, color: BtnColor.gray, expand: true, onPressed: () => _hide(context, r)),
          const SizedBox(height: 6),
          Text('새 메시지가 오면 목록에 다시 보여요', textAlign: TextAlign.center, style: Typo.caption400.copyWith(color: Ms.gray600)),
        ],
      ]);
}
