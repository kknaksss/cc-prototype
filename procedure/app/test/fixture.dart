// 시험 스냅샷 — back schemas/board.py 모양 · 값은 지어낸 것
import 'package:procedure_app/model/board.dart';

Map<String, dynamic> proc(int id, String state,
        {String kind = 'procedure', int seq = 1, String title = '시술', Map<String, dynamic>? doctor, Map<String, dynamic>? call,
        String? started, String? completed, bool pickable = false, bool canStart = false, bool canFinish = false}) =>
    {
      'id': id, 'kind': kind, 'sequence': seq, 'title': title, 'state': state, 'kosStatus': null,
      'startedAt': started, 'completedAt': completed, 'doctor': doctor, 'call': call,
      'pickable': pickable, 'canStart': canStart, 'canFinish': canFinish,
    };

Map<String, dynamic> card(int visitId, {String state = 'waiting', String? inAt, String? homeAt, List<Map<String, dynamic>> procs = const [],
        Map<String, dynamic>? need, String? anesSince, bool canHome = false, bool canCall = false}) =>
    {
      'visitId': visitId,
      'room': {'id': visitId, 'title': 'A-룸$visitId', 'order': visitId},
      'inAt': inAt, 'homeAt': homeAt,
      'customer': {'name': '고객$visitId', 'phoneticName': null, 'nationality': 'TW', 'isNew': true, 'chartNumber': null},
      'state': state, 'paymentRequired': false, 'orderMemo': null,
      'anesthesia': {'runningSince': anesSince, 'lastMinutes': null, 'long': false, 'canStart': anesSince == null, 'canEnd': anesSince != null},
      'procedures': procs, 'canCall': canCall, 'canHome': canHome, 'need': need,
      'kos': {'status': 'ok', 'failed': []},
    };

Board board({List<Map<String, dynamic>> cards = const [], List<Map<String, dynamic>> calls = const []}) => Board.fromJson({
      'now': '2026-10-21T10:00:00+09:00',
      'sync': {'lastOkAt': null, 'lastError': null, 'inWindow': true, 'extra': 1},
      'doctors': [
        {'id': 1, 'name': '가 원장', 'busy': false, 'busyRoom': null},
        {'id': 2, 'name': '나 원장', 'busy': true, 'busyRoom': 'A-룸3'},
      ],
      'counts': {'all': cards.length, 'need': 1, 'waiting': 1, 'anes': 0, 'call': calls.length, 'doing': 0},
      'limits': {'callMin': 5, 'anesMin': 20},
      'cards': cards,
      'calls': calls,
      'recentAccepts': [],
      'unknownField': {'x': 1},
    });

Map<String, dynamic> openCall(int callId, int visitId, String kind, {int? target, String created = '2026-10-21T09:50:00+09:00', List<int> procIds = const [1]}) => {
      'callId': callId, 'visitId': visitId, 'room': {'id': visitId, 'title': 'A-룸$visitId', 'order': visitId},
      'customer': {'name': '고객$visitId', 'nationality': 'TW'}, 'kind': kind, 'targetDoctorId': target, 'createdAt': created,
      'procedures': [for (final i in procIds) {'id': i, 'title': '시술$i'}],
    };
