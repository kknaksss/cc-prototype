// 표시 매핑 — 웹 components/procedures/view.ts 를 Dart 로(SPEC-004 §6.0 · 리포트 §7-1).
// 규칙(pickable · canStart · canCall · need · counts …)은 back 스냅샷 값을 그대로 쓴다. 여기는 문구 · 순서 · 고르기만.
import 'dart:ui' show Color;

import '../model/board.dart';
import '../theme/tokens.dart';
import 'state.dart';
import 'time.dart';

export 'state.dart' show ChipLook;

enum BadgeVariant { neutral, primary, warning, danger, purple }


// 필터 6칸(웹과 같음 · 겹쳐 셈) + 의사 계정만 「수락 대기」
enum FilterId { all, need, waiting, anes, call, doing, home, mine }

const filterName = {
  FilterId.all: '전체',
  FilterId.need: '확인',
  FilterId.waiting: '대기',
  FilterId.anes: '마취',
  FilterId.call: '호출',
  FilterId.doing: '진행',
  FilterId.home: '귀가',
  FilterId.mine: '수락 대기',
};

// 칸 점(웹 FILTERS) — fill · 테두리(○). 수락 대기는 점 없음(앱 칸)
class Dot {
  final Color fill;
  final Color? ring;
  const Dot(this.fill, [this.ring]);
}

final filterDot = <FilterId, Dot>{
  FilterId.all: const Dot(Ms.gray300),
  FilterId.need: const Dot(Ms.red),
  FilterId.waiting: Dot(phaseStyle(ResvMain.procedure, Phase.waiting).dotFill, phaseStyle(ResvMain.procedure, Phase.waiting).dotBorder),
  FilterId.anes: const Dot(Ms.purple),
  FilterId.call: const Dot(Ms.primary500),
  FilterId.doing: const Dot(Ms.primary),
  FilterId.home: Dot(phaseStyle(ResvMain.home, Phase.waiting).dotFill, phaseStyle(ResvMain.home, Phase.waiting).dotBorder),
};

int filterCount(FilterId id, Board b, Me me) => switch (id) {
      FilterId.all => b.counts.all,
      FilterId.need => b.counts.need,
      FilterId.waiting => b.counts.waiting,
      FilterId.anes => b.counts.anes,
      FilterId.call => b.counts.call,
      FilterId.doing => b.counts.doing,
      // 스냅샷 counts 에 귀가 칸이 없다 — 판의 귀가 대기 카드 수(웹 E2E-9: 귀가 대기는 흐리게 남고 「전체」에 들어감)
      FilterId.home => b.cards.where((c) => c.state == 'home').length,
      FilterId.mine => myCalls(b, me).length,
    };

// 칸 정의(SPEC-003 §6.4 · 웹 filterFn) — 확인 = need · 마취 = 진행 중 마취 · 호출 = calls 에 그 고객이 있음
bool Function(BoardCard) filterFn(FilterId id, Board b, Me me) => switch (id) {
      FilterId.need => (c) => c.need != null,
      FilterId.waiting => (c) => c.state == 'waiting',
      FilterId.anes => (c) => c.state != 'home' && c.anesthesia.runningSince != null,
      FilterId.call => (c) => c.state != 'home' && b.calls.any((k) => k.visitId == c.visitId),
      FilterId.doing => (c) => c.state == 'doing',
      FilterId.home => (c) => c.state == 'home',
      FilterId.mine => (c) => myCalls(b, me).any((k) => k.visitId == c.visitId),
      FilterId.all => (_) => true,
    };

String docName(Board b, int? id) {
  if (id == null) return '';
  for (final d in b.doctors) {
    if (d.id == id) return d.name;
  }
  return '';
}

// 카드 순서 = 스냅샷 cards[] 순서 그대로(웹 드래그 공유 순서 · back 이 정렬 — 귀가 대기 맨 뒤 포함). 앱은 정렬하지 않는다(§6.2 · D7-21)
List<BoardCard> orderedCards(List<BoardCard> cards) => cards;

// 보이는 작업 = 「방 배정」(isRoomTask)만 뺀 전부 — type(PROCEDURE · ETCETERA) 무관 같은 시술 줄(§6.0 · 웹 procsOf)
List<Procedure> procsOnly(BoardCard c) => c.procedures.where((p) => !p.isRoomTask).toList();

// 시술 표시 순서 — 진행 → 대기(sequence 순) → 완료(완료 시각 순) — 웹 orderedProcs(SPEC-003 §5.9)
List<Procedure> orderedProcs(BoardCard c) {
  final procs = procsOnly(c);
  final done = procs.where((p) => p.state == 'done').toList()
    ..sort((a, b) => (toMs(a.completedAt) ?? 0).compareTo(toMs(b.completedAt) ?? 0));
  final doing = procs.where((p) => p.state == 'doing').toList();
  final wait = procs.where((p) => p.state == 'wait').toList()..sort((a, b) => a.sequence.compareTo(b.sequence));
  return [...doing, ...wait, ...done];
}

String callText(Board b, String kind, int? target) => kind == 'all' ? '전체 호출' : '${docName(b, target)} 지정 호출';

enum LineTone { muted, normal, accent }

class ProcLine {
  final String text;
  final LineTone tone;
  const ProcLine(this.text, this.tone);
  @override
  bool operator ==(Object other) => other is ProcLine && other.text == text && other.tone == tone;
  @override
  int get hashCode => Object.hash(text, tone);
  @override
  String toString() => 'ProcLine($text, $tone)';
}

// 시술 줄 둘째 줄(웹 procLine · SPEC-003 §5.9)
ProcLine procLine(Board b, Procedure p) {
  final who = p.doctor?.name ?? '';
  if (p.state == 'done') {
    final span = '${p.startedAt != null ? hm(p.startedAt) : ''}~${hm(p.completedAt)}';
    return ProcLine((who.isNotEmpty ? '$who · ' : '') + span, LineTone.muted);
  }
  if (p.state == 'doing') return ProcLine('${who.isNotEmpty ? '$who · ' : ''}${hm(p.startedAt)} 시작', LineTone.normal);
  final call = p.call;
  if (call != null && call.acceptedBy != null) {
    final n = docName(b, call.acceptedBy);
    return ProcLine('${n.isNotEmpty ? n : who} 수락 · 시작 가능', LineTone.accent);
  }
  if (call != null) return ProcLine('${callText(b, call.kind, call.targetDoctorId)} · 수락 전', LineTone.normal);
  if (p.doctor != null) return ProcLine(p.doctor!.name, LineTone.normal);
  return const ProcLine('담당의 미정', LineTone.muted);
}

int _created(OpenCall k) => toMs(k.createdAt) ?? 0;

// 그 고객의 받을 호출(이른 순)
List<OpenCall> callsOf(Board b, int visitId) =>
    b.calls.where((k) => k.visitId == visitId).toList()..sort((a, c) => _created(a).compareTo(_created(c)));

OpenCall? firstOpenCall(Board b, int visitId) {
  final l = callsOf(b, visitId);
  return l.isEmpty ? null : l.first;
}

// 받는 사람 — 의사 = 연결 원장 id · 관리자 = 모든 호출(A-15) · 간호사 = 없음
class Me {
  final bool admin;
  final int? staffId; // 의사 계정만
  const Me({this.admin = false, this.staffId});
  static const none = Me();
  bool get receives => admin || staffId != null;
}

// 「나에게 온 호출」(SPEC-004 §6.0) — 의사 = kind=all 또는 targetDoctorId = 내 staffId · 관리자 = calls[] 전부
bool isMine(OpenCall k, Me me) => me.admin || (me.staffId != null && (k.kind == 'all' || k.targetDoctorId == me.staffId));

List<OpenCall> myCalls(Board b, Me me) =>
    !me.receives ? const [] : (b.calls.where((k) => isMine(k, me)).toList()..sort((a, c) => _created(a).compareTo(_created(c))));

// 원장 고르기 목록 — 비어 있는 원장 먼저(웹 호출 탭 · 호출 시트와 같음)
List<Doctor> doctorsFreeFirst(Board b) => [...b.doctors]..sort((x, y) => (x.busy ? 1 : 0) - (y.busy ? 1 : 0));

// 카드 상태 Badge(웹 OrderCard) — 덮어쓰기(확인 필요 danger · 마취 중 purple · 점 있음)가 있으면 그것, 없으면 2계층(점 없음 · §6.9)
class BadgeView {
  final String text;
  final BadgeVariant variant;
  final ChipLook? look; // 2계층 칩 색(덮어쓰기 아닐 때)
  const BadgeView(this.text, this.variant, {this.look});
  bool get dot => look == null;
}

BadgeView cardBadge(Board b, BoardCard c) {
  final home = c.state == 'home';
  final anesOn = c.anesthesia.runningSince != null;
  if (c.need != null) return BadgeView(needState(b, c, c.need!), BadgeVariant.danger);
  if (!home && anesOn) return const BadgeView('마취 중', BadgeVariant.purple);
  final v = visitBadge(c.state);
  return BadgeView(v.text, home ? BadgeVariant.neutral : BadgeVariant.primary, look: v);
}

// 「확인 필요」 배지 문구(웹 needView.state) — 「시술 완료」 배지는 없다(D7-63)
String needState(Board b, BoardCard c, Need need) {
  if (need.why == 'anes') return '마취 중';
  if (need.why == 'call') {
    final k = firstOpenCall(b, c.visitId);
    return '${k != null ? callText(b, k.kind, k.targetDoctorId) : '호출'} · 수락 전';
  }
  return '시술 모두 완료 · 귀가 대기 전';
}

// 카드 「지금」 상자 — 보이는 순서: 귀가 대기 > 진행 > 모두 완료 > 호출 > 마취 > 대기(시안 M9 의 표시 순서만)
enum NowKind { home, doing, allDone, call, anes, wait }

class NowBox {
  final NowKind kind;
  final String title;
  final String sub;
  final String timer;
  final bool red; // 빨강 = back need · long · 호출 기준(limits.callMin) 넘음
  const NowBox(this.kind, this.title, this.sub, this.timer, {this.red = false});
}

NowBox nowBox(Board b, BoardCard c, int now) {
  final procs = procsOnly(c);
  if (c.state == 'home') return NowBox(NowKind.home, '귀가 대기 · ${hm(c.homeAt)}', _lastEnd(procs), '');
  final doing = procs.where((p) => p.state == 'doing').toList();
  if (doing.isNotEmpty) {
    final p = doing.first;
    final who = p.doctor?.name ?? '';
    return NowBox(NowKind.doing, p.title, '${who.isNotEmpty ? '$who · ' : ''}${hm(p.startedAt)} 시작', elapsed(p.startedAt, now));
  }
  if (c.canHome) return NowBox(NowKind.allDone, '시술 모두 완료', _lastEnd(procs), '');
  final k = firstOpenCall(b, c.visitId);
  if (k != null) {
    final m = minutesSince(k.createdAt, now);
    final title = k.kind == 'all' ? '전체 호출 · 수락 대기' : '${docName(b, k.targetDoctorId)} 지정 · 수락 대기';
    return NowBox(NowKind.call, title, k.procedures.map((p) => p.title).join(' · '), '$m분',
        red: b.limits.callMin > 0 && m >= b.limits.callMin);
  }
  if (c.anesthesia.runningSince != null) {
    final m = minutesSince(c.anesthesia.runningSince, now);
    return NowBox(NowKind.anes, '마취 중', '${hm(c.anesthesia.runningSince)} 시작 · 기준 ${b.limits.anesMin}분', '$m분',
        red: c.anesthesia.long);
  }
  final waits = procs.where((p) => p.state == 'wait').toList()..sort((a, b) => a.sequence.compareTo(b.sequence));
  final docs = waits.map((p) => p.doctor?.name).whereType<String>().toSet().toList();
  return NowBox(NowKind.wait, '시술 대기', docs.isEmpty ? '담당의 미정' : '담당 ${docs.join(', ')}', '');
}

String _lastEnd(List<Procedure> procs) {
  final ends = procs.map((p) => toMs(p.completedAt)).whereType<int>().toList();
  if (ends.isEmpty) return '';
  ends.sort();
  return '마지막 종료 ${hmMs(ends.last)}';
}

// 진행 막대 — 시술 수만큼 칸 · 「n / m」 · 「다음 <시술> · <원장>」
class Progress {
  final List<String> steps; // done | doing | wait
  final int done;
  final int total;
  final String next;
  const Progress(this.steps, this.done, this.total, this.next);
}

Progress progressOf(BoardCard c) {
  final ps = orderedProcs(c);
  final waits = ps.where((p) => p.state == 'wait').toList();
  final next = c.state == 'home' || waits.isEmpty
      ? ''
      : '다음 ${waits.first.title}${waits.first.doctor != null ? ' · ${waits.first.doctor!.name}' : ''}';
  return Progress(ps.map((p) => p.state).toList(), ps.where((p) => p.state == 'done').length, ps.length, next);
}

String visitText(bool isNew) => isNew ? '첫내원' : '재내원';

// KOS 반영 표시(SPEC-003 §6.3) — ok 면 없음
String? kosText(KosState k) => switch (k.status) {
      'pending' => 'KOS 반영 중',
      'failed' => 'KOS 반영 실패',
      _ => null,
    };
