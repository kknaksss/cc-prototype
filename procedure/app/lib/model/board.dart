// 스냅샷 모델 — back `procedure/back/app/schemas/board.py` 와 같은 필드 이름 · null 여부(SPEC-004 §7.2).
// 모르는 필드는 무시한다(back 이 필드를 더해도 앱이 깨지지 않게). 시각은 ISO 8601 문자열 그대로 둔다.

typedef Json = Map<String, dynamic>;

String? _s(Object? v) => v is String ? v : null;
int? _i(Object? v) => v is int ? v : (v is num ? v.toInt() : null);
bool _b(Object? v) => v == true;
Json _o(Object? v) => v is Map ? v.cast<String, dynamic>() : const {};
List<T> _l<T>(Object? v, T Function(Json) f) => v is List ? v.whereType<Map>().map((e) => f(e.cast<String, dynamic>())).toList() : <T>[];

class SyncInfo {
  final String? lastOkAt;
  final String? lastError;
  final bool inWindow;
  const SyncInfo({this.lastOkAt, this.lastError, this.inWindow = false});
  factory SyncInfo.fromJson(Json j) => SyncInfo(lastOkAt: _s(j['lastOkAt']), lastError: _s(j['lastError']), inWindow: _b(j['inWindow']));
}

class Doctor {
  final int id;
  final String name;
  final bool busy;
  final String? busyRoom;
  const Doctor({required this.id, required this.name, this.busy = false, this.busyRoom});
  factory Doctor.fromJson(Json j) =>
      Doctor(id: _i(j['id']) ?? 0, name: _s(j['name']) ?? '', busy: _b(j['busy']), busyRoom: _s(j['busyRoom']));
}

class Counts {
  final int all, need, waiting, anes, call, doing;
  const Counts({this.all = 0, this.need = 0, this.waiting = 0, this.anes = 0, this.call = 0, this.doing = 0});
  factory Counts.fromJson(Json j) => Counts(
        all: _i(j['all']) ?? 0,
        need: _i(j['need']) ?? 0,
        waiting: _i(j['waiting']) ?? 0,
        anes: _i(j['anes']) ?? 0,
        call: _i(j['call']) ?? 0,
        doing: _i(j['doing']) ?? 0,
      );
}

class Limits {
  final int callMin, anesMin;
  const Limits({this.callMin = 0, this.anesMin = 0});
  factory Limits.fromJson(Json j) => Limits(callMin: _i(j['callMin']) ?? 0, anesMin: _i(j['anesMin']) ?? 0);
}

class Room {
  final int id;
  final String title;
  final int order;
  const Room({required this.id, required this.title, this.order = 0});
  factory Room.fromJson(Json j) => Room(id: _i(j['id']) ?? 0, title: _s(j['title']) ?? '', order: _i(j['order']) ?? 0);
}

class Customer {
  final String name;
  final String? phoneticName;
  final String? nationality;
  final bool isNew;
  final String? chartNumber;
  const Customer({required this.name, this.phoneticName, this.nationality, this.isNew = false, this.chartNumber});
  factory Customer.fromJson(Json j) => Customer(
        name: _s(j['name']) ?? '',
        phoneticName: _s(j['phoneticName']),
        nationality: _s(j['nationality']),
        isNew: _b(j['isNew']),
        chartNumber: _s(j['chartNumber']),
      );
}

class Anesthesia {
  final String? runningSince;
  final int? lastMinutes;
  final bool long;
  final bool canStart;
  final bool canEnd;
  const Anesthesia({this.runningSince, this.lastMinutes, this.long = false, this.canStart = false, this.canEnd = false});
  factory Anesthesia.fromJson(Json j) => Anesthesia(
        runningSince: _s(j['runningSince']),
        lastMinutes: _i(j['lastMinutes']),
        long: _b(j['long']),
        canStart: _b(j['canStart']),
        canEnd: _b(j['canEnd']),
      );
}

class DoctorRef {
  final int id;
  final String name;
  const DoctorRef({required this.id, required this.name});
  static DoctorRef? fromJson(Object? v) {
    if (v is! Map) return null;
    final j = v.cast<String, dynamic>();
    return DoctorRef(id: _i(j['id']) ?? 0, name: _s(j['name']) ?? '');
  }
}

class ProcCall {
  final int id;
  final String kind; // all | one
  final int? targetDoctorId;
  final String createdAt;
  final int? acceptedBy;
  final String? acceptedAt;
  const ProcCall({required this.id, required this.kind, this.targetDoctorId, required this.createdAt, this.acceptedBy, this.acceptedAt});
  static ProcCall? fromJson(Object? v) {
    if (v is! Map) return null;
    final j = v.cast<String, dynamic>();
    return ProcCall(
      id: _i(j['id']) ?? 0,
      kind: _s(j['kind']) ?? 'all',
      targetDoctorId: _i(j['targetDoctorId']),
      createdAt: _s(j['createdAt']) ?? '',
      acceptedBy: _i(j['acceptedBy']),
      acceptedAt: _s(j['acceptedAt']),
    );
  }
}

class Procedure {
  final int id;
  final String kind; // procedure | etc
  final int sequence;
  final String title;
  final String state; // wait | doing | done
  final String? kosStatus;
  final String? startedAt;
  final String? completedAt;
  final DoctorRef? doctor;
  final ProcCall? call;
  final bool pickable;
  final bool canStart;
  final bool canFinish;
  final bool isRoomTask; // 「방 배정」 — 앱은 그리지 않는다(§6.0 · 스냅샷 값)
  final bool canUndoStart; // [시작] 되돌리기(§6.3 #4 · SPEC-003 §5.13)
  final bool canUndoFinish;
  const Procedure({
    required this.id,
    this.kind = 'procedure',
    this.sequence = 0,
    required this.title,
    required this.state,
    this.kosStatus,
    this.startedAt,
    this.completedAt,
    this.doctor,
    this.call,
    this.pickable = false,
    this.canStart = false,
    this.canFinish = false,
    this.isRoomTask = false,
    this.canUndoStart = false,
    this.canUndoFinish = false,
  });
  bool get isEtc => kind == 'etc';
  factory Procedure.fromJson(Json j) => Procedure(
        id: _i(j['id']) ?? 0,
        kind: _s(j['kind']) ?? 'procedure',
        sequence: _i(j['sequence']) ?? 0,
        title: _s(j['title']) ?? '',
        state: _s(j['state']) ?? 'wait',
        kosStatus: _s(j['kosStatus']),
        startedAt: _s(j['startedAt']),
        completedAt: _s(j['completedAt']),
        doctor: DoctorRef.fromJson(j['doctor']),
        call: ProcCall.fromJson(j['call']),
        pickable: _b(j['pickable']),
        canStart: _b(j['canStart']),
        canFinish: _b(j['canFinish']),
        isRoomTask: _b(j['isRoomTask']),
        canUndoStart: _b(j['canUndoStart']),
        canUndoFinish: _b(j['canUndoFinish']),
      );
}

class Need {
  final String why; // home | anes | call
  final String since;
  final int limitMin;
  const Need({required this.why, required this.since, this.limitMin = 0});
  static Need? fromJson(Object? v) {
    if (v is! Map) return null;
    final j = v.cast<String, dynamic>();
    return Need(why: _s(j['why']) ?? 'call', since: _s(j['since']) ?? '', limitMin: _i(j['limitMin']) ?? 0);
  }
}

class KosFailure {
  final String op;
  final String? error;
  const KosFailure({required this.op, this.error});
  factory KosFailure.fromJson(Json j) => KosFailure(op: _s(j['op']) ?? '', error: _s(j['error']));
}

class KosState {
  final String status; // ok | pending | failed
  final List<KosFailure> failed;
  const KosState({this.status = 'ok', this.failed = const []});
  factory KosState.fromJson(Json j) => KosState(status: _s(j['status']) ?? 'ok', failed: _l(j['failed'], KosFailure.fromJson));
}

class BoardCard {
  final int visitId;
  final Room room;
  final String? inAt;
  final String? homeAt;
  final Customer customer;
  final String state; // waiting | doing | home
  final bool paymentRequired;
  final String? orderMemo;
  final Anesthesia anesthesia;
  final List<Procedure> procedures;
  final bool canCall;
  final bool canHome;
  final Need? need;
  final KosState kos;
  const BoardCard({
    required this.visitId,
    required this.room,
    this.inAt,
    this.homeAt,
    required this.customer,
    required this.state,
    this.paymentRequired = false,
    this.orderMemo,
    this.anesthesia = const Anesthesia(),
    this.procedures = const [],
    this.canCall = false,
    this.canHome = false,
    this.need,
    this.kos = const KosState(),
  });
  factory BoardCard.fromJson(Json j) => BoardCard(
        visitId: _i(j['visitId']) ?? 0,
        room: Room.fromJson(_o(j['room'])),
        inAt: _s(j['inAt']),
        homeAt: _s(j['homeAt']),
        customer: Customer.fromJson(_o(j['customer'])),
        state: _s(j['state']) ?? 'waiting',
        paymentRequired: _b(j['paymentRequired']),
        orderMemo: _s(j['orderMemo']),
        anesthesia: Anesthesia.fromJson(_o(j['anesthesia'])),
        procedures: _l(j['procedures'], Procedure.fromJson),
        canCall: _b(j['canCall']),
        canHome: _b(j['canHome']),
        need: Need.fromJson(j['need']),
        kos: KosState.fromJson(_o(j['kos'])),
      );
}

class CallProcedure {
  final int id;
  final String title;
  const CallProcedure({required this.id, required this.title});
  factory CallProcedure.fromJson(Json j) => CallProcedure(id: _i(j['id']) ?? 0, title: _s(j['title']) ?? '');
}

class OpenCall {
  final int callId;
  final int visitId;
  final Room room;
  final String customerName;
  final String? customerNationality;
  final String kind; // all | one
  final int? targetDoctorId;
  final String createdAt;
  final List<CallProcedure> procedures;
  const OpenCall({
    required this.callId,
    required this.visitId,
    required this.room,
    this.customerName = '',
    this.customerNationality,
    required this.kind,
    this.targetDoctorId,
    required this.createdAt,
    this.procedures = const [],
  });
  factory OpenCall.fromJson(Json j) {
    final c = _o(j['customer']);
    return OpenCall(
      callId: _i(j['callId']) ?? 0,
      visitId: _i(j['visitId']) ?? 0,
      room: Room.fromJson(_o(j['room'])),
      customerName: _s(c['name']) ?? '',
      customerNationality: _s(c['nationality']),
      kind: _s(j['kind']) ?? 'all',
      targetDoctorId: _i(j['targetDoctorId']),
      createdAt: _s(j['createdAt']) ?? '',
      procedures: _l(j['procedures'], CallProcedure.fromJson),
    );
  }
}

class Board {
  final String now;
  final SyncInfo sync;
  final List<Doctor> doctors;
  final Counts counts;
  final Limits limits;
  final List<BoardCard> cards;
  final List<OpenCall> calls;
  final int? version; // SSE board 이벤트에만
  const Board({
    required this.now,
    this.sync = const SyncInfo(),
    this.doctors = const [],
    this.counts = const Counts(),
    this.limits = const Limits(),
    this.cards = const [],
    this.calls = const [],
    this.version,
  });
  factory Board.fromJson(Json j) => Board(
        now: _s(j['now']) ?? '',
        sync: SyncInfo.fromJson(_o(j['sync'])),
        doctors: _l(j['doctors'], Doctor.fromJson),
        counts: Counts.fromJson(_o(j['counts'])),
        limits: Limits.fromJson(_o(j['limits'])),
        cards: _l(j['cards'], BoardCard.fromJson),
        calls: _l(j['calls'], OpenCall.fromJson),
        version: _i(j['version']),
      );
}
