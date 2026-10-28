// 공통 헤더(SPEC-004 §6.8) — 한 줄 [Céramique][메뉴명][알림](사용자 2026-10-28 — 두 줄이라 헤더가 너무 컸다 · 자리 바꿈) · 폰 · 태블릿 같음.
// 탭 머리의 큰 제목 줄은 없앴고, 거기 있던 것(시술 현황 「확인 N」 · 시계)은 그 탭 본문 첫 줄(TabBar 대신 BoardBar)로.
// 연결 끊김 줄(§7.1)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../screens/shell.dart' show openNotifications;
import '../sse/board_stream.dart';
import '../theme/tokens.dart';

// 공통 헤더 한 줄 — 왼쪽 Céramique · 가운데 지금 탭 이름(본문 가운데에 고정) · 오른쪽 종 + 안 읽은 수
class AppHeader extends StatelessWidget {
  final String title;
  const AppHeader({super.key, required this.title});

  @override
  Widget build(BuildContext context) {
    final tablet = isTabletWidth(context);
    return Container(
      height: headerHeight,
      padding: EdgeInsets.symmetric(horizontal: tablet ? 16 : 8), // 좌우 같게 — 메뉴명이 본문 가운데
      decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
      child: Row(children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(left: 8),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text('Céramique', style: Typo.titleSm600.copyWith(fontWeight: FontWeight.w700, color: Ms.primary, letterSpacing: -0.3)),
            ),
          ),
        ),
        Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.headingMd600),
        const Expanded(child: Align(alignment: Alignment.centerRight, child: Bell())),
      ]),
    );
  }
}

// 모든 머리(공통 헤더 · 예약 상세 · 알림) 같은 높이 — 56 → 48(사용자 2026-10-28 「글자 아래 여백이 너무 큼」)
const double headerHeight = 48;

// 머리 왼쪽 뒤로 버튼(‹ 목록 · ‹ 닫기) — 공통 헤더 글자 체계(16 · 제목과 같은 크기 · 굵기 500 · gray-700) · 모든 화면 같게
class HeaderBack extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  final bool chevron;
  const HeaderBack(this.label, {super.key, required this.onTap, this.chevron = true});

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: label,
        excludeSemantics: true,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (chevron) const Icon(Icons.chevron_left_rounded, size: 22, color: Ms.gray700),
              Text(label, style: Typo.headingMd500.copyWith(color: Ms.gray700)),
            ]),
          ),
        ),
      );
}

// 상세 화면 머리(예약 상세 · 룸 상세 · 알림) — 흰 바탕 · 공통 헤더 높이 · [‹ 들어온 탭 이름] · 제목(화면 이름)은 왼쪽 버튼 폭과
// 상관없이 정가운데 · 오른쪽은 비우거나 동작 하나(사용자 2026-10-28 — 상태 색 · 상태 제목 · 시각 없음)
class DetailHeader extends StatelessWidget {
  final String back;
  final String title;
  final Widget? trailing;
  final VoidCallback? onBack;
  final bool chevron;
  const DetailHeader({super.key, required this.back, required this.title, this.trailing, this.onBack, this.chevron = true});

  @override
  Widget build(BuildContext context) => Container(
        height: headerHeight,
        decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Stack(children: [
          Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 120), // 양쪽 버튼 자리 — 긴 제목이 버튼 밑으로 안 들어가게
              child: Text(title, key: const Key('detail-title'), maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.headingMd600),
            ),
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.only(left: 4),
              child: HeaderBack(back, chevron: chevron, onTap: onBack ?? () => Navigator.of(context).maybePop()),
            ),
          ),
          if (trailing != null) Align(alignment: Alignment.centerRight, child: Padding(padding: const EdgeInsets.only(right: 8), child: trailing)),
        ]),
      );
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

// 시술 현황 본문 첫 줄 — 「확인 N」(태블릿 「확인 필요 N」)만(시계는 뺌 · 사용자 2026-10-28) · 확인할 것이 없으면 줄 없음
class BoardBar extends StatelessWidget {
  final bool tablet;
  final int need;
  const BoardBar({super.key, required this.tablet, required this.need});

  @override
  Widget build(BuildContext context) {
    if (need <= 0) return const SizedBox.shrink();
    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(tablet ? 24 : 16, 8, tablet ? 24 : 16, 0),
      alignment: Alignment.centerLeft,
      child: tablet
          ? Text('확인 필요 $need', style: Typo.body600.copyWith(color: Ms.red))
          : Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: Ms.red, borderRadius: BorderRadius.circular(999)),
              child: Text('확인 $need', style: Typo.caption600.copyWith(color: Ms.white)),
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
