// 상태 이름 · 색 = 웹 2계층(SPEC-004 §6.9 · D7-07) — 앱 한 곳.
// 원천 = 웹 procedure/front/components/reservations/view.tsx(MAIN_NAME · SUB_NAME · MAIN_TONE · phaseStyle · barStyle · headOf · LEGEND · stateText)
//      + components/procedures/view.ts(STATE_2 · stateBadge · procChip · FILTERS). 값을 새로 정하지 않는다 — 시안과 다르면 웹
import 'package:flutter/painting.dart';

import '../theme/tokens.dart';

// 주 상태 7 · 부상태 3(SPEC-005 §5.1)
enum ResvMain { reserved, reception, consultation, procedure, home, canceled, noshow }

enum ResvSub { waiting, doing, done }

ResvMain? resvMainOf(Object? v) => switch (v) {
      'reserved' => ResvMain.reserved,
      'reception' => ResvMain.reception,
      'consultation' => ResvMain.consultation,
      'procedure' => ResvMain.procedure,
      'home' => ResvMain.home,
      'canceled' => ResvMain.canceled,
      'noshow' => ResvMain.noshow,
      _ => null,
    };

ResvSub? resvSubOf(Object? v) => switch (v) {
      'waiting' => ResvSub.waiting,
      'doing' => ResvSub.doing,
      'done' => ResvSub.done,
      _ => null,
    };

const mainName = {
  ResvMain.reserved: '예약',
  ResvMain.reception: '접수',
  ResvMain.consultation: '상담',
  ResvMain.procedure: '시술',
  ResvMain.home: '귀가',
  ResvMain.canceled: '취소',
  ResvMain.noshow: '부도',
};
const subName = {ResvSub.waiting: '대기', ResvSub.doing: '진행', ResvSub.done: '완료'};

// 「상담 · 대기」 꼴(웹 stateText)
String stateText(ResvMain main, ResvSub? sub) => mainName[main]! + (sub != null ? ' · ${subName[sub]}' : '');
bool isClosed(ResvMain m) => m == ResvMain.canceled || m == ResvMain.noshow;

// 주 상태 색(웹 MAIN_TONE) — fill · soft(100) · text · border
class Tone {
  final Color fill, soft, text, border;
  const Tone(this.fill, this.soft, this.text, this.border);
}

const mainTone = {
  ResvMain.reserved: Tone(Ms.purple, Ms.purple100, Ms.purple, Ms.purple),
  ResvMain.reception: Tone(Ms.yellow, Ms.yellow100, Ms.yellow, Ms.yellow),
  ResvMain.consultation: Tone(Ms.cons, Ms.cons100, Ms.cons, Ms.cons),
  ResvMain.procedure: Tone(Ms.primary, Ms.primary100, Ms.primary, Ms.primary),
  ResvMain.home: Tone(Ms.gray600, Ms.gray200, Ms.gray700, Ms.gray600),
  ResvMain.canceled: Tone(Ms.red, Ms.red100, Ms.red, Ms.red),
  ResvMain.noshow: Tone(Ms.red, Ms.red100, Ms.red, Ms.red),
};

// 단계(웹 Phase) — none = 아직
enum Phase { none, waiting, doing, done }

Phase? phaseOfSub(ResvSub? s) => switch (s) {
      ResvSub.waiting => Phase.waiting,
      ResvSub.doing => Phase.doing,
      ResvSub.done => Phase.done,
      null => null,
    };

// 칩 · 점 · 단계 카드 · 글자 색(웹 phaseStyle)
class PhaseStyle {
  final Color chipBg, chipFg; // 칩 · Badge
  final Color dotFill, dotBorder; // 점(테두리 2px 원)
  final Color cardBg, cardBorder; // 내원 현황 단계 카드
  final Color title, sub; // 카드 제목 · 상세 글자
  const PhaseStyle(this.chipBg, this.chipFg, this.dotFill, this.dotBorder, this.cardBg, this.cardBorder, this.title, this.sub);
}

PhaseStyle phaseStyle(ResvMain main, Phase phase) {
  final t = mainTone[main]!;
  return switch (phase) {
    Phase.waiting => PhaseStyle(t.soft, t.text, Ms.white, t.border, t.soft, t.border, t.text, Ms.gray600),
    Phase.doing => PhaseStyle(t.fill, Ms.white, Ms.white, Ms.white, t.fill, t.border, Ms.white, Ms.white),
    Phase.done => const PhaseStyle(Ms.gray100, Ms.gray500, Ms.gray400, Ms.gray400, Ms.white, Ms.gray300, Ms.gray500, Ms.gray500),
    Phase.none => const PhaseStyle(Ms.gray100, Ms.gray500, Ms.white, Ms.gray300, Ms.white, Ms.gray300, Ms.gray400, Ms.gray400),
  };
}

// 카드 왼쪽 막대(웹 barStyle) — 귀가 대기 gray-600 / 완료 gray-300 · 부도 = 흰 바탕 + 빨강 외곽선
class Bar {
  final Color color;
  final Color? outline;
  const Bar(this.color, {this.outline});
}

Bar barOf(ResvMain main, ResvSub? sub) => switch (main) {
      ResvMain.home => Bar(sub == ResvSub.done ? Ms.gray300 : Ms.gray600),
      ResvMain.noshow => const Bar(Ms.white, outline: Ms.red),
      _ => Bar(mainTone[main]!.fill),
    };

// 상세 머리(웹 headOf) — 바탕 · 글자 · 제목
class Head {
  final Color bg, fg;
  final Color? outline;
  final String title;
  const Head(this.bg, this.fg, this.title, {this.outline});
}

Head headOf(ResvMain main, ResvSub? sub) {
  final s = sub != null ? subName[sub]! : '';
  return switch (main) {
    ResvMain.reserved => const Head(Ms.purple, Ms.white, '접수 전'),
    ResvMain.reception => const Head(Ms.yellow, Ms.gray800, '접수 완료'),
    ResvMain.consultation => Head(Ms.cons, Ms.white, '상담 ${s.isEmpty ? '대기' : s}'),
    ResvMain.procedure => Head(Ms.primary, Ms.white, '시술 ${s.isEmpty ? '대기' : s}'),
    ResvMain.home => Head(sub == ResvSub.done ? Ms.gray400 : Ms.gray600, Ms.white, '귀가 ${sub == ResvSub.done ? '완료' : '대기'}'),
    ResvMain.canceled => const Head(Ms.red, Ms.white, '예약 취소'),
    ResvMain.noshow => const Head(Ms.white, Ms.red, '예약 부도', outline: Ms.red),
  };
}

// 범례 Badge 7(웹 LEGEND) — 바탕 · 글자 · 외곽선
class LegendItem {
  final ResvMain main;
  final Color bg, fg;
  final Color? outline;
  const LegendItem(this.main, this.bg, this.fg, {this.outline});
}

const legend = [
  LegendItem(ResvMain.reserved, Ms.purple100, Ms.purple),
  LegendItem(ResvMain.reception, Ms.yellow100, Ms.yellow),
  LegendItem(ResvMain.consultation, Ms.cons100, Ms.cons),
  LegendItem(ResvMain.procedure, Ms.primary100, Ms.primary),
  LegendItem(ResvMain.home, Ms.gray200, Ms.gray800),
  LegendItem(ResvMain.canceled, Ms.red100, Ms.red),
  LegendItem(ResvMain.noshow, Ms.white, Ms.red, outline: Ms.red),
];

// 칩 하나(바탕 · 글자 · 이름)
class ChipLook {
  final Color bg, fg;
  final String text;
  const ChipLook(this.bg, this.fg, this.text);
}

// ─── 시술 현황(SPEC-003 §5.14 · 웹 procedures/view.ts) — 스냅샷 state 셋을 주 · 부상태로
(ResvMain, ResvSub) visitState2(String state) => switch (state) {
      'doing' => (ResvMain.procedure, ResvSub.doing),
      'home' => (ResvMain.home, ResvSub.waiting),
      _ => (ResvMain.procedure, ResvSub.waiting),
    };

// 카드 상태 Badge(점 없음 · 칩 색) — 「시술 · 대기」 · 「시술 · 진행」 · 「귀가 · 대기」
ChipLook visitBadge(String state) {
  final (m, s) = visitState2(state);
  final p = phaseStyle(m, phaseOfSub(s)!);
  return ChipLook(p.chipBg, p.chipFg, stateText(m, s));
}

// 시술 줄 부상태 칩 — 주 상태는 늘 「시술」 · 완료 = 회색
ChipLook procChip(String procState) {
  final sub = switch (procState) {
    'doing' => ResvSub.doing,
    'done' => ResvSub.done,
    _ => ResvSub.waiting,
  };
  final p = phaseStyle(ResvMain.procedure, phaseOfSub(sub)!);
  return ChipLook(p.chipBg, p.chipFg, subName[sub]!);
}

// 예약 · 내원 현황 칩 — 부상태가 있으면 그 단계 색 · 없으면 범례 색
ChipLook resvChip(ResvMain main, ResvSub? sub) {
  final ph = phaseOfSub(sub);
  if (ph != null && !isClosed(main)) {
    final p = phaseStyle(main, ph);
    return ChipLook(p.chipBg, p.chipFg, stateText(main, sub));
  }
  final l = legend.firstWhere((x) => x.main == main);
  return ChipLook(l.bg, l.fg, stateText(main, sub));
}
