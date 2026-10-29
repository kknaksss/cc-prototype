// 공통 틀(SPEC-004 §6.8) — 폰 = 아래 탭바 5칸 · 태블릿 = 왼쪽 레일 92px. 탭마다 자기 스택(바꿔도 유지 · 같은 탭 다시 = 맨 위로).
// 「채팅」= 설정 앞 5번째 · 안 읽은 방 수 배지 · 앱 안 채팅 배너는 이 셸 안 맨 위 층(SPEC-007 §10.1 · §10.12)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../chat/chat_model.dart' show ChatBanner;
import '../chat/chat_ui.dart' show RedCount;
import '../theme/tokens.dart';
import '../widgets/header.dart';
import '../widgets/ui.dart' show MsBanner;
import 'board_screen.dart';
import 'chat_list_screen.dart';
import 'launchers.dart' show openDisplay;
import 'notifications_screen.dart';
import 'reservations_screen.dart';
import 'settings_screen.dart';
import 'visits_screen.dart';

const tabName = {
  AppTab.reservations: '예약 현황',
  AppTab.visits: '내원 현황',
  AppTab.board: '시술 현황',
  AppTab.chat: '채팅',
  AppTab.settings: '설정',
};

const _tabIcon = {
  AppTab.reservations: Icons.calendar_month_rounded,
  AppTab.visits: Icons.groups_rounded,
  AppTab.board: Icons.meeting_room_rounded,
  AppTab.chat: Icons.chat_bubble_rounded, // 말풍선(OQ-928)
  AppTab.settings: Icons.settings_rounded,
};

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  final _navs = {for (final t in AppTab.values) t: GlobalKey<NavigatorState>()};
  late final AppState _app;
  bool _showing = false; // 띄우기 화면(문진 · 스캔)이 열려 있음 — 새 요청은 끝날 때까지 기다린다(§5-3 · OQ-621)

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.displays.addListener(_next);
    WidgetsBinding.instance.addPostFrameCallback((_) => _next());
  }

  @override
  void dispose() {
    _app.displays.removeListener(_next);
    super.dispose();
  }

  // 띄우기 요청 하나씩 — kind 에 맞는 화면(문진 = §6.15 · 스캔 = §6.16)
  Future<void> _next() async {
    if (_showing || !mounted) return;
    final r = _app.takeDisplay();
    if (r == null) return;
    _showing = true;
    try {
      await openDisplay(context, r);
    } finally {
      _showing = false;
      if (mounted) WidgetsBinding.instance.addPostFrameCallback((_) => _next());
    }
  }

  Widget _root(AppTab t) => switch (t) {
        AppTab.reservations => const ReservationsScreen(),
        AppTab.visits => const VisitsScreen(),
        AppTab.board => const BoardScreen(),
        AppTab.chat => const ChatScreen(),
        AppTab.settings => const SettingsScreen(),
      };

  void _pick(AppState app, AppTab t) {
    if (app.tab.value == t) {
      _navs[t]!.currentState?.popUntil((r) => r.isFirst); // 같은 탭 다시 = 맨 위로
    } else {
      app.tab.value = t;
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final tablet = isTablet(context);
    return ValueListenableBuilder<AppTab>(
      valueListenable: app.tab,
      builder: (context, cur, _) {
        final stack = IndexedStack(
          index: cur.index,
          children: [
            for (final t in AppTab.values)
              HeroControllerScope.none(
                child: Navigator(
                  key: _navs[t],
                  observers: [if (t == AppTab.chat) app.chat.chatRoutes],
                  onGenerateRoute: (_) => MaterialPageRoute(builder: (_) => _root(t)),
                ),
              ),
          ],
        );
        // 뒤로 가기(가장자리 밀기)는 지금 탭 스택부터
        final body = NavigatorPopHandler(
          onPopWithResult: (_) => _navs[cur]!.currentState?.maybePop(),
          child: stack,
        );
        if (tablet) {
          return Scaffold(
            backgroundColor: Ms.gray100,
            body: Stack(children: [
              Row(children: [
                _Rail(cur: cur, onPick: (t) => _pick(app, t)),
                Expanded(child: body),
              ]),
              const ChatBannerLayer(),
            ]),
          );
        }
        final mq = MediaQuery.of(context);
        return Scaffold(
          backgroundColor: Ms.gray100,
          body: Stack(children: [
            Column(children: [
              // 탭 안 화면은 탭바 위까지 — 아래 안전 영역은 탭바가 먹는다
              Expanded(child: MediaQuery(data: mq.removePadding(removeBottom: true), child: body)),
              _TabBar(cur: cur, onPick: (t) => _pick(app, t), bottom: mq.padding.bottom),
            ]),
            const ChatBannerLayer(),
          ]),
        );
      },
    );
  }
}

// 폰 아래 탭바(시안 M:189-193) — 아이콘 + 글자 · 지금 탭 primary
class _TabBar extends StatelessWidget {
  final AppTab cur;
  final ValueChanged<AppTab> onPick;
  final double bottom;
  const _TabBar({required this.cur, required this.onPick, required this.bottom});

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.only(top: 8, bottom: bottom > 0 ? bottom : 10),
        decoration: const BoxDecoration(color: Ms.white, border: Border(top: BorderSide(color: Ms.gray200))),
        child: Row(children: [
          for (final t in AppTab.values)
            Expanded(
              child: Semantics(
                button: true,
                selected: t == cur,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onPick(t),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    _TabIcon(t, size: 22, color: t == cur ? Ms.primary : Ms.gray500),
                    const SizedBox(height: 4),
                    Text(tabName[t]!,
                        style: (t == cur ? Typo.caption600 : Typo.caption500).copyWith(color: t == cur ? Ms.primary : Ms.gray600)),
                  ]),
                ),
              ),
            ),
        ]),
      );
}

// 태블릿 왼쪽 레일 92px(시안 T:24-33) — 위 「Céramique」 · 메뉴 4개
class _Rail extends StatelessWidget {
  final AppTab cur;
  final ValueChanged<AppTab> onPick;
  const _Rail({required this.cur, required this.onPick});

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    return Container(
      width: 92,
      padding: EdgeInsets.only(top: top + 20, bottom: 24),
      decoration: const BoxDecoration(color: Ms.white, border: Border(right: BorderSide(color: Ms.gray200))),
      child: Column(children: [
        // 레일 폭에 맞춰 글자 배율 없이(배율이 걸리면 92px 를 넘는다)
        MediaQuery.withNoTextScaling(
          child: Text('Céramique',
              style: const TextStyle(fontFamily: 'Pretendard', fontSize: 15, fontWeight: FontWeight.w700, color: Ms.primary, letterSpacing: -0.3, height: 1)),
        ),
        const SizedBox(height: 20),
        for (final t in AppTab.values)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Semantics(
              button: true,
              selected: t == cur,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => onPick(t),
                child: Container(
                  width: 76,
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(color: t == cur ? Ms.primary100 : null, borderRadius: BorderRadius.circular(12)),
                  child: Column(children: [
                    _TabIcon(t, size: 26, color: t == cur ? Ms.primary : Ms.gray500),
                    const SizedBox(height: 6),
                    MediaQuery.withNoTextScaling(
                      child: Text(tabName[t]!,
                          style: TextStyle(
                              fontFamily: 'Pretendard',
                              fontSize: 12,
                              fontWeight: t == cur ? FontWeight.w600 : FontWeight.w500,
                              color: t == cur ? Ms.primary : Ms.gray700)),
                    ),
                  ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

// 탭 아이콘 — 「채팅」은 안 읽은 방 수 빨간 배지(0 이면 없음 · 99+ · 알림 끈 방도 셈 — SPEC-007 §10.1)
class _TabIcon extends StatelessWidget {
  final AppTab tab;
  final double size;
  final Color color;
  const _TabIcon(this.tab, {required this.size, required this.color});

  @override
  Widget build(BuildContext context) {
    final icon = Icon(_tabIcon[tab], size: size, color: color);
    if (tab != AppTab.chat) return icon;
    return ValueListenableBuilder<int>(
      valueListenable: AppScope.of(context).chat.unreadRooms,
      builder: (context, n, _) => Semantics(
        label: n > 0 ? '안 읽은 대화 $n개' : null,
        child: Stack(clipBehavior: Clip.none, children: [
          icon,
          if (n > 0) Positioned(top: -6, right: -12, child: MediaQuery.withNoTextScaling(child: RedCount(n, key: const Key('chat-tab-badge')))),
        ]),
      ),
    );
  }
}

// 앱 안 채팅 배너(SPEC-007 §10.12 · DS:S11 · S13d) — 셸 안 맨 위 층(탭 본문 · 탭바 · 레일 위). MaterialApp.builder 의 토스트 층에는
// 두지 않는다 — 문진 QR · 여권 스캔(루트 전체 화면)이 셸을 덮어 그 아래에 깔린다(D9-44). 폰 = 위 · 아이패드 = 위 가운데 · 4초 · 소리 없음
class ChatBannerLayer extends StatelessWidget {
  const ChatBannerLayer({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final tablet = isTabletWidth(context);
    final top = MediaQuery.paddingOf(context).top + 8;
    return ValueListenableBuilder<ChatBanner?>(
      valueListenable: app.chat.banner,
      builder: (context, b, _) {
        if (b == null) return const SizedBox.shrink();
        final banner = MsBanner(b.line, key: const Key('chat-banner'), action: '보기', onAction: () {
          app.tab.value = AppTab.chat;
          app.chat.openRoom(b.roomId);
        });
        return Positioned(
          top: top,
          left: tablet ? 0 : 12,
          right: tablet ? 0 : 12,
          child: tablet ? Center(child: SizedBox(width: 520, child: banner)) : banner,
        );
      },
    );
  }
}

// 탭 루트 화면 꼴 — 공통 헤더 한 줄 [Céramique][메뉴명][알림] + 연결 줄 + 본문(폰 · 태블릿 같음)
class TabScaffold extends StatelessWidget {
  final AppTab tab;
  final Widget body;
  const TabScaffold({super.key, required this.tab, required this.body});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      backgroundColor: Ms.gray100,
      body: SafeArea(
        bottom: false,
        child: Column(children: [
          AppHeader(title: tabName[tab]!),
          ConnectionLine(stream: app.stream),
          Expanded(child: body),
        ]),
      ),
    );
  }
}

// 종 → 알림 목록(§6.13) — 폰 = 전체 화면 · 태블릿 = 오른쪽 시트
Future<void> openNotifications(BuildContext context) {
  final nav = Navigator.of(context, rootNavigator: true);
  if (!isTablet(context)) {
    return nav.push(MaterialPageRoute(fullscreenDialog: true, builder: (_) => const NotificationsScreen()));
  }
  return showGeneralDialog(
    context: context,
    useRootNavigator: true,
    barrierDismissible: true,
    barrierLabel: '닫기',
    barrierColor: Ms.dim,
    transitionDuration: const Duration(milliseconds: 220),
    pageBuilder: (_, _, _) => const Align(
      alignment: Alignment.centerRight,
      child: SizedBox(width: 420, child: NotificationsScreen(sheet: true)),
    ),
    transitionBuilder: (_, a, _, child) => SlideTransition(
      position: Tween(begin: const Offset(1, 0), end: Offset.zero).animate(CurvedAnimation(parent: a, curve: Curves.easeOutCubic)),
      child: child,
    ),
  );
}
