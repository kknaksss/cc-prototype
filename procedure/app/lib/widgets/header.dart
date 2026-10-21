// 목록 머리(SPEC-004 §6.2) · 계정 ▾ = [로그아웃](§6.1) · 연결 끊김 줄(§7.1)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../push/push.dart' show NotifStatus;
import '../screens/board_screen.dart' show clockText;
import '../screens/login_screen.dart' show CeramiqueLogo;
import '../sse/board_stream.dart';
import '../theme/tokens.dart';
import 'ui.dart';

class ListHeader extends StatelessWidget {
  final bool tablet;
  final int need;
  const ListHeader({super.key, required this.tablet, required this.need});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final clock = Ticker(builder: (_) => Text(clockText(app), style: Typo.headingSm400.copyWith(color: Ms.black, fontFeatures: tabular)));
    if (tablet) {
      return Container(
        height: 64,
        padding: const EdgeInsets.symmetric(horizontal: 24),
        decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Row(children: [
          const CeramiqueLogo(size: 20),
          const SizedBox(width: 16),
          Text('시술실 현황', style: Typo.titleSm600),
          const Spacer(),
          if (need > 0) ...[
            Text('확인 필요 $need', style: Typo.body600.copyWith(color: Ms.red)),
            const SizedBox(width: 16),
          ],
          clock,
          const SizedBox(width: 16),
          const AccountMenu(),
        ]),
      );
    }
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
      child: Row(children: [
        Expanded(
          child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('시술실 현황', style: Typo.titleSm600.copyWith(height: 1.3)),
            const AccountMenu(compact: true),
          ]),
        ),
        if (need > 0) ...[
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: Ms.red, borderRadius: BorderRadius.circular(999)),
            child: Text('확인 $need', style: Typo.caption600.copyWith(color: Ms.white)),
          ),
          const SizedBox(width: 10),
        ],
        clock,
      ]),
    );
  }
}

// 계정 이름 ▾ — 누르면 [로그아웃](시안 「데모 계정 전환」 대신 · §6.7 #7)
class AccountMenu extends StatelessWidget {
  final bool compact;
  const AccountMenu({super.key, this.compact = false});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final name = app.session?.name ?? '';
    return PopupMenuButton<String>(
      tooltip: '',
      padding: EdgeInsets.zero,
      position: PopupMenuPosition.under,
      color: Ms.white,
      onSelected: (v) {
        if (v == 'logout') app.logout();
      },
      itemBuilder: (_) => [
        PopupMenuItem(enabled: false, child: Text(app.server.base, style: Typo.caption400.copyWith(color: Ms.gray600))),
        if (app.notif == NotifStatus.denied)
          PopupMenuItem(enabled: false, child: Text('알림 꺼짐 · 설정에서 켜기', style: Typo.caption600.copyWith(color: Ms.red))),
        PopupMenuItem(value: 'logout', child: Text('로그아웃', style: Typo.body500)),
      ],
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: compact ? 0 : 8),
        child: Text.rich(
          TextSpan(children: [
            TextSpan(text: name, style: (compact ? Typo.caption600 : Typo.body600).copyWith(color: Ms.primary)),
            TextSpan(text: ' ▾', style: (compact ? Typo.caption400 : Typo.body400).copyWith(color: Ms.gray600)),
            // 알림 거부 — 계정 ▾ 옆 한 줄(§5-1.1 ①)
            if (app.notif == NotifStatus.denied)
              TextSpan(text: '  알림 꺼짐', style: Typo.caption600.copyWith(color: Ms.red)),
          ]),
        ),
      ),
    );
  }
}

// 연결 끊긴 동안 「연결 끊김 · 다시 연결 중」(값은 마지막 스냅샷 그대로)
class ConnectionLine extends StatelessWidget {
  final BoardStream stream;
  const ConnectionLine({super.key, required this.stream});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: stream,
        builder: (context, _) {
          if (stream.connected) return const SizedBox.shrink();
          return Container(
            width: double.infinity,
            color: Ms.yellow100,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            child: Text(stream.board == null ? '서버에 연결 중…' : '연결 끊김 · 다시 연결 중',
                style: Typo.caption600.copyWith(color: Ms.yellow)),
          );
        },
      );
}
