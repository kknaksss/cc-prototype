// 예약 현황 공용 조각 — 국기 · 성별 · 초진/재진 · 2계층 칩 · 예약 카드 · 범례 · 원내 카드(웹 ScheduleTable · ResvAside 꼴)
import 'package:flutter/material.dart';

import '../model/reservation.dart';
import '../theme/tokens.dart';
import '../view/resv_view.dart';
import '../view/state.dart';

// 국기(18×12 자리) — 표에 없는 코드 · 빈 값 = 회색 상자 + 코드(없으면 「-」)
class Flag extends StatelessWidget {
  final String? code;
  const Flag(this.code, {super.key});

  @override
  Widget build(BuildContext context) {
    final e = flagEmoji(code);
    if (e != null) {
      return Semantics(label: nationName(code), child: Text(e, style: const TextStyle(fontSize: 14, height: 1.1)));
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
      decoration: BoxDecoration(color: Ms.gray100, border: Border.all(color: Ms.gray300), borderRadius: BorderRadius.circular(4)),
      child: Text((code ?? '').isEmpty ? '-' : code!, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: Ms.gray500, height: 1.2)),
    );
  }
}

// 성별 ♂ primary · ♀ red · 모르면 없음
Widget genderIcon(String? g) => switch (g) {
      'MALE' => Semantics(label: '남성', child: const Text('♂', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: Ms.primary, height: 1.2))),
      'FEMALE' => Semantics(label: '여성', child: const Text('♀', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: Ms.red, height: 1.2))),
      _ => const SizedBox.shrink(),
    };

// 작은 네모 칩(11px · 반경 4) — 초진/재진 · 부상태
class MiniChip extends StatelessWidget {
  final String text;
  final Color bg, fg;
  const MiniChip(this.text, this.bg, this.fg, {super.key});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(4)),
        child: Text(text, style: TextStyle(fontFamily: 'Pretendard', fontSize: 11, fontWeight: FontWeight.w600, color: fg, height: 1.45)),
      );
}

Widget visitChip(bool isNew) => isNew ? const MiniChip('초진', Ms.purple100, Ms.purple) : const MiniChip('재진', Ms.gray100, Ms.gray600);

// 2계층 상태 칩(알약) — 부상태 있으면 단계 색 · 없으면 대기 꼴(웹 원내 카드 · phaseStyle(main, sub ?? waiting))
class StateChip extends StatelessWidget {
  final ResvState state;
  const StateChip(this.state, {super.key});
  @override
  Widget build(BuildContext context) {
    final p = phaseStyle(state.main, phaseOfSub(state.sub) ?? Phase.waiting);
    final closed = isClosed(state.main);
    final l = legend.firstWhere((x) => x.main == state.main);
    final (bg, fg) = closed ? (l.bg, l.fg) : (p.chipBg, p.chipFg);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
        border: l.outline != null ? Border.all(color: l.outline!) : null,
      ),
      child: Text(state.text, style: Typo.caption600.copyWith(color: fg)),
    );
  }
}

// 「수납 필요」 Badge(warning)
Widget payDue() => Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(color: Ms.yellow100, borderRadius: BorderRadius.circular(999)),
      child: Text('수납 필요', style: Typo.caption600.copyWith(fontSize: 11, color: Ms.yellow)),
    );

// 예약 카드(웹 ResvCard) — 왼쪽 막대 4px(주 상태) · 성별 · 이름 · 초진/재진 · 부상태 칩 / 국기 · 발음 · 수납 필요. 취소 · 부도 = 흐림 + 줄긋기
class ResvCardTile extends StatelessWidget {
  final ResvCard card;
  final VoidCallback onTap;
  const ResvCardTile({super.key, required this.card, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final c = card.customer;
    final bar = barOf(card.state.main, card.state.sub);
    final closed = isClosed(card.state.main);
    final sub = card.state.sub;
    final subLook = sub == null ? null : phaseStyle(card.state.main, phaseOfSub(sub) ?? Phase.none);
    return Opacity(
      opacity: closed ? 0.5 : 1,
      child: Semantics(
        button: true,
        label: '${c.name} ${card.state.text}',
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: Container(
            decoration: BoxDecoration(color: Ms.white, border: Border.all(color: Ms.gray300), borderRadius: BorderRadius.circular(6)),
            clipBehavior: Clip.antiAlias,
            child: IntrinsicHeight(
              child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Container(
                  width: 4,
                  decoration: BoxDecoration(color: bar.color, border: bar.outline != null ? Border.all(color: bar.outline!) : null),
                ),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(6, 5, 6, 5),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
                      Row(children: [
                        genderIcon(c.gender),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(c.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Typo.caption600.copyWith(decoration: closed ? TextDecoration.lineThrough : null)),
                        ),
                        const SizedBox(width: 4),
                        visitChip(c.isNew),
                        if (sub != null && subLook != null) ...[const SizedBox(width: 4), MiniChip(subName[sub]!, subLook.chipBg, subLook.chipFg)],
                      ]),
                      const SizedBox(height: 2),
                      Row(children: [
                        Flag(c.nationality),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(c.phoneticName ?? '',
                              maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.caption400.copyWith(color: Ms.gray600)),
                        ),
                        if (card.paymentRequiredCount >= 1) payDue(),
                      ]),
                    ]),
                  ),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

// 범례 7(주 상태 · 개수 함께 — §6.10)
class ResvLegend extends StatelessWidget {
  final Map<String, int> counts;
  const ResvLegend(this.counts, {super.key});
  @override
  Widget build(BuildContext context) => Wrap(spacing: 6, runSpacing: 6, children: [
        for (final l in legend)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: l.bg,
              borderRadius: BorderRadius.circular(999),
              border: l.outline != null ? Border.all(color: l.outline!) : null,
            ),
            child: Text('${mainName[l.main]} ${counts[l.main.name] ?? 0}', style: Typo.caption600.copyWith(color: l.fg)),
          ),
      ]);
}

// 원내(내원 현황) 카드 — 이름 · 발음 · 국기 / 수납 필요 Badge 또는 상태 칩 / 전체 · 결제 · 수납 필요 칸(웹 ClinicCard)
class ClinicCard extends StatelessWidget {
  final ClinicItem item;
  final VoidCallback onTap;
  const ClinicCard({super.key, required this.item, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final due = item.paymentRequiredCount >= 1;
    final cells = [
      ('전체', moneyOf(item.amount, true), false),
      ('결제', moneyOf(item.amount, false), false),
      ('수납 필요', due ? '${item.paymentRequiredCount}건' : '-', due),
    ];
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        decoration: BoxDecoration(color: Ms.white, border: Border.all(color: Ms.gray300), borderRadius: BorderRadius.circular(8)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Flexible(child: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600)),
            if ((item.phoneticName ?? '').isNotEmpty) ...[
              const SizedBox(width: 6),
              Flexible(child: Text(item.phoneticName!, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body400.copyWith(color: Ms.gray500))),
            ],
            const SizedBox(width: 6),
            Flag(item.nationality),
            const Spacer(),
            if (due)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: Ms.red100, borderRadius: BorderRadius.circular(999)),
                child: Text('수납 필요', style: Typo.caption600.copyWith(color: Ms.red)),
              )
            else
              StateChip(item.state),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            for (var i = 0; i < cells.length; i++) ...[
              if (i > 0) const SizedBox(width: 4),
              Expanded(
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(color: cells[i].$3 ? Ms.red100 : Ms.gray100, borderRadius: BorderRadius.circular(6)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(cells[i].$1, style: Typo.caption400.copyWith(color: Ms.gray500)),
                    Text(cells[i].$2,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Typo.body600.copyWith(
                            color: cells[i].$3 ? Ms.red : (cells[i].$2 == '-' ? Ms.gray400 : Ms.gray800), fontFeatures: tabular)),
                  ]),
                ),
              ),
            ],
          ]),
        ]),
      ),
    );
  }
}
