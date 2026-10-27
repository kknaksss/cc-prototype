// 예약 현황 응답(SPEC-005 §7.2 · §7.3 — back schemas/reservations.py 필드 이름 그대로). 모르는 필드는 무시 · 빠지면 기본값
import '../view/state.dart';
import 'board.dart' show Json;

Json _o(Object? v) => v is Map ? v.cast<String, dynamic>() : const {};
Json? _on(Object? v) => v is Map ? v.cast<String, dynamic>() : null;
List<T> _l<T>(Object? v, T Function(Json) f) => v is List ? v.whereType<Map>().map((e) => f(e.cast<String, dynamic>())).toList() : <T>[];
String? _s(Object? v) => v is String ? v : null;
int? _i(Object? v) => v is num ? v.toInt() : null;
num? _n(Object? v) => v is num ? v : null;
bool _b(Object? v) => v == true;

class ResvState {
  final ResvMain main;
  final ResvSub? sub;
  const ResvState(this.main, this.sub);
  factory ResvState.fromJson(Object? v) {
    final j = _o(v);
    return ResvState(resvMainOf(j['main']) ?? ResvMain.reserved, resvSubOf(j['sub']));
  }
  String get text => stateText(main, sub);
}

class Zone {
  final int zoneId;
  final String title;
  final int order;
  const Zone(this.zoneId, this.title, this.order);
  factory Zone.fromJson(Json j) => Zone(_i(j['zoneId']) ?? 0, _s(j['title']) ?? '', _i(j['order']) ?? 0);
}

class Span {
  final String start, end; // HH:MM
  const Span(this.start, this.end);
  factory Span.fromJson(Json j) => Span(_s(j['start']) ?? '00:00', _s(j['end']) ?? '00:00');
}

class ResvColumn {
  final int? groupId;
  final String title;
  final int order;
  final int intervalMinutes;
  final int count;
  final List<(int zoneId, int capacity)> capacities;
  final List<Span> open;
  const ResvColumn({this.groupId, required this.title, this.order = 0, this.intervalMinutes = 30, this.count = 0, this.capacities = const [], this.open = const []});
  factory ResvColumn.fromJson(Json j) => ResvColumn(
        groupId: _i(j['groupId']),
        title: _s(j['title']) ?? '',
        order: _i(j['order']) ?? 0,
        intervalMinutes: _i(j['intervalMinutes']) ?? 30,
        count: _i(j['count']) ?? 0,
        capacities: _l(j['capacities'], (c) => (_i(c['zoneId']) ?? 0, _i(c['capacity']) ?? 0)),
        open: _l(j['open'], Span.fromJson),
      );
}

class CardCustomer {
  final int? customerId;
  final String name;
  final String? phoneticName;
  final String? gender; // MALE | FEMALE
  final String? nationality;
  final bool isNew;
  const CardCustomer({this.customerId, required this.name, this.phoneticName, this.gender, this.nationality, this.isNew = false});
  factory CardCustomer.fromJson(Object? v) {
    final j = _o(v);
    return CardCustomer(
      customerId: _i(j['customerId']),
      name: _s(j['name']) ?? '',
      phoneticName: _s(j['phoneticName']),
      gender: _s(j['gender']),
      nationality: _s(j['nationality']),
      isNew: _b(j['isNew']),
    );
  }
}

class ResvCard {
  final int reservationId;
  final int? groupId;
  final int? zoneId;
  final String start, end;
  final CardCustomer customer;
  final ResvState state;
  final int paymentRequiredCount;
  const ResvCard({required this.reservationId, this.groupId, this.zoneId, required this.start, required this.end, required this.customer, required this.state, this.paymentRequiredCount = 0});
  factory ResvCard.fromJson(Json j) => ResvCard(
        reservationId: _i(j['reservationId']) ?? 0,
        groupId: _i(j['groupId']),
        zoneId: _i(j['zoneId']),
        start: _s(j['start']) ?? '',
        end: _s(j['end']) ?? '',
        customer: CardCustomer.fromJson(j['customer']),
        state: ResvState.fromJson(j['state']),
        paymentRequiredCount: _i(j['paymentRequiredCount']) ?? 0,
      );
}

class Amount {
  final num? total, paid;
  final String? currency;
  const Amount(this.total, this.paid, this.currency);
  static Amount? fromJson(Object? v) {
    final j = _on(v);
    return j == null ? null : Amount(_n(j['total']), _n(j['paid']), _s(j['currency']));
  }
}

class ClinicItem {
  final int reservationId;
  final int? zoneId;
  final String name;
  final String? phoneticName;
  final String? nationality;
  final ResvState state;
  final String? receptionAt;
  final int paymentRequiredCount;
  final Amount? amount;
  const ClinicItem({required this.reservationId, this.zoneId, required this.name, this.phoneticName, this.nationality, required this.state, this.receptionAt, this.paymentRequiredCount = 0, this.amount});
  factory ClinicItem.fromJson(Json j) {
    final c = _o(j['customer']);
    return ClinicItem(
      reservationId: _i(j['reservationId']) ?? 0,
      zoneId: _i(j['zoneId']),
      name: _s(c['name']) ?? '',
      phoneticName: _s(c['phoneticName']),
      nationality: _s(c['nationality']),
      state: ResvState.fromJson(j['state']),
      receptionAt: _s(j['receptionAt']),
      paymentRequiredCount: _i(j['paymentRequiredCount']) ?? 0,
      amount: Amount.fromJson(j['amount']),
    );
  }
}

class Clinic {
  final Map<String, int> counts; // all · reception · consultation · procedure · home
  final List<ClinicItem> items;
  const Clinic(this.counts, this.items);
  static Clinic? fromJson(Object? v) {
    final j = _on(v);
    if (j == null) return null;
    final c = _o(j['counts']);
    return Clinic({for (final e in c.entries) e.key: _i(e.value) ?? 0}, _l(j['items'], ClinicItem.fromJson));
  }
}

class ResvBoard {
  final String date;
  final bool isToday;
  final String now;
  final Span? axis;
  final List<Zone> zones;
  final List<ResvColumn> columns;
  final List<ResvCard> cards;
  final Map<String, int> counts;
  final Clinic? clinic;
  const ResvBoard({required this.date, this.isToday = false, this.now = '', this.axis, this.zones = const [], this.columns = const [], this.cards = const [], this.counts = const {}, this.clinic});
  factory ResvBoard.fromJson(Json j) => ResvBoard(
        date: _s(j['date']) ?? '',
        isToday: _b(j['isToday']),
        now: _s(j['now']) ?? '',
        axis: _on(j['axis']) == null ? null : Span.fromJson(_o(j['axis'])),
        zones: _l(j['zones'], Zone.fromJson)..sort((a, b) => a.order.compareTo(b.order)),
        columns: _l(j['columns'], ResvColumn.fromJson)..sort((a, b) => a.order.compareTo(b.order)),
        cards: _l(j['cards'], ResvCard.fromJson),
        counts: {for (final e in _o(j['counts']).entries) e.key: _i(e.value) ?? 0},
        clinic: Clinic.fromJson(j['clinic']),
      );
}

// ─── §7.3 예약 상세
class Phone {
  final String? countryCode, number;
  const Phone(this.countryCode, this.number);
  static Phone? fromJson(Object? v) {
    final j = _on(v);
    return j == null ? null : Phone(_s(j['countryCode']), _s(j['number']));
  }
}

class Personal {
  final Json raw; // 저장할 때 키 그대로 다시 보낸다
  const Personal(this.raw);
  String? s(String k) => _s(raw[k]);
  Phone? get phone => Phone.fromJson(raw['phone']);
  Json get address => _o(raw['address']);
  Json get sns => _o(raw['sns']);
}

class IdentityField {
  final String key, label;
  final bool filled;
  const IdentityField(this.key, this.label, this.filled);
  factory IdentityField.fromJson(Json j) => IdentityField(_s(j['key']) ?? '', _s(j['label']) ?? '', _b(j['filled']));
}

class Identity {
  final String status; // confirmed | unconfirmed
  final String? checkedAt, checkedBy, method, device;
  final int? photoId;
  final String kind; // foreign | domestic
  final List<IdentityField> fields;
  final bool complete;
  const Identity({this.status = 'unconfirmed', this.checkedAt, this.checkedBy, this.method, this.device, this.photoId, this.kind = 'foreign', this.fields = const [], this.complete = false});
  factory Identity.fromJson(Object? v) {
    final j = _o(v);
    return Identity(
      status: _s(j['status']) ?? 'unconfirmed',
      checkedAt: _s(j['checkedAt']),
      checkedBy: _s(j['checkedBy']),
      method: _s(j['method']),
      device: _s(j['device']),
      photoId: _i(j['photoId']),
      kind: _s(j['kind']) ?? 'foreign',
      fields: _l(j['fields'], IdentityField.fromJson),
      complete: _b(j['complete']),
    );
  }
}

class DetailCustomer {
  final int customerId;
  final String name;
  final String? phoneticName, gender, nationality, chartNumber, remark, personalError;
  final bool isNew;
  final int? age;
  final Personal? personal;
  final Identity identity;
  const DetailCustomer({required this.customerId, required this.name, this.phoneticName, this.gender, this.nationality, this.chartNumber, this.remark, this.personalError, this.isNew = false, this.age, this.personal, required this.identity});
  factory DetailCustomer.fromJson(Object? v) {
    final j = _o(v);
    return DetailCustomer(
      customerId: _i(j['customerId']) ?? 0,
      name: _s(j['name']) ?? '',
      phoneticName: _s(j['phoneticName']),
      gender: _s(j['gender']),
      nationality: _s(j['nationality']),
      chartNumber: _s(j['chartNumber']),
      remark: _s(j['remark']),
      personalError: _s(j['personalError']),
      isNew: _b(j['isNew']),
      age: _i(j['age']),
      personal: _on(j['personal']) == null ? null : Personal(_o(j['personal'])),
      identity: Identity.fromJson(j['identity']),
    );
  }
}

class HealthItem {
  final String title;
  final String? answer, memo;
  final bool needsCheck, empty;
  const HealthItem(this.title, this.answer, this.memo, this.needsCheck, this.empty);
  factory HealthItem.fromJson(Json j) => HealthItem(_s(j['title']) ?? '', _s(j['answer']), _s(j['memo']), _b(j['needsCheck']), _b(j['empty']));
}

class PrevVisit {
  final String date;
  final String? start, resultRaw, zoneTitle, groupTitle, reservationMemo, consultationMemo;
  final String result; // completed | noshow | canceled | other
  final List<String> procedures;
  const PrevVisit({required this.date, this.start, this.resultRaw, this.zoneTitle, this.groupTitle, this.reservationMemo, this.consultationMemo, this.result = 'other', this.procedures = const []});
  factory PrevVisit.fromJson(Json j) => PrevVisit(
        date: _s(j['date']) ?? '',
        start: _s(j['start']),
        resultRaw: _s(j['resultRaw']),
        zoneTitle: _s(j['zoneTitle']),
        groupTitle: _s(j['groupTitle']),
        reservationMemo: _s(j['reservationMemo']),
        consultationMemo: _s(j['consultationMemo']),
        result: _s(j['result']) ?? 'other',
        procedures: _l(j['procedures'], (p) => _s(p['title']) ?? ''),
      );
}

class Consultation {
  final String state; // none | waiting | doing | done
  final int? counselorId;
  final String? counselorName, since, calledAt, calledBy;
  const Consultation({this.state = 'none', this.counselorId, this.counselorName, this.since, this.calledAt, this.calledBy});
  static Consultation? fromJson(Object? v) {
    final j = _on(v);
    if (j == null) return null;
    final c = _on(j['counselor']);
    return Consultation(
      state: _s(j['state']) ?? 'none',
      counselorId: _i(c?['staffId']),
      counselorName: _s(c?['name']),
      since: _s(j['since']),
      calledAt: _s(j['calledAt']),
      calledBy: _s(j['calledBy']),
    );
  }
}

class Flow {
  final String? receptionAt, roomTitle, receptionBy;
  final Consultation? consultation;
  final String procedure; // none | waiting | doing | done
  final String home; // none | waiting | done
  final String? tCons, tProc, tHome;
  const Flow({this.receptionAt, this.roomTitle, this.receptionBy, this.consultation, this.procedure = 'none', this.home = 'none', this.tCons, this.tProc, this.tHome});
  static Flow? fromJson(Object? v) {
    final j = _on(v);
    if (j == null) return null;
    final st = _o(j['stages']);
    final t = _o(j['times']);
    return Flow(
      receptionAt: _s(j['receptionAt']),
      roomTitle: _s(j['roomTitle']),
      receptionBy: _s(j['receptionBy']),
      consultation: Consultation.fromJson(j['consultation']),
      procedure: _s(st['procedure']) ?? 'none',
      home: _s(st['home']) ?? 'none',
      tCons: _s(t['consultation']),
      tProc: _s(t['procedure']),
      tHome: _s(t['home']),
    );
  }
}

class Settlement {
  final int paymentRequiredCount, prescriptionCount;
  final Amount? amount;
  const Settlement(this.paymentRequiredCount, this.prescriptionCount, this.amount);
  static Settlement? fromJson(Object? v) {
    final j = _on(v);
    return j == null ? null : Settlement(_i(j['paymentRequiredCount']) ?? 0, _i(j['prescriptionCount']) ?? 0, Amount.fromJson(j['amount']));
  }
}

class RoomItem {
  final int roomId;
  final String title;
  final bool busy, selected;
  const RoomItem(this.roomId, this.title, this.busy, this.selected);
  factory RoomItem.fromJson(Json j) => RoomItem(_i(j['roomId']) ?? 0, _s(j['title']) ?? '', _b(j['busy']), _b(j['selected']));
}

class CounselorItem {
  final int staffId;
  final String name;
  final String? busyRoom;
  const CounselorItem(this.staffId, this.name, this.busyRoom);
  factory CounselorItem.fromJson(Json j) => CounselorItem(_i(j['staffId']) ?? 0, _s(j['name']) ?? '', _s(j['busyRoom']));
}

class DisplayItem {
  final int id;
  final String kind, status;
  final String? deviceName, closedAt;
  final String createdAt;
  const DisplayItem(this.id, this.kind, this.status, this.deviceName, this.createdAt, this.closedAt);
  factory DisplayItem.fromJson(Json j) =>
      DisplayItem(_i(j['id']) ?? 0, _s(j['kind']) ?? '', _s(j['status']) ?? '', _s(j['deviceName']), _s(j['createdAt']) ?? '', _s(j['closedAt']));
}

class ResvDetail {
  final int reservationId;
  final String day;
  final String? start, end, groupTitle, zoneTitle;
  final ResvState state;
  final DetailCustomer customer;
  final bool sedationRequired;
  final String? memo, funnel, counselorName;
  final List<String> doctors;
  final String healthState; // none | ok | error
  final String? healthSubmittedAt;
  final List<HealthItem> health;
  final List<PrevVisit> previousVisits;
  final Flow? flow;
  final Settlement? settlement;
  final List<RoomItem> rooms;
  final bool roomLocked;
  final String? receiveMode; // new | resume
  final List<CounselorItem> counselors;
  final Map<String, bool> can;
  final List<DisplayItem> displays;
  const ResvDetail({
    required this.reservationId,
    required this.day,
    this.start,
    this.end,
    this.groupTitle,
    this.zoneTitle,
    required this.state,
    required this.customer,
    this.sedationRequired = false,
    this.memo,
    this.funnel,
    this.counselorName,
    this.doctors = const [],
    this.healthState = 'none',
    this.healthSubmittedAt,
    this.health = const [],
    this.previousVisits = const [],
    this.flow,
    this.settlement,
    this.rooms = const [],
    this.roomLocked = false,
    this.receiveMode,
    this.counselors = const [],
    this.can = const {},
    this.displays = const [],
  });

  bool canDo(String k) => can[k] == true;

  factory ResvDetail.fromJson(Json j) {
    final r = _o(j['reservation']);
    final f = _on(r['funnel']);
    final h = _o(j['health']);
    return ResvDetail(
      reservationId: _i(j['reservationId']) ?? 0,
      day: _s(j['day']) ?? '',
      start: _s(j['start']),
      end: _s(j['end']),
      groupTitle: _s(j['groupTitle']),
      zoneTitle: _s(j['zoneTitle']),
      state: ResvState.fromJson(j['state']),
      customer: DetailCustomer.fromJson(j['customer']),
      sedationRequired: _b(r['sedationRequired']),
      memo: _s(r['memo']),
      funnel: f == null ? null : [_s(f['name']), _s(f['detail'])].whereType<String>().where((x) => x.isNotEmpty).join(' · '),
      counselorName: _s(_on(r['counselor'])?['name']),
      doctors: _l(r['doctors'], (d) => _s(d['name']) ?? ''),
      healthState: _s(h['state']) ?? 'none',
      healthSubmittedAt: _s(h['submittedAt']),
      health: _l(h['items'], HealthItem.fromJson),
      previousVisits: _l(j['previousVisits'], PrevVisit.fromJson),
      flow: Flow.fromJson(j['flow']),
      settlement: Settlement.fromJson(j['settlement']),
      rooms: _l(j['rooms'], RoomItem.fromJson),
      roomLocked: _b(j['roomLocked']),
      receiveMode: _s(j['receiveMode']),
      counselors: _l(j['counselors'], CounselorItem.fromJson),
      can: {for (final e in _o(j['can']).entries) e.key: e.value == true},
      displays: _l(j['displays'], DisplayItem.fromJson),
    );
  }
}

// 띄우기 대상 기기(§5-3 targets)
class DisplayTarget {
  final int deviceId;
  final String name, kind;
  final String? lastSeenAt;
  final bool online;
  const DisplayTarget(this.deviceId, this.name, this.kind, this.lastSeenAt, this.online);
  factory DisplayTarget.fromJson(Json j) =>
      DisplayTarget(_i(j['deviceId']) ?? 0, _s(j['name']) ?? '', _s(j['kind']) ?? 'tablet', _s(j['lastSeenAt']), _b(j['online']));
}
