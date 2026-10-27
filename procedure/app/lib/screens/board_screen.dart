// 시술실 현황 — 시술 현황 탭 루트(SPEC-004 §6.2 · §6.8). 모바일 = 한 줄 1장 · 태블릿 = 격자 minmax(270px,1fr)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../model/board.dart';
import '../theme/tokens.dart';
import '../view/time.dart';
import '../view/view.dart';
import '../widgets/accept.dart';
import '../widgets/header.dart';
import '../widgets/ui.dart';
import 'room_screen.dart';
import 'shell.dart' show TabScaffold;

// 화면 짧은 변 < 600 = 모바일 배치(§6.0)
bool isTablet(BuildContext context) => MediaQuery.sizeOf(context).shortestSide >= 600;

class BoardScreen extends StatefulWidget {
  const BoardScreen({super.key});
  @override
  State<BoardScreen> createState() => _BoardScreenState();
}

class _BoardScreenState extends State<BoardScreen> {
  FilterId _filter = FilterId.all;
  late final AppState _app;

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.openVisit.addListener(_maybeOpen);
    _app.stream.addListener(_maybeOpen);
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeOpen());
  }

  @override
  void dispose() {
    _app.openVisit.removeListener(_maybeOpen);
    _app.stream.removeListener(_maybeOpen);
    super.dispose();
  }

  // 알림을 눌러 연 방(§5-1.3) — 스냅샷이 오면 그 룸 상세로, 없으면 토스트 → 목록
  void _maybeOpen() {
    final v = _app.openVisit.value;
    final b = _app.stream.board;
    if (v == null || b == null || !mounted) return;
    _app.openVisit.value = null;
    final nav = Navigator.of(context);
    nav.popUntil((r) => r.isFirst);
    if (pushTarget(b, v) == null) {
      _app.toaster.show('호출이 끝났거나 방이 비었어요');
      return;
    }
    nav.push(MaterialPageRoute(builder: (_) => RoomScreen(visitId: v)));
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final tablet = isTablet(context);
    return ListenableBuilder(
      listenable: app.stream,
      builder: (context, _) {
        final b = app.stream.board;
        return TabScaffold(
          head: ListHeader(tablet: tablet, need: b?.counts.need ?? 0),
          body: b == null ? const Center(child: CircularProgressIndicator(strokeWidth: 2)) : _body(context, app, b, tablet),
        );
      },
    );
  }

  Widget _body(BuildContext context, AppState app, Board b, bool tablet) {
    final me = app.me;
    final ids = [
      FilterId.all,
      if (me.receives) FilterId.mine,
      FilterId.need,
      FilterId.waiting,
      FilterId.anes,
      FilterId.call,
      FilterId.doing,
      FilterId.home,
    ];
    final filter = ids.contains(_filter) ? _filter : FilterId.all;
    final pick = filterFn(filter, b, me);
    final cards = orderedCards(b.cards).where(pick).toList();
    return Column(children: [
      SizedBox(
        height: 43,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: EdgeInsets.fromLTRB(tablet ? 24 : 16, 10, tablet ? 24 : 16, 0),
          children: [
            for (final id in ids)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: FilterChipButton(
                  id: id,
                  label: '${filterName[id]} ${filterCount(id, b, me)}',
                  on: filter == id,
                  onTap: () => setState(() => _filter = id),
                ),
              ),
          ],
        ),
      ),
      Expanded(
        child: cards.isEmpty
            ? Center(child: Text('시술 중인 방이 없어요', style: Typo.body500.copyWith(color: Ms.gray600)))
            : Ticker(
                builder: (context) {
                  final now = DateTime.now().millisecondsSinceEpoch + app.stream.skewMs;
                  Widget card(BoardCard c) => RoomCard(board: b, card: c, now: now, me: me);
                  if (!tablet) {
                    return ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 10, 16, 24),
                      itemCount: cards.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 8),
                      itemBuilder: (_, i) => card(cards[i]),
                    );
                  }
                  return LayoutBuilder(builder: (context, box) {
                    // grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)) — 최소 폭도 글자 배율만큼(T4)
                    const gap = 12.0;
                    final w = box.maxWidth - 48;
                    final minW = 270 * uiScale(MediaQuery.sizeOf(context));
                    final cols = ((w + gap) / (minW + gap)).floor().clamp(1, 8);
                    final cw = (w - gap * (cols - 1)) / cols;
                    return SingleChildScrollView(
                      padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
                      // 폭 전체 · 왼쪽 위부터(T5) — 내용 폭으로 줄면 카드 1장이 가운데 뜬다
                      child: SizedBox(
                        width: double.infinity,
                        child: Wrap(
                          alignment: WrapAlignment.start,
                          runAlignment: WrapAlignment.start,
                          spacing: gap,
                          runSpacing: gap,
                          children: [for (final c in cards) SizedBox(width: cw, child: card(c))],
                        ),
                      ),
                    );
                  });
                },
              ),
      ),
    ]);
  }
}

class RoomCard extends StatelessWidget {
  final Board board;
  final BoardCard card;
  final int now;
  final Me me;
  const RoomCard({super.key, required this.board, required this.card, required this.now, this.me = Me.none});

  @override
  Widget build(BuildContext context) {
    final c = card;
    final tablet = isTablet(context);
    final badge = cardBadge(board, c);
    final box = nowBox(board, c, now);
    final prog = progressOf(c);
    final mine = callsOf(board, c.visitId).where((k) => isMine(k, me)).toList();
    final home = c.state == 'home';
    final doing = c.state == 'doing';
    final need = c.need != null;

    final (bg, fg, timerFg) = switch (box.kind) {
      NowKind.doing => (Ms.primary100, Ms.primary, Ms.primary),
      NowKind.call => box.red ? (Ms.red100, Ms.red, Ms.red) : (Ms.primary100, Ms.primary, Ms.primary),
      NowKind.anes => (Ms.purple100, Ms.purple, box.red ? Ms.red : Ms.purple),
      NowKind.home || NowKind.allDone => (Ms.gray100, Ms.gray700, Ms.gray800),
      NowKind.wait => (Ms.gray100, Ms.gray800, Ms.gray800),
    };

    return Opacity(
      opacity: home ? 0.55 : 1,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => RoomScreen(visitId: c.visitId))),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(
            color: Ms.white,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: need ? Ms.red : doing ? Ms.primary : Ms.gray200, width: need ? 2 : 1),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Text(c.room.title, style: Typo.headingMd500),
              const SizedBox(width: 8),
              // 고객 이름 + 한글 발음(없으면 안 그림 · 발음이 먼저 말줄임 — §6.2 · SPEC-003 §10.1 #5)
              Expanded(
                child: Text.rich(
                  TextSpan(children: [
                    TextSpan(text: c.customer.name, style: Typo.caption600),
                    if ((c.customer.phoneticName ?? '').trim().isNotEmpty)
                      TextSpan(text: '  ${c.customer.phoneticName!.trim()}', style: Typo.caption400.copyWith(color: Ms.gray600)),
                  ]),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              // 배지는 flex 를 받지 않는다 — Expanded 와 나눠 가지면 짧은 배지가 가운데쯤 뜬다(E2E A1)
              ConstrainedBox(constraints: const BoxConstraints(maxWidth: 190), child: MsBadge.of(badge)),
            ]),
            if (tablet) ...[
              const SizedBox(height: 6),
              Row(children: [
                if ((c.customer.nationality ?? '').isNotEmpty) ...[Tag(c.customer.nationality!), const SizedBox(width: 6)],
                visitTag(c.customer.isNew),
              ]),
            ],
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
              decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(box.title, style: Typo.body600.copyWith(color: fg)),
                    if (box.sub.isNotEmpty) Text(box.sub, style: Typo.caption500.copyWith(color: Ms.gray700)),
                  ]),
                ),
                if (box.timer.isNotEmpty)
                  Text(box.timer,
                      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, height: 1, color: timerFg, fontFeatures: tabular)),
              ]),
            ),
            if (prog.total > 0) ...[
              const SizedBox(height: 8),
              Row(children: [
                SizedBox(
                  width: 72,
                  child: Row(children: [
                    for (var i = 0; i < prog.steps.length; i++) ...[
                      if (i > 0) const SizedBox(width: 3),
                      Expanded(
                        child: Container(
                          height: 5,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(3),
                            color: switch (prog.steps[i]) {
                              'done' => Ms.gray400,
                              'doing' => Ms.primary,
                              _ => Ms.gray200,
                            },
                          ),
                        ),
                      ),
                    ],
                  ]),
                ),
                const SizedBox(width: 8),
                Text('${prog.done} / ${prog.total}', style: Typo.caption500.copyWith(color: Ms.gray600, fontFeatures: tabular)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(prog.next, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.caption400.copyWith(color: Ms.gray700)),
                ),
              ]),
            ],
            // 의사 계정 + 나에게 온 호출 — 호출마다 한 줄 [수락](§6.2 · §6.7 #3)
            for (final k in mine) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.only(top: 8),
                decoration: const BoxDecoration(border: Border(top: BorderSide(color: Ms.gray200))),
                child: Row(children: [
                  Expanded(
                    child: Text('${k.kind == 'all' ? '전체 호출' : me.admin ? '${docName(board, k.targetDoctorId)} 지정' : '나를 지정'} · ${k.procedures.length}건',
                        style: Typo.body600.copyWith(color: need ? Ms.red : Ms.primary)),
                  ),
                  MsButton('수락', onPressed: () => acceptCall(context, board, c, k)),
                ]),
              ),
            ],
          ]),
        ),
      ),
    );
  }
}

// 지금 시각(KST) — 머리 시계
String clockText(AppState app) => hmMs(DateTime.now().millisecondsSinceEpoch + app.stream.skewMs);

// 알림 visitId → 그 방 카드(없으면 null — 호출이 끝났거나 방이 비었음)
BoardCard? pushTarget(Board b, int visitId) {
  for (final c in b.cards) {
    if (c.visitId == visitId) return c;
  }
  return null;
}

// 필터 칸 — 점 꼴은 웹(SPEC-003 §5.14 #4 · D7-64): 대기 = ○(흰 속 primary 테두리) · 진행 = ● · 칸 이름 · 「귀가」 · 「수락 대기」는 앱 그대로
class FilterChipButton extends StatelessWidget {
  final FilterId id;
  final String label;
  final bool on;
  final VoidCallback onTap;
  const FilterChipButton({super.key, required this.id, required this.label, required this.on, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final d = filterDot[id];
    final h = 33 * uiScale(MediaQuery.sizeOf(context));
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Container(
        height: h,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: on ? Ms.primary100 : Ms.white,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? Ms.primary : Ms.gray300),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (d != null) ...[
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(color: d.fill, shape: BoxShape.circle, border: d.ring != null ? Border.all(color: d.ring!, width: 2) : null),
            ),
            const SizedBox(width: 6),
          ],
          Text(label, style: Typo.caption600.copyWith(fontSize: 13, color: on ? Ms.primary : Ms.gray800)),
        ]),
      ),
    );
  }
}
