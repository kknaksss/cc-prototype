// 방 정보(SPEC-007 §10.8 ~ §10.10 · DS:S10a ~ S10e · S13c) — 폰 = 채팅 탭 스택 「‹ 대화 · 방 정보」 · 아이패드 = 오른쪽 시트 420.
// 그룹: 그룹 이름(바꾸기 없음) · 알림 Toggle · 참여자(「나」 맨 위 · 강퇴 없음) · [+ 참여자 추가] · [나가기].
// 1:1: 알림 · 참여자 2명 · 안내 한 줄 · [목록에서 숨기기](확인 없음). 값은 Room 그대로 — 방 정보 API 없음
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../chat/chat_model.dart';
import '../chat/chat_ui.dart';
import '../chat/chat_view.dart';
import '../theme/tokens.dart';
import '../view/view.dart' show BadgeVariant;
import '../widgets/header.dart';
import '../widgets/ui.dart';
import 'chat_new_screen.dart';
import 'chat_room_screen.dart' show chatRoomRouteName;

class ChatInfoScreen extends StatelessWidget {
  final int roomId;
  final bool sheet; // 아이패드 오른쪽 시트
  const ChatInfoScreen({super.key, required this.roomId, this.sheet = false});

  // 나가기 · 숨기기 뒤 — 시트는 닫고, 폰 스택은 목록까지(ChatRoomView 가 removed 로 닫음)
  void _close(BuildContext context) {
    if (sheet) Navigator.of(context).pop();
  }

  Future<void> _mute(BuildContext context, Room r, bool on) async {
    final app = AppScope.read(context);
    await app.run(() => app.chat.setMuted(r.id, !on));
  }

  Future<void> _add(BuildContext context, Room r) async {
    final screen = ChatPeopleScreen(addTo: r);
    final added = sheet
        ? await showCenterPanel<Room>(context, screen)
        : await Navigator.of(context).push<Room>(MaterialPageRoute(fullscreenDialog: true, builder: (_) => screen));
    if (added == null || !context.mounted) return;
    // 추가 → 대화로 돌아감(시스템 줄 「… 님을 초대했어요」 · DS:S10d)
    if (sheet) {
      Navigator.of(context).pop();
    } else {
      Navigator.of(context).popUntil((x) => x.settings.name == chatRoomRouteName || x.isFirst);
    }
  }

  Future<void> _leave(BuildContext context, Room r) async {
    final ok = await confirmChat(context,
        title: '${roomTitle(r)}에서 나갈까요?', body: '내 목록에서 이 방이 사라져요. 다시 초대받으면 다시 볼 수 있어요.', ok: '나가기');
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
          DetailHeader(back: sheet ? '닫기' : '대화', chevron: !sheet, title: '방 정보'),
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
        const SizedBox(height: 20),
        Row(children: [
          Text('참여자 ${r.memberCount}명', style: Typo.body600),
          const Spacer(),
          if (r.group)
            MsButton('+ 참여자 추가', key: const Key('chat-add-members'), variant: BtnVariant.outlined, size: BtnSize.sm, onPressed: () => _add(context, r)),
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
          Text('1:1 에는 참여자를 더할 수 없어요. 여럿이 이야기하려면 [새 대화] 에서 그룹을 만들어요.', style: Typo.body400.copyWith(color: Ms.gray600)),
          const SizedBox(height: 16),
          MsButton('목록에서 숨기기', key: const Key('chat-hide'), variant: BtnVariant.outlined, color: BtnColor.gray, expand: true, onPressed: () => _hide(context, r)),
          const SizedBox(height: 6),
          Text('새 메시지가 오면 목록에 다시 보여요', textAlign: TextAlign.center, style: Typo.caption400.copyWith(color: Ms.gray600)),
        ],
      ]);
}
