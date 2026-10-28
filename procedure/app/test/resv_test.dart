// 예약 현황 표시 계산(SPEC-004 §6.10 ~ §6.12) — 웹 reservations/view.tsx 와 같은 입력 → 같은 글자
import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/model/reservation.dart';
import 'package:procedure_app/screens/visits_screen.dart' show clinicGroups;
import 'package:procedure_app/view/resv_view.dart';
import 'package:procedure_app/view/state.dart';

Map<String, dynamic> resvCard(int id, String start, {int group = 1, String main = 'reserved', String? sub}) => {
      'reservationId': id, 'resourceIndex': 0, 'groupId': group, 'zoneId': 1, 'start': start, 'end': start,
      'customer': {'customerId': id, 'name': '고객$id', 'phoneticName': null, 'gender': 'FEMALE', 'nationality': 'TW', 'isNew': true},
      'state': {'main': main, 'sub': sub}, 'paymentRequiredCount': 0, 'draggable': true,
    };

ResvBoard resvBoard({List<Map<String, dynamic>> cards = const [], bool today = true, Map<String, dynamic>? clinic}) => ResvBoard.fromJson({
      'date': '2026-10-27', 'isToday': today, 'now': '2026-10-27T14:40:00+09:00',
      'axis': {'start': '06:00', 'end': '22:00'},
      'zones': [{'zoneId': 2, 'title': '5층', 'order': 2, 'isDefault': false}, {'zoneId': 1, 'title': '4층', 'order': 1, 'isDefault': true}],
      'columns': [{'groupId': 1, 'title': '국내', 'order': 1, 'intervalMinutes': 30, 'count': 2, 'capacities': [{'zoneId': 2, 'capacity': 2}, {'zoneId': 1, 'capacity': 3}], 'open': []}],
      'cards': cards, 'counts': {'total': cards.length}, 'clinic': clinic, 'unknown': 1,
    });

void main() {
  test('시각 · 날짜 글자(KST)', () {
    expect(kstMin('2026-10-27T05:30:00Z'), 14 * 60 + 30);
    expect(minToHm(9 * 60 + 5), '09:05');
    expect(shiftDate('2026-10-31', 1), '2026-11-01');
    expect(dateTitle('2026-10-26'), '2026. 10. 26. (월)');
  });

  test('금액 · 정원 · 국가', () {
    expect(money(1234567, 'KRW'), '₩1,234,567');
    expect(money(50, 'USD'), '50 USD');
    expect(money(null, 'KRW'), '-');
    final b = resvBoard();
    expect(capacityText(b.columns.single, b.zones), '4층 3명 · 5층 2명'); // 구역 order 순
    expect(nationName('tw'), '대만');
    expect(nationName('XX'), 'XX');
    expect(flagEmoji('KR'), '🇰🇷');
    expect(flagEmoji('XX'), isNull);
  });

  test('폰 시간대 목록 — 30분 · 그 시간대 시작 카드 · 그룹 칩 거르기 · 지금 시간대', () {
    final b = resvBoard(cards: [
      resvCard(1, '2026-10-27T14:00:00+09:00'),
      resvCard(2, '2026-10-27T14:20:00+09:00', group: 2),
      resvCard(3, '2026-10-27T15:00:00+09:00'),
    ]);
    final rows = slotRows(b);
    expect(rows.first.label, '06:00');
    expect(rows.length, 32);
    expect(rows.firstWhere((r) => r.label == '14:00').cards.map((c) => c.reservationId), [1, 2]);
    expect(slotRows(b, filterOn: true, groupFilter: 1).firstWhere((r) => r.label == '14:00').cards.map((c) => c.reservationId), [1]);
    expect(nowSlot(b), 14 * 60 + 30);
    expect(nowSlot(resvBoard(today: false)), isNull);
  });

  test('카드 상태 2계층 읽기', () {
    final c = ResvCard.fromJson(resvCard(1, 'x', main: 'consultation', sub: 'waiting'));
    expect(c.state.main, ResvMain.consultation);
    expect(c.state.text, '상담 · 대기');
  });

  test('내원 현황 — 구역 order 묶음 · 0 명 구역 빼기 · 귀가 대기는 수납 필요 먼저', () {
    Map<String, dynamic> it(int id, int zone, String main, int pay) => {
          'reservationId': id, 'zoneId': zone, 'customer': {'name': 'c$id', 'phoneticName': null, 'nationality': 'KR'},
          'state': {'main': main, 'sub': 'waiting'}, 'receptionAt': null, 'paymentRequiredCount': pay, 'amount': null,
        };
    final b = resvBoard(clinic: {
      'counts': {'all': 4},
      'items': [it(1, 1, 'home', 0), it(2, 1, 'home', 2), it(3, 1, 'reception', 0), it(4, 9, 'home', 0)],
    });
    final all = clinicGroups(b, 'all');
    expect(all.map((g) => g.$1), ['4층', '구역 없음']);
    final home = clinicGroups(b, 'home');
    expect(home.first.$2.map((i) => i.reservationId), [2, 1]);
    expect(clinicGroups(resvBoard(), 'all'), isEmpty);
  });

  test('예약 상세 — can 값 그대로 · 모르는 키 무시', () {
    final d = ResvDetail.fromJson({
      'reservationId': 9, 'day': '2026-10-27', 'state': {'main': 'reception', 'sub': null},
      'customer': {'customerId': 3, 'name': 'A', 'isNew': false, 'identity': {'status': 'confirmed', 'kind': 'foreign', 'fields': [], 'complete': true, 'method': 'app_scan'}},
      'reservation': {'sedationRequired': false, 'memo': 'm', 'doctors': []},
      'health': {'state': 'none', 'items': []}, 'previousVisits': [],
      'can': {'cancel': false, 'discharge': true}, 'rooms': [], 'counselors': [], 'newKey': 1,
    });
    expect(d.canDo('discharge'), isTrue);
    expect(d.canDo('cancel'), isFalse);
    expect(d.canDo('receive'), isFalse);
    expect(d.customer.identity.method, 'app_scan');
    expect(d.displays, isEmpty);
  });
}
