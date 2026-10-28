// 예약 현황(SPEC-004 §6.10 · D7-21 · D7-28 ~ D7-30) — 첫 화면(D7-60). 데이터 = GET /api/reservations/board?date= · 10초마다(앱이 앞 · 이 탭일 때만)
// 폰 = 30분 시간대 목록 + 칩 줄(전체 + KOS 예약 그룹) · 태블릿 = 시간 × 칸 표(가로 스크롤 · 시각 열 · 열 머리 고정).
// 첫 렌더 = 지금 시각으로 스크롤. [+] · 드래그 · 등록 · 공지 · 예약 요청 없음(D7-30 · D7-31)
import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../model/reservation.dart';
import '../scan/scan_channel.dart';
import '../theme/tokens.dart';
import '../view/resv_view.dart';
import '../widgets/header.dart';
import '../widgets/resv_ui.dart';
import '../widgets/ui.dart';
import 'board_screen.dart' show isTablet;
import 'reservation_detail_screen.dart';
import 'shell.dart';

// 이 탭이 앞에 있을 때 — 폴링 · 알림 누름 열기
mixin TabPolling<T extends StatefulWidget> on State<T> {
  Timer? _poll;
  AppTab get pollTab;
  Duration get pollEvery;
  Future<void> poll();

  void startPolling() {
    _poll = Timer.periodic(pollEvery, (_) {
      final app = AppScope.read(context);
      final fg = WidgetsBinding.instance.lifecycleState == null || WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
      if (mounted && fg && app.tab.value == pollTab && app.session != null) poll();
    });
  }

  void stopPolling() => _poll?.cancel();
}

class ReservationsScreen extends StatefulWidget {
  const ReservationsScreen({super.key});
  @override
  State<ReservationsScreen> createState() => _ReservationsScreenState();
}

class _ReservationsScreenState extends State<ReservationsScreen> with TabPolling {
  late final AppState _app;
  String _date = todayKst();
  ResvBoard? _board;
  String? _error;
  bool _filterOn = false; // 칩 「전체」 = false
  int? _group;
  bool _scrolled = false;
  final _vScroll = ScrollController();
  final _hHead = ScrollController();
  final _hBody = ScrollController();

  @override
  AppTab get pollTab => AppTab.reservations;
  @override
  Duration get pollEvery => const Duration(seconds: 10);

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.openReservation.addListener(_maybeOpen);
    _app.tab.addListener(_onTab);
    _hBody.addListener(() {
      if (_hHead.hasClients) _hHead.jumpTo(_hBody.offset);
    });
    poll();
    startPolling();
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeOpen());
  }

  @override
  void dispose() {
    stopPolling();
    _app.openReservation.removeListener(_maybeOpen);
    _app.tab.removeListener(_onTab);
    _vScroll.dispose();
    _hHead.dispose();
    _hBody.dispose();
    super.dispose();
  }

  void _onTab() {
    if (_app.tab.value == AppTab.reservations) poll();
  }

  // 상담사 호출 푸시 · 알림 목록 → 그 예약 상세(§5-2 · §6.13)
  void _maybeOpen() {
    final id = _app.openReservation.value;
    if (id == null || !mounted) return;
    _app.openReservation.value = null;
    final nav = Navigator.of(context);
    nav.popUntil((r) => r.isFirst);
    nav.push(MaterialPageRoute(builder: (_) => ReservationDetailScreen(reservationId: id, focusConsultation: true)));
  }

  @override
  Future<void> poll() async {
    final date = _date;
    try {
      final b = await _app.api.reservationBoard(date);
      if (!mounted || date != _date) return;
      setState(() {
        _board = b;
        _error = null;
      });
      if (!_scrolled) WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToNow());
    } on ApiError catch (e) {
      if (e.status == 401) return _app.logout(message: '로그인이 풀렸어요 — 다시 로그인하세요');
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _go(String date) {
    setState(() {
      _date = date;
      _board = null;
      _scrolled = false;
    });
    poll();
  }

  // 첫 렌더 = 지금 시간대(오늘) · 다른 날 = 첫 운영 줄 — 위 여유 64
  void _scrollToNow() {
    final b = _board;
    if (b == null || !_vScroll.hasClients) return;
    _scrolled = true;
    final start = hmToMin(b.axis?.start ?? '06:00');
    var target = nowSlot(b);
    if (target == null) {
      final opens = b.columns.expand((c) => c.open).map((s) => hmToMin(s.start)).toList()..sort();
      target = opens.isEmpty ? start : opens.first;
    }
    final y = isTablet(context) ? (target - start) / 60 * _hourH : _slotY(b, target);
    _vScroll.jumpTo((y - 64).clamp(0, _vScroll.position.maxScrollExtent));
  }

  static const _hourH = 120.0;
  static const _colW = 200.0;
  static const _timeW = 56.0;

  // 폰 — 그 시간대 줄의 위치(줄 높이 = 카드 수에 따라)
  double _slotY(ResvBoard b, int min) {
    var y = 0.0;
    for (final r in slotRows(b, groupFilter: _group, filterOn: _filterOn)) {
      if (r.min >= min) break;
      y += _rowH(r.cards.length);
    }
    return y;
  }

  double _rowH(int n) => 16 + (n == 0 ? 24 : n * 52 + (n - 1) * 6);

  Future<void> _readQr() async {
    String? raw;
    try {
      raw = await const ScanChannel().scanQr();
    } on NoCamera {
      _app.toaster.show('카메라를 쓸 수 없어요');
      return;
    }
    if (raw != null) await _app.claimQr(raw);
  }

  void _open(ResvCard c) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => ReservationDetailScreen(reservationId: c.reservationId)));

  @override
  Widget build(BuildContext context) {
    final tablet = isTablet(context);
    final b = _board;
    final today = todayKst();
    return TabScaffold(
      // 머리 오른쪽 [QR 읽기] — 코디 폰이 웹 QR 을 찍는 자리(§6.10 · D7-44)
      head: TabHead(tablet: tablet, title: '예약 현황', trailing: [
        MsButton('QR 읽기', size: BtnSize.sm, variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _readQr),
      ]),
      body: Column(children: [
        // 날짜 줄 ‹ 날짜 › · [오늘] · 범례(주 상태 7 · 개수) · 총 예약 N건
        Container(
          color: Ms.white,
          padding: EdgeInsets.fromLTRB(tablet ? 24 : 12, 8, tablet ? 24 : 16, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              IconButton(
                  visualDensity: VisualDensity.compact, onPressed: () => _go(shiftDate(_date, -1)), icon: const Icon(Icons.chevron_left_rounded), tooltip: '전날'),
              Flexible(child: Text(dateTitle(_date), maxLines: 1, style: Typo.headingMd600)),
              IconButton(
                  visualDensity: VisualDensity.compact, onPressed: () => _go(shiftDate(_date, 1)), icon: const Icon(Icons.chevron_right_rounded), tooltip: '다음 날'),
              const Spacer(),
              MsButton('오늘', size: BtnSize.sm, variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _date == today ? null : () => _go(today)),
            ]),
            if (b != null) ...[
              const SizedBox(height: 6),
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: ResvLegend(b.counts)),
                const SizedBox(width: 8),
                Text('총 예약 ${b.counts['total'] ?? 0}건', style: Typo.body600.copyWith(color: Ms.gray700)),
              ]),
            ],
          ]),
        ),
        if (b != null && !tablet) _chips(b),
        const Divider(height: 1, thickness: 1, color: Ms.gray200),
        Expanded(
          child: b == null
              ? Center(
                  child: _error != null
                      ? Text(_error!, style: Typo.body500.copyWith(color: Ms.gray600))
                      : const CircularProgressIndicator(strokeWidth: 2))
              : RefreshIndicator(onRefresh: poll, child: tablet ? _table(b) : _slots(b)),
        ),
      ]),
    );
  }

  // 칩 줄 — 「전체」 + KOS 예약 그룹(order 순 · 가로 스크롤). 구역 칩 없음(D7-28)
  Widget _chips(ResvBoard b) {
    Widget chip(String name, bool on, VoidCallback tap) => Padding(
          padding: const EdgeInsets.only(right: 6),
          child: GestureDetector(
            onTap: tap,
            child: Container(
              height: 32,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: on ? Ms.primary : Ms.white,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: on ? Ms.primary : Ms.gray300),
              ),
              child: Text(name, style: Typo.body500.copyWith(color: on ? Ms.white : Ms.gray700, height: 1.2)),
            ),
          ),
        );
    return Container(
      color: Ms.white,
      height: 48,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
        children: [
          chip('전체', !_filterOn, () => setState(() => _filterOn = false)),
          for (final c in b.columns)
            chip(c.title, _filterOn && _group == c.groupId, () => setState(() {
                  _filterOn = true;
                  _group = c.groupId;
                })),
        ],
      ),
    );
  }

  // 폰 — 30분 시간대 목록 · 지금 시간대 파란 바탕
  Widget _slots(ResvBoard b) {
    final rows = slotRows(b, groupFilter: _group, filterOn: _filterOn);
    final now = nowSlot(b);
    return ListView.builder(
      controller: _vScroll,
      physics: const AlwaysScrollableScrollPhysics(),
      itemCount: rows.length,
      itemBuilder: (_, i) {
        final r = rows[i];
        final cur = r.min == now;
        return Container(
          constraints: BoxConstraints(minHeight: _rowH(r.cards.length)),
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          decoration: BoxDecoration(
            color: cur ? Ms.primary100 : Ms.white,
            border: const Border(bottom: BorderSide(color: Ms.gray200)),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(
              width: 48,
              child: Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(r.label, style: Typo.caption500.copyWith(color: cur ? Ms.primary : Ms.gray600, fontFeatures: tabular)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                for (var k = 0; k < r.cards.length; k++) ...[
                  if (k > 0) const SizedBox(height: 6),
                  ResvCardTile(card: r.cards[k], onTap: () => _open(r.cards[k])),
                ],
              ]),
            ),
          ]),
        );
      },
    );
  }

  // 태블릿 — 시간 × 칸 표. 칸마다 자기 간격 · 1시간 높이 같음 · 운영 밖 회색 · 칸 머리 「{정원}명 / {간격}분」
  Widget _table(ResvBoard b) {
    final start = hmToMin(b.axis?.start ?? '06:00');
    final end = hmToMin(b.axis?.end ?? '22:00');
    final h = (end - start) / 60 * _hourH;
    final now = b.isToday ? kstMin(b.now) : null;
    final cols = b.columns;
    // 칸 폭 = 한 시간대에 가장 많이 겹친 카드 수만큼(카드 184 + 간격)
    double colW(ResvColumn c) {
      final cards = b.cards.where((x) => x.groupId == c.groupId);
      final per = <int, int>{};
      for (final x in cards) {
        final s = kstMin(x.start) ?? 0;
        final k = s - s % c.intervalMinutes;
        per[k] = (per[k] ?? 0) + 1;
      }
      final n = per.values.fold(1, (a, v) => v > a ? v : a).clamp(1, 4);
      return (_colW * n).toDouble();
    }

    final widths = [for (final c in cols) colW(c)];
    final headH = 56 * uiScale(MediaQuery.sizeOf(context)); // 글자 배율만큼(T4)
    final head = Row(children: [
      for (var i = 0; i < cols.length; i++)
        Container(
          width: widths[i],
          padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
          decoration: const BoxDecoration(color: Ms.white, border: Border(right: BorderSide(color: Ms.gray200), bottom: BorderSide(color: Ms.gray300))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${cols[i].title} ${cols[i].count}', maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600),
            Text(cols[i].groupId == null ? '' : '${capacityText(cols[i], b.zones)} / ${cols[i].intervalMinutes}분',
                maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.caption400.copyWith(color: Ms.gray600)),
          ]),
        ),
    ]);
    Widget column(ResvColumn c, double w) {
      final step = c.intervalMinutes <= 0 ? 30 : c.intervalMinutes;
      final cards = b.cards.where((x) => x.groupId == c.groupId).toList();
      final kids = <Widget>[];
      // 운영 밖 회색
      kids.add(Positioned.fill(child: Container(color: Ms.gray200)));
      for (final s in c.open) {
        final y0 = (hmToMin(s.start) - start) / 60 * _hourH;
        final y1 = (hmToMin(s.end) - start) / 60 * _hourH;
        kids.add(Positioned(top: y0, height: y1 - y0, left: 0, right: 0, child: Container(color: Ms.white)));
      }
      for (var m = start; m < end; m += step) {
        kids.add(Positioned(
            top: (m - start) / 60 * _hourH, left: 0, right: 0, child: Container(height: 1, color: m % 60 == 0 ? Ms.gray300 : Ms.gray200)));
      }
      final bySlot = <int, List<ResvCard>>{};
      for (final x in cards) {
        final s = kstMin(x.start) ?? start;
        bySlot.putIfAbsent(s - (s - start) % step, () => []).add(x);
      }
      for (final e in bySlot.entries) {
        final top = (e.key - start) / 60 * _hourH + 3;
        for (var k = 0; k < e.value.length; k++) {
          kids.add(Positioned(
            top: top,
            left: 4 + k * _colW,
            width: _colW - 8,
            child: ResvCardTile(card: e.value[k], onTap: () => _open(e.value[k])),
          ));
        }
      }
      return Container(
        width: w,
        height: h,
        decoration: const BoxDecoration(border: Border(right: BorderSide(color: Ms.gray200))),
        child: Stack(clipBehavior: Clip.hardEdge, children: kids),
      );
    }

    final timeCol = SizedBox(
      width: _timeW,
      height: h,
      child: Stack(children: [
        for (var m = start; m < end; m += 30)
          Positioned(
            top: (m - start) / 60 * _hourH + 2,
            left: 0,
            right: 6,
            child: Text(minToHm(m),
                textAlign: TextAlign.right,
                style: Typo.caption500.copyWith(color: m == (now == null ? -1 : now - now % 30) ? Ms.primary : Ms.gray600, fontFeatures: tabular)),
          ),
      ]),
    );
    final nowLine = now == null || now < start || now > end
        ? null
        : Positioned(top: (now - start) / 60 * _hourH, left: 0, right: 0, child: Container(height: 2, color: Ms.red));

    return Column(children: [
      // 열 머리 고정 · 가로 스크롤은 본문과 같이
      Row(children: [
        Container(width: _timeW, height: headH, decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray300)))),
        Expanded(
          child: SingleChildScrollView(
            controller: _hHead,
            scrollDirection: Axis.horizontal,
            physics: const NeverScrollableScrollPhysics(),
            child: SizedBox(height: headH, child: head),
          ),
        ),
      ]),
      Expanded(
        child: SingleChildScrollView(
          controller: _vScroll,
          physics: const AlwaysScrollableScrollPhysics(),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(color: Ms.white, child: timeCol),
            Expanded(
              child: SingleChildScrollView(
                controller: _hBody,
                scrollDirection: Axis.horizontal,
                child: Stack(children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [for (var i = 0; i < cols.length; i++) column(cols[i], widths[i])]),
                  ?nowLine,
                ]),
              ),
            ),
          ]),
        ),
      ),
    ]);
  }
}
