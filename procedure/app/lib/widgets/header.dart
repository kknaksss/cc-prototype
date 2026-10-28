// 공통 헤더(SPEC-004 §6.8) — 폰 = 가운데 「Céramique」 · 오른쪽 종 + 안 읽은 수 / 태블릿 = 탭 머리 오른쪽 끝 종.
// 시술 현황 탭 머리(§6.2 — 「시술실 현황」 · 「확인 N」 · 시계 · 계정 ▾ 없음 · D7-57) · 연결 끊김 줄(§7.1)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../screens/board_screen.dart' show clockText;
import '../screens/shell.dart' show openNotifications;
import '../sse/board_stream.dart';
import '../theme/tokens.dart';
import 'ui.dart';

// 폰 공통 헤더 — 시안 M:48-57
class AppHeader extends StatelessWidget {
  const AppHeader({super.key});

  @override
  Widget build(BuildContext context) => Container(
        height: 56,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Row(children: [
          const SizedBox(width: 44),
          Expanded(
            child: Text('Céramique',
                textAlign: TextAlign.center,
                style: Typo.titleSm600.copyWith(fontWeight: FontWeight.w700, color: Ms.primary, letterSpacing: -0.3)),
          ),
          const Bell(),
        ]),
      );
}

// 종 + 안 읽은 수(99+ · 0 이면 배지 없음) → 알림 목록(§6.13)
class Bell extends StatelessWidget {
  const Bell({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return ValueListenableBuilder<int>(
      valueListenable: app.unread,
      builder: (context, n, _) => Semantics(
        button: true,
        label: n > 0 ? '알림 $n개 안 읽음' : '알림',
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => openNotifications(context),
          child: SizedBox(
            width: 44,
            height: 44,
            child: Stack(clipBehavior: Clip.none, alignment: Alignment.center, children: [
              const Icon(Icons.notifications_none_rounded, size: 24, color: Ms.gray700),
              if (n > 0)
                Positioned(
                  top: 4,
                  right: 2,
                  child: Container(
                    constraints: const BoxConstraints(minWidth: 18),
                    height: 18,
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(color: Ms.red, borderRadius: BorderRadius.circular(9)),
                    child: Text(n > 99 ? '99+' : '$n',
                        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Ms.white, height: 1)),
                  ),
                ),
            ]),
          ),
        ),
      ),
    );
  }
}

// 탭 머리 — 제목 · 오른쪽 칸들 · (태블릿) 맨 끝 종(§6.8 「레일 위 글자 대신 본문 머리 오른쪽 끝」)
class TabHead extends StatelessWidget {
  final bool tablet;
  final String title;
  final List<Widget> trailing;
  final Widget? leading;
  const TabHead({super.key, required this.tablet, required this.title, this.trailing = const [], this.leading});

  @override
  Widget build(BuildContext context) => Container(
        height: tablet ? 64 : 48,
        padding: EdgeInsets.only(left: tablet ? 24 : 16, right: tablet ? 16 : 16),
        decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Row(children: [
          ?leading,
          Expanded(child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.titleSm600)),
          ...trailing,
          if (tablet) ...[const SizedBox(width: 8), const Bell()],
        ]),
      );
}

// 시술 현황 탭 머리 — 「시술실 현황」 / 「확인 N」(태블릿 「확인 필요 N」) · 시계
class ListHeader extends StatelessWidget {
  final bool tablet;
  final int need;
  const ListHeader({super.key, required this.tablet, required this.need});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final clock = Ticker(builder: (_) => Text(clockText(app), style: Typo.headingSm400.copyWith(color: Ms.black, fontFeatures: tabular)));
    return TabHead(tablet: tablet, title: '시술실 현황', trailing: [
      if (need > 0) ...[
        if (tablet)
          Text('확인 필요 $need', style: Typo.body600.copyWith(color: Ms.red))
        else
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: Ms.red, borderRadius: BorderRadius.circular(999)),
            child: Text('확인 $need', style: Typo.caption600.copyWith(color: Ms.white)),
          ),
        const SizedBox(width: 12),
      ],
      clock,
    ]);
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
