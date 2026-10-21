import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/model/board.dart';
import 'package:procedure_app/view/time.dart';
import 'package:procedure_app/view/view.dart';

import 'fixture.dart';

void main() {
  final b = board();
  Procedure p(Map<String, dynamic> j) => Procedure.fromJson(j);

  group('procLine — 웹 view.ts 와 같은 입력 → 같은 문구', () {
    test('완료', () {
      expect(procLine(b, p(proc(1, 'done', doctor: {'id': 1, 'name': '가 원장'}, started: '2026-10-21T09:00:00+09:00', completed: '2026-10-21T09:20:00+09:00'))),
          const ProcLine('가 원장 · 09:00~09:20', LineTone.muted));
    });
    test('진행', () {
      expect(procLine(b, p(proc(1, 'doing', doctor: {'id': 1, 'name': '가 원장'}, started: '2026-10-21T00:30:00Z'))),
          const ProcLine('가 원장 · 09:30 시작', LineTone.normal));
    });
    test('수락됨', () {
      final call = {'id': 9, 'kind': 'all', 'targetDoctorId': null, 'createdAt': '', 'acceptedBy': 2, 'acceptedAt': ''};
      expect(procLine(b, p(proc(1, 'wait', call: call))), const ProcLine('나 원장 수락 · 시작 가능', LineTone.accent));
    });
    test('수락 전 — 전체 · 지정', () {
      final all = {'id': 9, 'kind': 'all', 'targetDoctorId': null, 'createdAt': '', 'acceptedBy': null, 'acceptedAt': null};
      final one = {'id': 9, 'kind': 'one', 'targetDoctorId': 1, 'createdAt': '', 'acceptedBy': null, 'acceptedAt': null};
      expect(procLine(b, p(proc(1, 'wait', call: all))).text, '전체 호출 · 수락 전');
      expect(procLine(b, p(proc(1, 'wait', call: one))).text, '가 원장 지정 호출 · 수락 전');
    });
    test('담당 · 미정', () {
      expect(procLine(b, p(proc(1, 'wait', doctor: {'id': 2, 'name': '나 원장'}))).text, '나 원장');
      expect(procLine(b, p(proc(1, 'wait'))), const ProcLine('담당의 미정', LineTone.muted));
    });
  });

  test('시각은 KST', () {
    expect(hm('2026-10-21T01:05:00Z'), '10:05');
    expect(elapsed('2026-10-21T10:00:00+09:00', DateTime.parse('2026-10-21T10:03:07+09:00').millisecondsSinceEpoch), '03:07');
  });

  test('etc(방 배정) 줄은 그리지 않고 진행 막대도 procedure 만 센다', () {
    final c = BoardCard.fromJson(card(1, procs: [
      proc(10, 'done', kind: 'etc', seq: 0, title: '방 배정'),
      proc(11, 'wait', seq: 2, title: 'B'),
      proc(12, 'doing', seq: 1, title: 'A', started: '2026-10-21T09:00:00+09:00'),
      proc(13, 'done', seq: 3, title: 'C', completed: '2026-10-21T09:10:00+09:00'),
    ]));
    expect(orderedProcs(c).map((x) => x.title), ['C', 'A', 'B']);
    final pr = progressOf(c);
    expect(pr.total, 3);
    expect(pr.done, 1);
    expect(pr.next, '다음 B');
  });

  group('나에게 온 호출', () {
    final bb = board(calls: [openCall(1, 1, 'all'), openCall(2, 2, 'one', target: 1), openCall(3, 3, 'one', target: 2)]);
    test('kind=all 또는 내 staffId 지정만', () {
      expect(myCalls(bb, const Me(staffId: 1)).map((k) => k.callId), [1, 2]);
      expect(myCalls(bb, const Me(staffId: 2)).map((k) => k.callId), [1, 3]);
    });
    test('간호사(받는 사람 아님) 없음', () {
      expect(myCalls(bb, Me.none), isEmpty);
    });
    test('관리자 = 모든 호출(전체 · 지정 · A-15)', () {
      expect(myCalls(bb, const Me(admin: true)).map((k) => k.callId), [1, 2, 3]);
      expect(filterCount(FilterId.mine, bb, const Me(admin: true)), 3);
    });
    test('「수락 대기」 칸 수 = 그 호출 수', () {
      expect(filterCount(FilterId.mine, bb, const Me(staffId: 1)), 2);
    });
  });

  test('필터 칸 = 웹 filterFn · 수는 counts', () {
    final bb = board(cards: [card(1, need: {'why': 'call', 'since': '2026-10-21T09:50:00+09:00', 'limitMin': 5}), card(2, state: 'doing'), card(3, state: 'home')],
        calls: [openCall(1, 1, 'all')]);
    List<int> ids(FilterId f) => bb.cards.where(filterFn(f, bb, Me.none)).map((c) => c.visitId).toList();
    expect(ids(FilterId.need), [1]);
    expect(ids(FilterId.call), [1]);
    expect(ids(FilterId.doing), [2]);
    expect(ids(FilterId.waiting), [1]);
    expect(filterCount(FilterId.need, bb, Me.none), 1); // counts.need 그대로
  });

  test('카드 순서 — 입실순 · 귀가 대기는 맨 뒤', () {
    final cs = [
      BoardCard.fromJson(card(1, state: 'home', inAt: '2026-10-21T08:00:00+09:00', homeAt: '2026-10-21T09:00:00+09:00')),
      BoardCard.fromJson(card(2, inAt: '2026-10-21T09:30:00+09:00')),
      BoardCard.fromJson(card(3, inAt: '2026-10-21T09:00:00+09:00')),
    ];
    expect(orderedCards(cs).map((c) => c.visitId), [3, 2, 1]);
  });

  test('카드 배지 — 확인 필요 > 귀가 대기 > 마취 중 > 상태', () {
    final bb = board(calls: [openCall(1, 1, 'one', target: 1)]);
    expect(cardBadge(bb, BoardCard.fromJson(card(1, need: {'why': 'call', 'since': '', 'limitMin': 5}))).text, '가 원장 지정 호출 · 수락 전');
    expect(cardBadge(bb, BoardCard.fromJson(card(2, anesSince: '2026-10-21T09:50:00+09:00'))).variant, BadgeVariant.purple);
    expect(cardBadge(bb, BoardCard.fromJson(card(3, state: 'doing'))).text, '시술 진행');
    // E2E A6 — 귀가 대기 전 확인 필요는 짧게
    expect(cardBadge(bb, BoardCard.fromJson(card(4, need: {'why': 'home', 'since': '', 'limitMin': 0}))).text, '시술 완료');
  });

  test('모르는 필드 · 빠진 필드가 있어도 읽힌다', () {
    final bb = Board.fromJson({'now': 'x', 'cards': [{'visitId': 1}]});
    expect(bb.cards.single.procedures, isEmpty);
    expect(bb.counts.all, 0);
  });
}
