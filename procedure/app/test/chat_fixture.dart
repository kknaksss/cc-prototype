// 채팅 시험 — 계약 고정점 모양(SPEC-007 §6 · §7)의 가짜 back. 이름 · 문구는 지어낸 값(실명 아님)
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
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
        String at = t0,
        String? updatedAt,
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
      'createdAt': at,
      'updatedAt': updatedAt ?? deletedAt ?? at,
      'deletedAt': deletedAt,
    };

// 가짜 back — 요청 기록 · 경로별 응답(시험이 덮어쓸 수 있음)
class FakeChat {
  final reqs = <http.Request>[];
  List<Map<String, dynamic>> rooms = [];
  final Map<int, List<Map<String, dynamic>>> messages = {};
  List<Map<String, dynamic>> people = [docM, coordM, consM];
  int nextId = 900;
  // 경로 → 응답(있으면 먼저)
  final Map<String, http.Response Function(http.Request)> override = {};
  Uint8List photoBytes = Uint8List.fromList(const [0xFF, 0xD8, 0xFF, 0xD9]);

  List<http.Request> where(String method, String path) => [for (final r in reqs) if (r.method == method && r.url.path == path) r];

  http.Response _j(Object o, [int status = 200]) => http.Response(jsonEncode(o), status, headers: jsonHeaders);

  Future<void>? delay; // 있으면 응답 전에 기다린다(보내는 중 보기)
  late final http.Client client = MockClient((req) async {
    reqs.add(req);
    final d = delay;
    if (d != null && req.method == 'POST') await d;
    final p = req.url.path;
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
    if (p == '/api/chat/photos' && req.method == 'POST') return _j({'photoId': 501});
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
          kind: b['photoId'] != null ? 'photo' : 'text', photo: b['photoId'] != null ? {'id': b['photoId'], 'width': 400, 'height': 300} : null,
          clientId: b['clientId'] as String?);
      list.add(m);
      messages[rid] = list;
      return _j(m);
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
