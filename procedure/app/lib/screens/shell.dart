// 공통 틀(SPEC-004 §6.8) — 폰 = 아래 탭바 4칸 · 태블릿 = 왼쪽 레일 92px. 탭마다 자기 스택(바꿔도 유지 · 같은 탭 다시 = 맨 위로)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../theme/tokens.dart';
import '../widgets/header.dart';
import 'board_screen.dart';
import 'launchers.dart' show openDisplay;
import 'notifications_screen.dart';
import 'reservations_screen.dart';
import 'settings_screen.dart';
import 'visits_screen.dart';

const tabName = {
  AppTab.reservations: '예약 현황',
  AppTab.visits: '내원 현황',
  AppTab.board: '시술 현황',
  AppTab.settings: '설정',
};

const _tabIcon = {
  AppTab.reservations: Icons.calendar_month_rounded,
  AppTab.visits: Icons.groups_rounded,
  AppTab.board: Icons.meeting_room_rounded,
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
    _app.askDeviceName.addListener(_askName);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _next();
      _askName();
    });
  }

  @override
  void dispose() {
    _app.displays.removeListener(_next);
    _app.askDeviceName.removeListener(_askName);
    super.dispose();
  }

  // 첫 로그인 「이 기기 이름」(E2E batch 1 #2) — 웹 [스캔할 기기] · [태블릿에 띄우기] 목록에 보일 이름. 띄우기 화면이 열려 있으면 끝난 뒤
  bool _asking = false;
  Future<void> _askName() async {
    if (_asking || _showing || !mounted || !_app.askDeviceName.value) return;
    _asking = true;
    try {
      final name = await askDeviceNameDialog(context);
      await _app.answerDeviceName(name);
    } finally {
      _asking = false;
    }
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
      if (mounted) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _next();
          _askName();
        });
      }
    }
  }

  Widget _root(AppTab t) => switch (t) {
        AppTab.reservations => const ReservationsScreen(),
        AppTab.visits => const VisitsScreen(),
        AppTab.board => const BoardScreen(),
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
            body: Row(children: [
              _Rail(cur: cur, onPick: (t) => _pick(app, t)),
              Expanded(child: body),
            ]),
          );
        }
        final mq = MediaQuery.of(context);
        return Scaffold(
          backgroundColor: Ms.gray100,
          body: Column(children: [
            // 탭 안 화면은 탭바 위까지 — 아래 안전 영역은 탭바가 먹는다
            Expanded(child: MediaQuery(data: mq.removePadding(removeBottom: true), child: body)),
            _TabBar(cur: cur, onPick: (t) => _pick(app, t), bottom: mq.padding.bottom),
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
                    Icon(_tabIcon[t], size: 22, color: t == cur ? Ms.primary : Ms.gray500),
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
                    Icon(_tabIcon[t], size: 26, color: t == cur ? Ms.primary : Ms.gray500),
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

// 탭 루트 화면 꼴 — 폰 = 공통 헤더 + 연결 줄 + 머리 + 본문 / 태블릿 = 연결 줄 + 머리(끝에 종) + 본문
class TabScaffold extends StatelessWidget {
  final Widget head;
  final Widget body;
  const TabScaffold({super.key, required this.head, required this.body});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final tablet = isTablet(context);
    return Scaffold(
      backgroundColor: Ms.gray100,
      body: SafeArea(
        bottom: false,
        child: Column(children: [
          if (!tablet) const AppHeader(),
          ConnectionLine(stream: app.stream),
          head,
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

// 「이 기기 이름」 입력 — [저장] = 적은 이름 · [나중에] = null(기본 이름 그대로 · 설정에서 바꿀 수 있음)
Future<String?> askDeviceNameDialog(BuildContext context) => showDialog<String>(
      context: context,
      useRootNavigator: true,
      barrierDismissible: false,
      barrierColor: Ms.dim,
      builder: (_) => const _DeviceNameDialog(),
    );

class _DeviceNameDialog extends StatefulWidget {
  const _DeviceNameDialog();
  @override
  State<_DeviceNameDialog> createState() => _DeviceNameDialogState();
}

class _DeviceNameDialogState extends State<_DeviceNameDialog> {
  final _ctl = TextEditingController();

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        backgroundColor: Ms.white,
        title: Text('이 기기 이름', style: Typo.headingMd600),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('웹에서 여권 스캔 · 문진을 보낼 기기를 고를 때 이 이름이 보여요', style: Typo.body400.copyWith(color: Ms.gray600)),
          const SizedBox(height: 8),
          TextField(
            key: const Key('device-name'),
            controller: _ctl,
            autofocus: true,
            maxLength: 40,
            decoration: const InputDecoration(hintText: '예: 데스크 태블릿 · 코디 폰'),
            onSubmitted: (v) => Navigator.of(context).pop(v),
          ),
          Text('설정 › 이 기기에서 바꿀 수 있어요', style: Typo.caption500.copyWith(color: Ms.gray500)),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('나중에')),
          TextButton(onPressed: () => Navigator.of(context).pop(_ctl.text), child: const Text('저장')),
        ],
      );
}
