// 채팅 시험 — 계약 고정점 모양(SPEC-007 §6 · §7)의 가짜 back. 이름 · 문구는 지어낸 값(실명 아님)
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/chat/photo_pick.dart';
import 'package:procedure_app/model/account.dart';

final jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

// 나 = 1(가 간호) · 2 = 나 의사 · 3 = 다 코디 · 4 = 라 상담 · 5 = 마 관리(비활성)
Map<String, dynamic> member(int id, String name, {String role = 'nurse', bool active = true, bool me = false}) =>
    {'id': id, 'name': name, 'role': role, 'active': active, 'me': me};

final meM = member(1, '가간호', me: true);
final docM = member(2, '나의사', role: 'doctor');
final coordM = member(3, '다코디', role: 'coordinator');
final consM = member(4, '라상담', role: 'counselor');
final offM = member(5, '마관리', role: 'admin', active: false);

const t0 = '2026-10-29T14:03:07.215+09:00';

Map<String, dynamic> preview(int id, {int sender = 2, String senderName = '나의사', bool mine = false, String kind = 'text', String? text = '안녕하세요', bool deleted = false, String at = t0}) =>
    {'id': id, 'senderId': sender, 'senderName': senderName, 'mine': mine, 'kind': kind, 'text': text, 'deleted': deleted, 'createdAt': at};

Map<String, dynamic> roomJ(int id,
        {bool group = false,
        String? title,
        String? name,
        List<Map<String, dynamic>>? members,
        int unread = 0,
        bool muted = false,
        Map<String, dynamic>? last,
        String createdAt = '2026-10-28T09:00:00.000+09:00'}) {
  final ms = members ?? [meM, docM];
  return {
    'id': id,
    'kind': group ? 'group' : 'direct',
    'title': title,
    'name': name ?? (group ? (title ?? ms.where((m) => m['me'] != true).map((m) => m['name']).join(', ')) : ms.firstWhere((m) => m['me'] != true)['name']),
    'members': ms,
    'memberCount': ms.length,
    'muted': muted,
    'unread': unread,
    'lastMessage': last,
    'lastMessageAt': last?['createdAt'],
    'createdAt': createdAt,
  };
}

Map<String, dynamic> msgJ(int id, int roomId,
        {int sender = 2,
        String senderName = '나의사',
        String role = 'doctor',
        bool active = true,
        String kind = 'text',
        String? text = '안녕하세요',
        Map<String, dynamic>? photo,
        Map<String, dynamic>? video,
        String at = t0,
        String? updatedAt,
        String? editedAt,
        String? deletedAt,
        String? clientId}) =>
    {
      'id': id,
      'roomId': roomId,
      'clientId': clientId,
      'sender': {'id': sender, 'name': senderName, 'role': role, 'active': active},
      'kind': kind,
      'text': deletedAt != null ? null : text,
      'photo': deletedAt != null ? null : photo,
      'video': deletedAt != null ? null : video,
      'createdAt': at,
      'updatedAt': updatedAt ?? deletedAt ?? editedAt ?? at,
      'editedAt': editedAt,
      'deletedAt': deletedAt,
    };

// 가짜 back — 요청 기록 · 경로별 응답(시험이 덮어쓸 수 있음)
class FakeChat {
  final reqs = <http.Request>[];
  List<Map<String, dynamic>> rooms = [];
  final Map<int, List<Map<String, dynamic>>> messages = {};
  List<Map<String, dynamic>> people = [docM, coordM, consM];
  int nextId = 900;
  int nextPhotoId = 501;
  final Set<String> forwardFail = {}; // 전달 대상별 실패('r:<roomId>' · 'a:<accountId>')
  int nextVideoId = 601;
  // 경로 → 응답(있으면 먼저)
  final Map<String, http.Response Function(http.Request)> override = {};
  Uint8List photoBytes = Uint8List.fromList(const [0xFF, 0xD8, 0xFF, 0xD9]);
  Uint8List videoBytes = Uint8List.fromList(List.filled(4096, 3));
  String editedAt = '2026-10-29T15:00:00.456+09:00';

  List<http.Request> where(String method, String path) => [for (final r in reqs) if (r.method == method && r.url.path == path) r];

  http.Response _j(Object o, [int status = 200]) => http.Response(jsonEncode(o), status, headers: jsonHeaders);

  Future<void>? delay; // 있으면 응답 전에 기다린다(보내는 중 보기)
  final Map<String, Future<void>> slow = {}; // 경로 → 응답 전에 기다릴 것(GET 포함)
  late final http.Client client = MockClient((req) async {
    reqs.add(req);
    final d = delay;
    if (d != null && req.method == 'POST') await d;
    final p = req.url.path;
    final hold = slow[p];
    if (hold != null) await hold;
    final o = override[p] ?? override['${req.method} $p'];
    if (o != null) return o(req);
    final seg = p.split('/');
    if (p == '/api/chat/rooms' && req.method == 'GET') {
      return _j({'items': rooms, 'unreadRooms': rooms.where((r) => (r['unread'] as int) > 0).length});
    }
    if (p == '/api/chat/people') return _j({'items': people});
    if (p == '/api/chat/rooms/direct') {
      final id = (jsonDecode(req.body) as Map)['accountId'];
      final peer = people.firstWhere((x) => x['id'] == id);
      final r = rooms.where((r) => r['kind'] == 'direct' && (r['members'] as List).any((m) => m['id'] == id)).firstOrNull ??
          roomJ(nextId++, members: [meM, peer]);
      if (!rooms.contains(r)) rooms.add(r);
      return _j(r);
    }
    if (p == '/api/chat/rooms' && req.method == 'POST') {
      final b = jsonDecode(req.body) as Map;
      final ms = [meM, for (final id in b['accountIds'] as List) people.firstWhere((x) => x['id'] == id)];
      final r = roomJ(nextId++, group: true, title: b['title'] as String?, members: ms);
      rooms.add(r);
      return _j(r);
    }
    if (p == '/api/chat/photos' && req.method == 'POST') return _j({'photoId': nextPhotoId++});
    if (p == '/api/chat/videos' && req.method == 'POST') return _j({'videoId': nextVideoId++});
    // 전달(r4 #19 · r4 처분 W-5) — 대상 차례 그대로 결과 · 방 = 그 방(비활성 상대 1:1 = 그것만 409) · 사람 = 1:1 열거나 만듦 ·
    // forwardFail(대상 키 'r:<id>' · 'a:<id>') = 그 대상만 실패 · 같은 clientId 두 번 = 처음 것
    if (seg.length == 6 && seg[5] == 'forward' && req.method == 'POST') {
      final src = int.parse(seg[4]);
      final orig = messages.values.expand((l) => l).firstWhere((m) => m['id'] == src);
      final results = <Map<String, dynamic>>[];
      for (final tg in ((jsonDecode(req.body) as Map)['targets'] as List).cast<Map>()) {
        final key = tg['roomId'] != null ? 'r:${tg['roomId']}' : 'a:${tg['accountId']}';
        Map<String, dynamic>? r;
        if (tg['roomId'] != null) {
          r = rooms.where((x) => x['id'] == tg['roomId']).firstOrNull;
        } else {
          final id = tg['accountId'];
          r = rooms.where((x) => x['kind'] == 'direct' && (x['members'] as List).any((m) => m['id'] == id)).firstOrNull;
          if (r == null) {
            r = roomJ(nextId++, members: [meM, people.firstWhere((x) => x['id'] == id)]);
            rooms.add(r);
          }
        }
        final inactive = r != null && r['kind'] == 'direct' && (r['members'] as List).any((m) => m['me'] != true && m['active'] == false);
        if (r == null || forwardFail.contains(key) || inactive) {
          results.add({
            'ok': false,
            'roomId': r?['id'],
            'error': inactive
                ? {'code': 'chat_peer_inactive', 'message': '비활성 계정이에요'}
                : {'code': 'chat_room_not_found', 'message': '대화방을 찾을 수 없어요'},
          });
          continue;
        }
        final rid = r['id'] as int;
        final list = messages[rid] ??= [];
        final again = list.where((m) => m['clientId'] == tg['clientId']).firstOrNull;
        final m = again ??
            msgJ(nextId++, rid, sender: 1, senderName: '가간호', role: 'nurse', kind: orig['kind'] as String, text: orig['text'] as String?,
                photo: orig['photo'] as Map<String, dynamic>?, video: orig['video'] as Map<String, dynamic>?, clientId: tg['clientId'] as String?);
        if (again == null) list.add(m);
        results.add({'ok': true, 'roomId': rid, 'message': m});
      }
      return _j({'results': results});
    }
    if (seg.length == 5 && p.startsWith('/api/chat/videos/') && req.method == 'GET') {
      return http.Response.bytes(videoBytes, 200, headers: {'content-type': 'video/mp4'});
    }
    // 수정(r3 #15) — 서버 값 editedAt · updatedAt
    if (seg.length == 5 && p.startsWith('/api/chat/messages/') && req.method == 'PATCH') {
      final id = int.parse(seg[4]);
      final text = (jsonDecode(req.body) as Map)['text'] as String;
      for (final l in messages.values) {
        for (var i = 0; i < l.length; i++) {
          if (l[i]['id'] == id) {
            l[i] = {...l[i], 'text': text, 'editedAt': editedAt, 'updatedAt': editedAt};
            return _j(l[i]);
          }
        }
      }
      return _j({'error': {'code': 'chat_message_not_found', 'message': '메시지를 찾을 수 없어요'}}, 404);
    }
    if (seg.length == 6 && p.startsWith('/api/chat/videos/') && seg[5] == 'thumbnail') {
      return http.Response.bytes(photoBytes, 200, headers: {'content-type': 'image/jpeg'});
    }
    if (seg.length == 5 && p.startsWith('/api/chat/photos/')) return http.Response.bytes(photoBytes, 200, headers: {'content-type': 'image/jpeg'});
    if (seg.length == 6 && seg[5] == 'messages') {
      final rid = int.parse(seg[4]);
      final list = messages[rid] ?? [];
      if (req.method == 'GET') {
        final before = int.tryParse(req.url.queryParameters['before'] ?? '');
        final since = req.url.queryParameters['since'];
        var items = [...list];
        if (before != null) items = items.where((m) => (m['id'] as int) < before).toList();
        if (since != null) {
          final s = DateTime.parse(since);
          items = items.where((m) => !DateTime.parse(m['updatedAt'] as String).isBefore(s)).toList();
        }
        final more = items.length > 50;
        if (more) items = items.sublist(items.length - 50);
        return _j({'items': items, 'hasMore': more});
      }
      final b = jsonDecode(req.body) as Map;
      final m = msgJ(nextId++, rid, sender: 1, senderName: '가간호', role: 'nurse', text: b['text'] as String?,
          kind: b['photoId'] != null ? 'photo' : (b['videoId'] != null ? 'video' : 'text'),
          photo: b['photoId'] != null ? {'id': b['photoId'], 'width': 400, 'height': 300} : null,
          video: b['videoId'] != null ? {'id': b['videoId'], 'width': 720, 'height': 1280, 'durationMs': 12000} : null,
          clientId: b['clientId'] as String?);
      list.add(m);
      messages[rid] = list;
      return _j(m);
    }
    // 모아보기(r5 #20) — 사진 · 동영상만 · 지운 것 빼고 · 최근 것 위 · before · limit(기본 60)
    if (seg.length == 6 && seg[5] == 'attachments' && req.method == 'GET') {
      final rid = int.parse(seg[4]);
      final before = int.tryParse(req.url.queryParameters['before'] ?? '');
      final limit = int.tryParse(req.url.queryParameters['limit'] ?? '') ?? 60;
      var items = [
        for (final m in messages[rid] ?? const <Map<String, dynamic>>[])
          if ((m['kind'] == 'photo' || m['kind'] == 'video') && m['deletedAt'] == null && (before == null || (m['id'] as int) < before)) m
      ]..sort((a, b) => (b['id'] as int).compareTo(a['id'] as int));
      final more = items.length > limit;
      if (more) items = items.sublist(0, limit);
      return _j({'items': items, 'hasMore': more});
    }
    if (seg.length == 6 && seg[5] == 'read') {
      final rid = int.parse(seg[4]);
      for (final r in rooms) {
        if (r['id'] == rid) r['unread'] = 0;
      }
      return _j({'ok': true, 'lastViewedAt': t0, 'lastReadMessageId': (jsonDecode(req.body) as Map)['messageId'], 'unreadRooms': rooms.where((r) => (r['unread'] as int) > 0).length});
    }
    if (seg.length == 6 && seg[5] == 'mute') return _j({'ok': true, 'muted': (jsonDecode(req.body) as Map)['muted']});
    return _j({'ok': true, 'unread': 0, 'items': []});
  });
}

// 로그인된 AppState(세션 · 가짜 back) — 스트림은 열지 않는다
AppState chatApp(FakeChat f) {
  final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: f.client));
  app.session = const Session(token: 't', id: 'nurse', role: Role.nurse, name: '가간호');
  app.phase = Phase.loggedIn;
  return app;
}

void phone(WidgetTester t) {
  t.view.physicalSize = const Size(1179, 2556);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
}

void ipad(WidgetTester t) {
  t.view.physicalSize = const Size(2388, 1668);
  t.view.devicePixelRatio = 2;
  addTearDown(t.view.reset);
}

// 가짜 back 응답이 화면까지 오게(MockClient 는 진짜 비동기)
Future<void> settle(WidgetTester t, [int n = 6]) async {
  for (var i = 0; i < n; i++) {
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
    await t.pump();
  }
}

// 시험 끝 — 화면을 내리고 타이머(토스트 · 배너)를 흘린다
Future<void> teardown(WidgetTester t, AppState app) async {
  await t.pumpWidget(const SizedBox());
  await t.pump(const Duration(seconds: 5));
  app.stream.dispose();
}

// 가짜 사진 보관함(최근 줄) — photo_manager 대신
class FakeRecent extends RecentMedia {
  MediaAccess state = MediaAccess.full;
  List<RecentItem> items = [];
  Uint8List thumbBytes = Uint8List.fromList(const [0xFF, 0xD8, 0xFF, 0xD9]);
  Map<String, String> files = {}; // id → 파일 경로
  int settings = 0, limitedPicks = 0;
  @override
  Future<MediaAccess> access() async => state;
  @override
  Future<List<RecentItem>> page(int page, {int size = 60}) async => items.skip(page * size).take(size).toList();
  @override
  Future<Uint8List?> thumb(RecentItem item) async => thumbBytes;
  @override
  Future<String?> file(RecentItem item) async => files[item.id];
  @override
  Future<void> pickMoreLimited() async => limitedPicks++;
  @override
  Future<void> openSettings() async => settings++;
}
