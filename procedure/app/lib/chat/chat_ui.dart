// 채팅 공용 조각(시안 medikit → 앱 위젯 · SPEC-007 §10.0) — 역할 Badge · 방 목록 행 · 대화상자 · 가운데 창(아이패드)
import 'package:flutter/material.dart';

import '../model/account.dart';
import '../theme/tokens.dart';
import '../view/state.dart' show ChipLook;
import '../view/view.dart' show BadgeVariant;
import '../widgets/ui.dart';
import 'chat_model.dart';
import 'chat_view.dart';

// 역할 Badge — 의사 primary · 간호사 purple · 관리자 neutral · 코디 yellow-100 바탕 · 상담사 cons-100 바탕(DS:S3a)
Widget roleBadge(Role r, {Key? key}) => switch (r) {
      Role.doctor => MsBadge(roleName[r]!, BadgeVariant.primary, key: key, dot: false),
      Role.nurse => MsBadge(roleName[r]!, BadgeVariant.purple, key: key, dot: false),
      Role.admin => MsBadge(roleName[r]!, BadgeVariant.neutral, key: key, dot: false),
      Role.coordinator => MsBadge.chip(ChipLook(Ms.yellow100, Ms.yellow, roleName[r]!), key: key),
      Role.counselor => MsBadge.chip(ChipLook(Ms.cons100, Ms.cons, roleName[r]!), key: key),
    };

const inactiveMark = '(비활성)';

// 방 목록 행(DS:S1) — 이름 · 인원(그룹) / 역할 Badge(1:1) · 종 빗금(알림 끔) · 시각 / 미리보기 · 안 읽음 Badge
class RoomRow extends StatelessWidget {
  final Room room;
  final bool selected;
  final VoidCallback onTap;
  final DateTime? now;
  const RoomRow({super.key, required this.room, required this.onTap, this.selected = false, this.now});

  @override
  Widget build(BuildContext context) {
    final r = room;
    final p = previewOf(r);
    final peer = r.peer;
    return Semantics(
      button: true,
      selected: selected,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          decoration: BoxDecoration(
            color: selected ? Ms.primary100 : Ms.white,
            border: const Border(bottom: BorderSide(color: Ms.gray200)),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Expanded(
                child: Row(children: [
                  Flexible(child: Text(roomTitle(r), maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600)),
                  const SizedBox(width: 6),
                  if (r.group) Text('${r.memberCount}', style: Typo.caption500.copyWith(color: Ms.gray600)),
                  if (!r.group && peer != null) roleBadge(peer.role),
                  if (peerInactive(r)) ...[const SizedBox(width: 4), Text(inactiveMark, style: Typo.caption500.copyWith(color: Ms.gray600))],
                  if (r.muted) ...[
                    const SizedBox(width: 4),
                    Semantics(label: '알림 끔', child: const Icon(Icons.notifications_off_outlined, size: 15, color: Ms.gray500)),
                  ],
                ]),
              ),
              const SizedBox(width: 8),
              Text(listTime(r.lastMessageAt ?? r.createdAt, now: now), style: Typo.caption400.copyWith(color: Ms.gray600)),
            ]),
            const SizedBox(height: 3),
            SizedBox(
              height: 22,
              child: Row(children: [
                if (p.prefix.isNotEmpty) Text(p.prefix, style: Typo.body400.copyWith(color: Ms.gray600)),
                if (p.photo) const Padding(padding: EdgeInsets.only(right: 4), child: Icon(Icons.image_outlined, size: 15, color: Ms.gray600)),
                Expanded(child: Text(p.body, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body400.copyWith(color: Ms.gray600))),
                if (r.unread > 0) ...[
                  const SizedBox(width: 8),
                  MsBadge(countText(r.unread), r.muted ? BadgeVariant.neutral : BadgeVariant.primary, dot: false),
                ],
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

// 빨간 수 배지(탭 · 레일 · 종과 같은 꼴 · 99+)
class RedCount extends StatelessWidget {
  final int n;
  const RedCount(this.n, {super.key});
  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(minWidth: 18),
        height: 18,
        padding: const EdgeInsets.symmetric(horizontal: 4),
        alignment: Alignment.center,
        decoration: BoxDecoration(color: Ms.red, borderRadius: BorderRadius.circular(9)),
        child: Text(countText(n), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Ms.white, height: 1)),
      );
}

// 확인 대화상자(삭제 · 나가기 — DS:S9b · S10e) — Card · 제목 · 설명 · [취소] · [확인](red)
Future<bool> confirmChat(BuildContext context, {required String title, required String body, required String ok}) async {
  final r = await showDialog<bool>(
    context: context,
    barrierColor: Ms.dim,
    builder: (ctx) => Dialog(
      backgroundColor: Ms.white,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 360),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(title, style: Typo.headingMd600),
            const SizedBox(height: 8),
            Text(body, style: Typo.body400.copyWith(color: Ms.gray700)),
            const SizedBox(height: 20),
            Row(children: [
              Expanded(child: MsButton('취소', variant: BtnVariant.outlined, color: BtnColor.gray, expand: true, onPressed: () => Navigator.of(ctx).pop(false))),
              const SizedBox(width: 8),
              Expanded(child: MsButton(ok, color: BtnColor.red, expand: true, onPressed: () => Navigator.of(ctx).pop(true))),
            ]),
          ]),
        ),
      ),
    ),
  );
  return r == true;
}

// 아이패드 — 새 대화 · 참여자 추가를 가운데 창으로(DS:S13a 설명 「폰과 같은 내용 · 가운데」)
Future<T?> showCenterPanel<T>(BuildContext context, Widget child) => showDialog<T>(
      context: context,
      barrierColor: Ms.dim,
      builder: (ctx) => Dialog(
        backgroundColor: Ms.gray100,
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: 520, maxHeight: MediaQuery.sizeOf(ctx).height * 0.8),
          child: child,
        ),
      ),
    );

// 아이패드 — 방 정보 = 오른쪽 시트 420(알림 목록 태블릿 자리와 같은 꼴 · shell.dart openNotifications)
Future<void> showRightSheet(BuildContext context, Widget child) => showGeneralDialog(
      context: context,
      useRootNavigator: true,
      barrierDismissible: true,
      barrierLabel: '닫기',
      barrierColor: Ms.dim,
      transitionDuration: const Duration(milliseconds: 220),
      pageBuilder: (_, _, _) => Align(alignment: Alignment.centerRight, child: SizedBox(width: 420, child: child)),
      transitionBuilder: (_, a, _, c) => SlideTransition(
        position: Tween(begin: const Offset(1, 0), end: Offset.zero).animate(CurvedAnimation(parent: a, curve: Curves.easeOutCubic)),
        child: c,
      ),
    );
