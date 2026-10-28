// 내원 현황(SPEC-004 §6.12 · D7-58) — 웹 「원내 현황」 탭과 같은 데이터 · 필터 · 카드. 데이터 = 오늘 GET /api/reservations/board 의 clinic.
// 필터 = 전체 · 접수 · 상담 · 시술 · 귀가 대기(주 상태) · 구역별 묶음(0 명 구역은 안 그림) · 「귀가 대기」는 수납 필요 먼저(M:263).
// 카드 누르면 → 예약 상세 · 태블릿 = 카드 격자
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../model/reservation.dart';
import '../theme/tokens.dart';
import '../view/resv_view.dart';
import '../widgets/resv_ui.dart';
import 'board_screen.dart' show isTablet;
import 'reservation_detail_screen.dart';
import 'reservations_screen.dart' show TabPolling;
import 'shell.dart';

const clinicFilters = [
  ('all', '전체', Ms.gray300),
  ('reception', '접수', Ms.yellow),
  ('consultation', '상담', Ms.cons),
  ('procedure', '시술', Ms.primary),
  ('home', '귀가 대기', Ms.gray600),
];

// 필터 · 구역 묶음(웹 ClinicTab) — 귀가 대기 칸은 수납 필요 먼저
List<(String title, List<ClinicItem> items)> clinicGroups(ResvBoard b, String filter) {
  final c = b.clinic;
  if (c == null) return const [];
  var items = c.items.where((i) => filter == 'all' || i.state.main.name == filter).toList();
  if (filter == 'home') {
    items = [...items.where((i) => i.paymentRequiredCount > 0), ...items.where((i) => i.paymentRequiredCount <= 0)];
  }
  final groups = [
    for (final z in b.zones) (z.title, items.where((i) => i.zoneId == z.zoneId).toList()),
  ];
  final orphan = items.where((i) => !b.zones.any((z) => z.zoneId == i.zoneId)).toList();
  if (orphan.isNotEmpty) groups.add(('구역 없음', orphan));
  return groups.where((g) => g.$2.isNotEmpty).toList();
}

class VisitsScreen extends StatefulWidget {
  const VisitsScreen({super.key});
  @override
  State<VisitsScreen> createState() => _VisitsScreenState();
}

class _VisitsScreenState extends State<VisitsScreen> with TabPolling {
  late final AppState _app;
  ResvBoard? _board;
  String? _error;
  String _filter = 'all';

  @override
  AppTab get pollTab => AppTab.visits;
  @override
  Duration get pollEvery => const Duration(seconds: 10);

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.tab.addListener(_onTab);
    if (_app.tab.value == AppTab.visits) poll();
    startPolling();
  }

  @override
  void dispose() {
    stopPolling();
    _app.tab.removeListener(_onTab);
    super.dispose();
  }

  void _onTab() {
    if (_app.tab.value == AppTab.visits) poll();
  }

  @override
  Future<void> poll() async {
    try {
      final b = await _app.api.reservationBoard(todayKst());
      if (mounted) {
        setState(() {
          _board = b;
          _error = null;
        });
      }
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _open(ClinicItem i) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReservationDetailScreen(reservationId: i.reservationId, back: '내원 현황')));

  @override
  Widget build(BuildContext context) {
    final tablet = isTablet(context);
    final b = _board;
    final c = b?.clinic;
    Widget body;
    if (b == null) {
      body = Center(
          child: _error != null ? Text(_error!, style: Typo.body500.copyWith(color: Ms.gray600)) : const CircularProgressIndicator(strokeWidth: 2));
    } else if (c == null) {
      body = Center(child: Text('오늘만 볼 수 있어요', style: Typo.body500.copyWith(color: Ms.gray600)));
    } else {
      final groups = clinicGroups(b, _filter);
      final pad = tablet ? 24.0 : 16.0;
      body = RefreshIndicator(
        onRefresh: poll,
        child: LayoutBuilder(builder: (context, box) {
          final cols = tablet ? ((box.maxWidth - pad * 2 + 12) / (340 + 12)).floor().clamp(1, 4) : 1;
          final w = (box.maxWidth - pad * 2 - 12 * (cols - 1)) / cols;
          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: EdgeInsets.fromLTRB(pad, 0, pad, 24), // 칩 줄 위 · 아래 여백은 ChipRow 가(모든 탭 같게 · batch 4 #2)
            children: [
              // 필터(점 · 이름 · 수) — 공통 StatusChip 한 줄(넘치면 가로 스크롤 · 2026-10-28)
              ChipRow([
                for (final f in clinicFilters)
                  StatusChip(f.$2,
                      count: c.counts[f.$1] ?? 0, dot: f.$3, selected: _filter == f.$1, onTap: () => setState(() => _filter = f.$1)),
              ]),
              for (final (gi, g) in groups.indexed) ...[
                Padding(
                  padding: EdgeInsets.only(top: gi == 0 ? 0 : 4, bottom: 8), // 첫 묶음 머리는 칩 줄 바로 아래
                  child: Text('${g.$1} ${g.$2.length}명', style: Typo.caption600.copyWith(color: Ms.gray700)),
                ),
                Wrap(spacing: 12, runSpacing: 8, children: [
                  for (final it in g.$2) SizedBox(width: w, child: ClinicCard(item: it, onTap: () => _open(it))),
                ]),
                const SizedBox(height: 8),
              ],
              if (groups.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 24),
                  child: Center(
                    child: Text(c.items.isEmpty ? '원내 고객 없음' : '조건에 맞는 고객 없음', style: Typo.body400.copyWith(color: Ms.gray500)),
                  ),
                ),
            ],
          );
        }),
      );
    }
    return TabScaffold(tab: AppTab.visits, body: body);
  }
}
