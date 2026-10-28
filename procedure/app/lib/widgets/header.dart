// 공통 헤더(SPEC-004 §6.8) — 한 줄 [메뉴명][Céramique][알림](사용자 2026-10-28 — 두 줄이라 헤더가 너무 컸다) · 폰 · 태블릿 같음.
// 탭 머리의 큰 제목 줄은 없앴고, 거기 있던 것(시술 현황 「확인 N」 · 시계)은 그 탭 본문 첫 줄(TabBar 대신 BoardBar)로.
// 연결 끊김 줄(§7.1)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../screens/board_screen.dart' show clockText;
import '../screens/shell.dart' show openNotifications;
import '../sse/board_stream.dart';
import '../theme/tokens.dart';
import 'ui.dart';

// 공통 헤더 한 줄 — 왼쪽 지금 탭 이름 · 가운데 Céramique(화면 가운데에 고정) · 오른쪽 종 + 안 읽은 수
class AppHeader extends StatelessWidget {
  final String title;
  const AppHeader({super.key, required this.title});

  @override
  Widget build(BuildContext context) {
    final tablet = isTabletWidth(context);
    return Container(
      height: 56,
      padding: EdgeInsets.symmetric(horizontal: tablet ? 16 : 8), // 좌우 같게 — Céramique 가 화면 가운데
      decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
      child: Row(children: [
        Expanded(child: Padding(padding: const EdgeInsets.only(left: 8), child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.headingMd600))),
        Text('Céramique', style: Typo.titleSm600.copyWith(fontWeight: FontWeight.w700, color: Ms.primary, letterSpacing: -0.3)),
        const Expanded(child: Align(alignment: Alignment.centerRight, child: Bell())),
      ]),
    );
  }
}

// 짧은 변 600 이상 = 태블릿(§6.0 — board_screen isTablet 과 같은 기준 · 순환 import 피함)
bool isTabletWidth(BuildContext context) => MediaQuery.sizeOf(context).shortestSide >= 600;

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

// 시술 현황 본문 첫 줄 — 「확인 N」(태블릿 「확인 필요 N」) · 시계(옛 탭 머리 「시술실 현황」 줄에 있던 것 · §6.2 · D7-57)
class BoardBar extends StatelessWidget {
  final bool tablet;
  final int need;
  const BoardBar({super.key, required this.tablet, required this.need});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final clock = Ticker(builder: (_) => Text(clockText(app), style: Typo.headingSm400.copyWith(color: Ms.black, fontFeatures: tabular)));
    return Container(
      height: 40,
      padding: EdgeInsets.symmetric(horizontal: tablet ? 24 : 16),
      decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
      child: Row(children: [
        if (need > 0)
          tablet
              ? Text('확인 필요 $need', style: Typo.body600.copyWith(color: Ms.red))
              : Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(color: Ms.red, borderRadius: BorderRadius.circular(999)),
                  child: Text('확인 $need', style: Typo.caption600.copyWith(color: Ms.white)),
                ),
        const Spacer(),
        clock,
      ]),
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
