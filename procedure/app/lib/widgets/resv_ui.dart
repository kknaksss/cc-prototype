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
  // 한 줄(사용자 2026-10-28 — 두 줄로 꺾이지 않게) · 넘치면 가로 스크롤 · 공통 StatusChip
  @override
  Widget build(BuildContext context) => ChipRow([
        for (final l in legend) StatusChip(mainName[l.main]!, count: counts[l.main.name] ?? 0, bg: l.bg, fg: l.fg, outline: l.outline),
      ]);
}

// 공통 상태 칩(사용자 2026-10-28 「탭마다 칩 디자인이 다 다르다」) — 예약 현황 범례 칩이 기준: 알약 · caption 600 · 웹 2계층 색 · 「이름 개수」.
// 범례(onTap 없음) = 상태 색 그대로 / 필터(onTap) = 고르지 않음 흰 바탕 · 회색 글자 · gray-300 테두리(점이 상태 색) ·
// 고름 = primary-100 · primary 글자 · primary 테두리. 보이는 크기는 같고 누르는 자리만 위아래로 넓다
class StatusChip extends StatelessWidget {
  final String label;
  final int? count;
  final Color bg, fg;
  final Color? outline;
  final Color? dot, dotRing; // 필터 점(시술 현황 ○ 대기 · ● 진행 등)
  final bool selected;
  final VoidCallback? onTap;
  const StatusChip(this.label,
      {super.key, this.count, this.bg = Ms.gray100, this.fg = Ms.gray700, this.outline, this.dot, this.dotRing, this.selected = false, this.onTap});

  @override
  Widget build(BuildContext context) {
    final filter = onTap != null;
    final (b, f, o) = !filter ? (bg, fg, outline ?? bg) : selected ? (Ms.primary100, Ms.primary, Ms.primary) : (Ms.white, Ms.gray700, Ms.gray300);
    final chip = Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: b, borderRadius: BorderRadius.circular(999), border: Border.all(color: o)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (dot != null) ...[
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: dot, shape: BoxShape.circle, border: dotRing != null ? Border.all(color: dotRing!, width: 1.5) : null),
          ),
          const SizedBox(width: 4),
        ],
        Text(count == null ? label : '$label $count', style: Typo.caption600.copyWith(color: f)),
      ]),
    );
    if (!filter) return chip;
    return Semantics(
      button: true,
      selected: selected,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Padding(padding: const EdgeInsets.symmetric(vertical: 6), child: chip),
      ),
    );
  }
}

// 칩 한 줄 — 넘치면 가로 스크롤 · 간격 4 · **위 · 아래 여백도 여기서**(모든 탭 같게 · 예약 현황 그룹 필터 줄이 기준 ·
// 사용자 batch 4 #2 — 화면마다 감싸는 여백이 달라 탭마다 칩 위 · 아래가 달랐다). 화면은 좌우만 준다.
// 보이는 칩 위 · 아래 = chipRowVertical(2) + 필터 칩 누르는 자리(6)
const double chipRowVertical = 2;

class ChipRow extends StatelessWidget {
  final List<Widget> chips;
  final double left, right;
  const ChipRow(this.chips, {super.key, this.left = 0, this.right = 0});
  @override
  Widget build(BuildContext context) => Align(
        alignment: Alignment.centerLeft, // 칩이 짧아도 왼쪽부터(가운데 뜨지 않게)
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: EdgeInsets.fromLTRB(left, chipRowVertical, right, chipRowVertical),
          child: Row(children: [
            for (final (i, c) in chips.indexed) ...[if (i > 0) const SizedBox(width: 4), c],
          ]),
        ),
      );
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
