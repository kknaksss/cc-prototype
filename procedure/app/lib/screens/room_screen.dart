// 룸 상세(SPEC-004 §6.3) — 모바일 = 한 열 · 태블릿 = 두 열(왼쪽 오더 메모 · 마취 / 오른쪽 시술 · 호출 · 완료)
// 버튼의 보임 · 켜짐 = 스냅샷 값만(§6.0)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../interpret/langs.dart';
import '../model/board.dart';
import '../theme/tokens.dart';
import '../view/time.dart';
import '../view/view.dart';
import '../widgets/accept.dart';
import '../widgets/call_sheet.dart';
import '../widgets/interpret_bar.dart';
import '../widgets/interpret_drawer.dart';
import '../widgets/ui.dart';
import 'board_screen.dart' show clockText, isTablet;

class RoomScreen extends StatefulWidget {
  final int visitId;
  const RoomScreen({super.key, required this.visitId});
  @override
  State<RoomScreen> createState() => _RoomScreenState();
}

class _RoomScreenState extends State<RoomScreen> {
  String? _roomTitle;
  bool _gone = false;
  bool _drawer = false;
  // 드로어에서 고른 언어(null = 국적 자동)
  String? _lang;
  String? _lastTalk; // 「마지막 통역 HH:MM · N문장」

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final tablet = isTablet(context);
    return ListenableBuilder(
      listenable: app.stream,
      builder: (context, _) {
        final b = app.stream.board;
        BoardCard? c;
        for (final x in b?.cards ?? const <BoardCard>[]) {
          if (x.visitId == widget.visitId) c = x;
        }
        if (b != null && c == null) {
          _leave(app);
          return const Scaffold(backgroundColor: Ms.gray100);
        }
        if (b == null || c == null) {
          return const Scaffold(backgroundColor: Ms.gray100, body: Center(child: CircularProgressIndicator(strokeWidth: 2)));
        }
        _roomTitle = c.room.title;
        final auto = autoLang(c.customer.nationality);
        final langCode = _lang ?? auto.code;
        final traditional = langCode == 'zh' && auto.code == 'zh' ? auto.traditional : false;
        final card = c;
        return Scaffold(
          backgroundColor: Ms.gray100,
          body: Stack(children: [
            SafeArea(
              bottom: false,
              child: Column(children: [
                _header(app, b, card),
                Expanded(
                  child: Ticker(builder: (context) {
                    final now = DateTime.now().millisecondsSinceEpoch + app.stream.skewMs;
                    return tablet ? _tabletBody(app, b, card, now) : _mobileBody(app, b, card, now);
                  }),
                ),
                InterpretBar(
                  tablet: tablet,
                  langCode: langCode,
                  traditional: traditional,
                  lastTalk: _lastTalk,
                  onOpen: () => setState(() => _drawer = true),
                ),
              ]),
            ),
            if (_drawer)
              InterpretDrawer(
                tablet: tablet,
                room: card.room.title,
                customerName: card.customer.name,
                nationality: card.customer.nationality,
                langCode: langCode,
                traditional: traditional,
                autoCode: auto.code,
                onLang: (code) => setState(() => _lang = code),
                onClose: (summary) => setState(() {
                  _drawer = false;
                  if (summary != null) _lastTalk = summary;
                }),
              ),
          ]),
        );
      },
    );
  }

  // 이 방 카드가 판에서 사라짐 → 토스트 · 목록으로(§6.3)
  void _leave(AppState app) {
    if (_gone) return;
    _gone = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      app.toaster.show('${_roomTitle ?? '이 방'} 고객이 판에서 빠졌어요');
      Navigator.of(context).maybePop();
    });
  }

  Widget _header(AppState app, Board b, BoardCard c) {
    final others = b.counts.need - (c.need != null ? 1 : 0);
    final badge = cardBadge(b, c);
    final kos = kosText(c.kos);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      decoration: const BoxDecoration(color: Ms.white, border: Border(bottom: BorderSide(color: Ms.gray200))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => Navigator.of(context).maybePop(),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 44),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Row(children: [
                  Text('← 현황', style: Typo.body600),
                  if (others > 0) ...[
                    const SizedBox(width: 6),
                    Text('다른 룸 확인 $others', style: Typo.caption600.copyWith(color: Ms.red)),
                  ],
                ]),
              ),
            ),
          ),
          // Spacer + Flexible 은 남는 폭을 반씩 나눠 짧은 배지가 가운데 뜬다(E2E A4) — 한 칸에 오른쪽 정렬
          Expanded(child: Align(alignment: Alignment.centerRight, child: MsBadge(badge.text, badge.variant))),
          const SizedBox(width: 10),
          Ticker(builder: (_) => Text(clockText(app), style: Typo.headingSm400.copyWith(color: Ms.black, fontFeatures: tabular))),
        ]),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              Text(c.room.title, style: Typo.titleMd600),
              const SizedBox(width: 8),
              Expanded(child: Text(c.customer.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600)),
            ]),
            const SizedBox(height: 2),
            Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              if ((c.customer.nationality ?? '').isNotEmpty) Tag(c.customer.nationality!),
              visitTag(c.customer.isNew),
              if (c.inAt != null) Text('입실 ${hm(c.inAt)}', style: Typo.caption400.copyWith(color: Ms.gray600)),
              if (c.paymentRequired) const Tag('수납 필요', bg: Ms.yellow100, fg: Ms.yellow, bold: true),
              if (kos != null)
                Text(kos, style: Typo.caption600.copyWith(color: c.kos.status == 'failed' ? Ms.red : Ms.gray600)),
            ]),
          ]),
        ),
      ]),
    );
  }

  Widget _mobileBody(AppState app, Board b, BoardCard c, int now) => ListView(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
        children: _gap([
          ..._callBoxes(app, b, c, now),
          if (c.canHome) _doneBox(app, c),
          // E2E A5 — 오더 메모 → 마취 → 시술(+[의사 호출]) · 지금 할 일(호출 · 완료)은 맨 위
          _memoBox(c),
          _anesBox(app, b, c, now),
          _procBox(app, b, c, now),
        ]),
      );

  Widget _tabletBody(AppState app, Board b, BoardCard c, int now) => Padding(
        padding: const EdgeInsets.fromLTRB(24, 16, 24, 16),
        child: LayoutBuilder(builder: (context, box) {
          final left = (box.maxWidth * 0.34).clamp(260.0, 380.0);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(
              width: left,
              child: ListView(children: _gap([_memoBox(c), _anesBox(app, b, c, now)])),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: ListView(children: _gap([
                ..._callBoxes(app, b, c, now),
                if (c.canHome) _doneBox(app, c),
                _procBox(app, b, c, now),
              ])),
            ),
          ]);
        }),
      );

  List<Widget> _gap(List<Widget> ws) => [
        for (var i = 0; i < ws.length; i++) ...[if (i > 0) const SizedBox(height: 8), ws[i]],
      ];

  // 호출 상자 — 이 카드의 받을 호출마다(§6.3 #2)
  List<Widget> _callBoxes(AppState app, Board b, BoardCard c, int now) {
    final me = app.me;
    return [
      for (final k in callsOf(b, c.visitId))
        () {
          final m = minutesSince(k.createdAt, now);
          final late = b.limits.callMin > 0 && m >= b.limits.callMin;
          final mine = isMine(k, me);
          final title = '${k.kind == 'all' ? '전체 호출' : '${docName(b, k.targetDoctorId)} 지정 호출'} · 수락 대기';
          final sub = '${hm(k.createdAt)} 호출 · 시술 ${k.procedures.length}건 · 기준 ${b.limits.callMin}분${late ? ' 넘음' : ''}';
          return Boxed(
            color: late ? Ms.red100 : Ms.primary100,
            border: late ? Ms.red : Ms.primary,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(title, style: Typo.titleSm600.copyWith(color: late ? Ms.red : Ms.primary)),
                    const SizedBox(height: 4),
                    Text(sub, style: Typo.caption500.copyWith(color: Ms.gray700)),
                  ]),
                ),
                Text('$m분',
                    style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600, height: 1, color: late ? Ms.red : Ms.primary, fontFeatures: tabular)),
              ]),
              const SizedBox(height: 10),
              // 의사(나에게 온 호출) = [수락 · N건] · 관리자(모든 호출 · A-15) = 전체 → 원장 고르기 / 지정 → 지정 원장으로 + [다른 원장에게]
              if (mine && me.admin && k.kind == 'one')
                Row(children: [
                  Expanded(
                    flex: 3,
                    child: MsButton('${docName(b, k.targetDoctorId)}으로 수락 · ${k.procedures.length}건',
                        size: BtnSize.lg, expand: true, onPressed: () => acceptCall(context, b, c, k)),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    flex: 2,
                    child: MsButton('다른 원장에게',
                        size: BtnSize.lg,
                        variant: BtnVariant.outlined,
                        color: BtnColor.gray,
                        expand: true,
                        onPressed: () => app.run(() => app.api.reassignAll(k.callId), '${c.room.title} 전체 호출로 바꿈')),
                  ),
                ])
              else if (mine)
                MsButton(me.admin ? '원장 골라 수락 · ${k.procedures.length}건' : '수락 · ${k.procedures.length}건',
                    size: BtnSize.lg, expand: true, onPressed: () => acceptCall(context, b, c, k))
              else
                Row(children: [
                  Expanded(
                    child: MsButton('다른 의사 호출',
                        variant: BtnVariant.outlined,
                        expand: true,
                        onPressed: () => openCallSheet(context, visitId: c.visitId, preselect: k.procedures.map((p) => p.id).toSet())),
                  ),
                  if (k.kind == 'one') ...[
                    const SizedBox(width: 8),
                    Expanded(
                      child: MsButton('다른 원장에게',
                          variant: BtnVariant.outlined,
                          color: BtnColor.gray,
                          expand: true,
                          onPressed: () => app.run(() => app.api.reassignAll(k.callId), '${c.room.title} 전체 호출로 바꿈')),
                    ),
                  ],
                ]),
            ]),
          );
        }(),
    ];
  }

  // 완료 상자(canHome) — [귀가 대기]
  Widget _doneBox(AppState app, BoardCard c) {
    final ends = procsOnly(c).map((p) => toMs(p.completedAt)).whereType<int>().toList()..sort();
    return Boxed(
      color: Ms.primary100,
      border: Ms.primary,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('시술 모두 완료', style: Typo.headingMd500.copyWith(color: Ms.primary)),
        if (ends.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text('마지막 종료 ${hmMs(ends.last)}', style: Typo.caption500.copyWith(color: Ms.gray700)),
        ],
        const SizedBox(height: 8),
        MsButton('귀가 대기',
            expand: true, onPressed: () => app.run(() => app.api.goHome(c.visitId), '${c.room.title} ${c.customer.name} 귀가 대기')),
      ]),
    );
  }

  Widget _procBox(AppState app, Board b, BoardCard c, int now) {
    final ps = orderedProcs(c);
    final done = ps.where((p) => p.state == 'done').length;
    return Boxed(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 2),
          child: Text.rich(TextSpan(children: [
            TextSpan(text: '시술 ${ps.length} ', style: Typo.headingMd500),
            TextSpan(text: '· 완료 $done', style: Typo.body400.copyWith(color: Ms.gray600)),
          ])),
        ),
        for (final p in ps) ...[const SizedBox(height: 6), _procRow(app, b, c, p, now)],
        const SizedBox(height: 10),
        MsButton(c.canCall ? '의사 호출' : '호출할 대기 시술 없음',
            variant: BtnVariant.outlined,
            color: BtnColor.gray,
            expand: true,
            onPressed: c.canCall ? () => openCallSheet(context, visitId: c.visitId, preselect: const {}) : null),
      ]),
    );
  }

  Widget _procRow(AppState app, Board b, BoardCard c, Procedure p, int now) {
    final line = procLine(b, p);
    final doing = p.state == 'doing';
    final titleStyle = switch (p.state) {
      'done' => Typo.headingMd400.copyWith(color: Ms.gray500),
      'doing' => Typo.titleMd600.copyWith(color: Ms.primary),
      _ => Typo.titleSm600,
    };
    final lineStyle = switch (line.tone) {
      LineTone.muted => Typo.caption400.copyWith(color: Ms.gray500),
      LineTone.accent => Typo.caption600.copyWith(color: Ms.primary),
      LineTone.normal => Typo.caption500.copyWith(color: Ms.gray700),
    };
    final called = p.state == 'wait' && p.call != null && p.call!.acceptedBy == null;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: doing ? Ms.primary100 : Ms.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: doing ? Ms.primary : Ms.gray200),
      ),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(p.title, style: titleStyle),
            const SizedBox(height: 2),
            Text(line.text, style: lineStyle),
          ]),
        ),
        const SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          if (doing)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(elapsed(p.startedAt, now),
                  style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600, height: 1, color: Ms.primary, fontFeatures: tabular)),
            ),
          if (called) const Padding(padding: EdgeInsets.only(bottom: 4), child: MsBadge('호출함', BadgeVariant.primary, dot: false)),
          if (p.state == 'wait')
            MsButton('시작',
                variant: BtnVariant.outlined,
                onPressed: p.canStart ? () => app.run(() => app.api.startProcedure(p.id), '${p.title} 시작') : null),
          if (doing)
            MsButton('종료', onPressed: p.canFinish ? () => app.run(() => app.api.finishProcedure(p.id), '${p.title} 종료') : null),
          if (p.state == 'done') const MsBadge('완료', BadgeVariant.neutral, dot: false),
        ]),
      ]),
    );
  }

  // 마취 상자 — 시술 진행 중에도 버튼이 켜질 수 있다(D-23 · 시안 X6 버림)
  Widget _anesBox(AppState app, Board b, BoardCard c, int now) {
    final a = c.anesthesia;
    final on = a.runningSince != null;
    final m = minutesSince(a.runningSince, now);
    return Boxed(
      color: on ? Ms.purple100 : Ms.white,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
          Expanded(child: Text(on ? '마취 중' : '마취', style: Typo.caption600.copyWith(color: on ? Ms.purple : Ms.gray700))),
          if (on)
            Text('$m분', style: Typo.titleMd600.copyWith(color: a.long ? Ms.red : Ms.purple, fontFeatures: tabular))
          else if (a.lastMinutes != null)
            Text('완료 ${a.lastMinutes}분', style: Typo.body600.copyWith(color: Ms.purple))
          else
            Text('안 함', style: Typo.body500.copyWith(color: Ms.gray600)),
        ]),
        if (on) ...[
          const SizedBox(height: 4),
          Text('${hm(a.runningSince)} 시작 · 기준 ${b.limits.anesMin}분${a.long ? ' 넘음' : ''}',
              style: Typo.caption400.copyWith(color: Ms.gray700)),
        ],
        if (a.canStart) ...[
          const SizedBox(height: 8),
          MsButton('마취 시작',
              variant: BtnVariant.outlined,
              color: BtnColor.gray,
              expand: true,
              onPressed: () => app.run(() => app.api.anesStart(c.visitId), '${c.room.title} 마취 시작')),
        ],
        if (a.canEnd) ...[
          const SizedBox(height: 8),
          MsButton('마취 종료', expand: true, onPressed: () => app.run(() => app.api.anesEnd(c.visitId), '${c.room.title} 마취 종료')),
        ],
      ]),
    );
  }

  Widget _memoBox(BoardCard c) {
    final memo = (c.orderMemo ?? '').trim();
    return Boxed(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('오더 메모', style: Typo.caption600.copyWith(color: Ms.gray700)),
        const SizedBox(height: 6),
        Text(memo.isEmpty ? '오더 메모 없음' : memo, style: Typo.body400.copyWith(color: memo.isEmpty ? Ms.gray600 : Ms.gray800)),
      ]),
    );
  }
}

