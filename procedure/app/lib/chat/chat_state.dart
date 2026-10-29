// 채팅 상태 한 곳(SPEC-007 §5 · §7 · §10 · §11) — 방 목록 · 탭 배지 · 방마다 메시지 · 보내는 중 · 사진 메모리 캐시 · 보고 있는 방 · 읽음 · 앱 안 배너.
// 앱은 back 값만 쓴다(안 읽음 · 방 이름 = back). 앱이 세는 것은 SSE 사이의 +1 뿐(§10.1 「배지 갱신」)
import 'dart:async';
import 'dart:collection';
import 'dart:math' show max;
import 'dart:typed_data';

import 'package:flutter/widgets.dart';

import '../api/api.dart';
import '../widgets/ui.dart' show Toaster;
import 'chat_model.dart';
import 'chat_view.dart';

// 띄우기 화면(문진 QR · 여권 스캔)이 떠 있는 수 — showQrScreen · showPassportScan 이 어느 길로 열렸든 올리고 내린다(D9-44 · A24).
// 0 이 아니면 앱 안 배너를 만들지 않고, 그동안 온 것은 쌓아 두지 않는다(닫힌 뒤 한꺼번에 뜨지 않음 · OQ-933)
final ValueNotifier<int> openDisplayScreens = ValueNotifier(0);

Future<T> whileDisplayScreen<T>(Future<T> Function() open) async {
  openDisplayScreens.value++;
  try {
    return await open();
  } finally {
    openDisplayScreens.value--;
  }
}

// 루트 Navigator 에 쌓인 화면 수(대화상자 · 시트 · 사진 크게 보기 · 아이패드 방 정보 · 알림 목록 · 문진 QR …) — 0 이 아니면 보고 있는 방이 아니다(§5 · W2-4)
class RootRoutes extends NavigatorObserver {
  final ValueNotifier<int> count = ValueNotifier(0);
  final Set<Route<dynamic>> _above = {};
  void _sync() => count.value = _above.length;
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    if (previousRoute != null) _above.add(route);
    _sync();
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _above.remove(route);
    _sync();
  }

  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _above.remove(route);
    _sync();
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    if (oldRoute != null && _above.remove(oldRoute) && newRoute != null) _above.add(newRoute);
    _sync();
  }
}

// 사진 메모리 캐시(사진 id → 바이트 · 최근 100장 · 디스크 없음 — D9-24 · OQ-925)
class PhotoCache {
  final int capacity;
  final LinkedHashMap<int, Uint8List> _m = LinkedHashMap();
  PhotoCache([this.capacity = 100]);
  Uint8List? get(int id) {
    final v = _m.remove(id);
    if (v != null) _m[id] = v;
    return v;
  }

  void put(int id, Uint8List bytes) {
    _m.remove(id);
    _m[id] = bytes;
    while (_m.length > capacity) {
      _m.remove(_m.keys.first);
    }
  }

  void remove(int id) => _m.remove(id);
  void clear() => _m.clear();
  int get length => _m.length;
}

// 한 방의 메시지 — id 로 겹침을 지운다(같은 id = 새 것으로 바꿔 끼움 · §5 페이지)
class ChatThread {
  final Map<int, ChatMessage> byId = {};
  final List<PendingMessage> pending = [];
  bool loaded = false;
  bool loading = false;
  bool hasOlder = false;
  bool loadingOlder = false;

  List<ChatMessage> get messages => byId.values.toList()..sort((a, b) => a.id.compareTo(b.id));
  int get lastId => byId.isEmpty ? 0 : byId.keys.reduce(max);
  int? get oldestId => byId.isEmpty ? null : byId.keys.reduce((a, b) => a < b ? a : b);

  // since 기준 — 받은 것 중 가장 늦은 updatedAt(받은 게 없으면 null → since 없이 처음 읽기 · W2-2)
  String? get latestUpdatedAt {
    String? best;
    DateTime? bt;
    for (final m in byId.values) {
      final t = DateTime.tryParse(m.updatedAt);
      if (t != null && (bt == null || t.isAfter(bt))) {
        bt = t;
        best = m.updatedAt;
      }
    }
    return best;
  }

  void merge(Iterable<ChatMessage> items) {
    for (final m in items) {
      byId[m.id] = m;
    }
  }

  void reset() {
    byId.clear();
    loaded = false;
    hasOlder = false;
  }
}

class ChatState extends ChangeNotifier {
  final Api api;
  final Toaster toaster;
  // 지금 탭이 「채팅」인가(AppState.tab) · 401 = 로그아웃(app_state run 과 같게)
  final bool Function() onChatTab;
  final Future<void> Function() onUnauthorized;
  final RootRoutes rootRoutes = RootRoutes();
  // 채팅 탭 Navigator 의 화면 쌓임(대화 화면 · 목록이 RouteAware 로 「맨 위」를 안다 — A31)
  final RouteObserver<ModalRoute<void>> chatRoutes = RouteObserver<ModalRoute<void>>();

  ChatState({required this.api, required this.toaster, required this.onChatTab, required this.onUnauthorized}) {
    rootRoutes.count.addListener(reevaluate);
    openDisplayScreens.addListener(_onDisplayScreens);
  }

  List<Room> rooms = [];
  bool roomsLoaded = false;
  final ValueNotifier<int> unreadRooms = ValueNotifier(0);
  int? meId; // 내 계정 id(Room.members[].me · 내가 보낸 Message.sender)
  final Map<int, ChatThread> threads = {};
  final PhotoCache photos = PhotoCache();
  final Map<int, Future<Uint8List?>> _photoLoads = {};

  // 푸시 누름 · 배너 [보기] → 채팅 탭이 그 방을 연다
  final ValueNotifier<int?> openRequest = ValueNotifier(null);
  // 내 목록에서 빠진 방(나감 · 숨김 · 다른 기기) — 열려 있으면 닫는다
  final ValueNotifier<int?> removed = ValueNotifier(null);

  Room? room(int id) => rooms.where((r) => r.id == id).firstOrNull;
  ChatThread thread(int roomId) => threads.putIfAbsent(roomId, ChatThread.new);

  bool isMine(ChatMessage m) => meId != null && m.sender.id == meId;

  void _learnMe(Room r) {
    final me = r.me;
    if (me != null) meId = me.id;
  }

  void _sort() => rooms.sort((a, b) {
        final x = DateTime.tryParse(a.sortAt), y = DateTime.tryParse(b.sortAt);
        if (x == null || y == null) return b.sortAt.compareTo(a.sortAt);
        return y.compareTo(x);
      });

  // 탭 배지 = 안 읽은 방 수(알림 끈 방도 셈 · 숨긴 1:1 은 목록에 없으니 안 셈 — §6.2 #2)
  void _recount() => unreadRooms.value = rooms.where((r) => r.unread > 0).length;

  void _upsert(Room r) {
    _learnMe(r);
    final i = rooms.indexWhere((x) => x.id == r.id);
    if (i >= 0) {
      rooms[i] = r;
    } else {
      rooms.add(r);
    }
    _sort();
    _recount();
  }

  void _remove(int roomId) {
    rooms.removeWhere((r) => r.id == roomId);
    threads.remove(roomId);
    _readSent.remove(roomId);
    _recount();
    removed.value = null; // 같은 방이 두 번 빠져도(나감 → 다시 초대 → 나감) 알리게
    removed.value = roomId;
    if (_top == roomId) _top = null;
  }

  // ─── 읽기
  // GET /api/chat/rooms — 실패(옛 back 404 · 네트워크)는 조용히 그대로(§11 · refreshUnread 와 같게)
  Future<bool> refreshRooms() async {
    try {
      final r = await api.chatRooms();
      rooms = r.items;
      for (final x in rooms) {
        _learnMe(x);
      }
      _sort();
      roomsLoaded = true;
      _recount();
      notifyListeners();
      reevaluate();
      return true;
    } on ApiError {
      return false;
    }
  }

  // 처음 = 최근 50(§5)
  Future<void> loadLatest(int roomId) async {
    final t = thread(roomId);
    if (t.loading) return;
    t.loading = true;
    await null; // 화면 initState 에서 불려도 그리는 중에 알리지 않게
    try {
      final r = await api.chatMessages(roomId);
      t.byId.clear();
      t.merge(r.items);
      t.hasOlder = r.hasMore;
      t.loaded = true;
    } on ApiError catch (e) {
      if (e.status == 401) unawaited(onUnauthorized());
    } finally {
      t.loading = false;
      notifyListeners();
      reevaluate();
    }
  }

  // 위 끝 = before=<가장 오래된 id> 50
  Future<void> loadOlder(int roomId) async {
    final t = thread(roomId);
    final oldest = t.oldestId;
    if (!t.hasOlder || t.loadingOlder || oldest == null) return;
    t.loadingOlder = true;
    notifyListeners();
    try {
      final r = await api.chatMessages(roomId, before: oldest);
      t.merge(r.items);
      t.hasOlder = r.hasMore;
    } on ApiError {
      // 그대로 — 다음 스크롤 때 다시
    } finally {
      t.loadingOlder = false;
      notifyListeners();
    }
  }

  // 놓친 것 메우기(앞으로 옴 · SSE 다시 연결 — §11) — since=<가장 늦은 updatedAt>(>=) · id 로 겹침 지움 · hasMore 면 최근 50 다시
  Future<void> catchUp() async {
    await refreshRooms();
    for (final e in threads.entries.toList()) {
      final id = e.key, t = e.value;
      if (!_views.containsKey(id)) {
        t.reset(); // 열려 있지 않은 방 = 다음에 열 때 처음부터
        continue;
      }
      final since = t.latestUpdatedAt;
      if (!t.loaded || since == null) {
        await loadLatest(id);
        continue;
      }
      try {
        final r = await api.chatMessages(id, since: since);
        if (r.hasMore) {
          t.byId.clear();
          t.merge((await api.chatMessages(id)).items);
          t.hasOlder = true;
        } else {
          t.merge(r.items);
        }
      } on ApiError {
        // 조용히
      }
    }
    notifyListeners();
    reevaluate();
  }

  // ─── 보고 있는 방(§5 · D9-40) — 앱이 앞 · 지금 탭 = 채팅 · 그 대화가 채팅 스택 맨 위(아이패드 = 오른쪽 칸) · 루트 위 화면 없음
  bool foreground = true;
  int? _top;
  final Map<int, int> _views = {}; // 열린 대화 화면 수(방마다)

  int? get watching => foreground && onChatTab() && rootRoutes.count.value == 0 && openDisplayScreens.value == 0 ? _top : null;

  // 대화 화면이 채팅 스택 맨 위가 됨 / 아님(RouteAware · 아이패드 고른 방)
  void setTop(int roomId) {
    _top = roomId;
    reevaluate();
  }

  void clearTop(int roomId) {
    if (_top == roomId) _top = null;
  }

  void viewOpened(int roomId) => _views[roomId] = (_views[roomId] ?? 0) + 1;
  void viewClosed(int roomId) {
    final n = (_views[roomId] ?? 1) - 1;
    n <= 0 ? _views.remove(roomId) : _views[roomId] = n;
  }

  // 보고 있는 방이 되면 읽음(방을 엶 · 채팅 탭으로 돌아옴 · 위 화면 닫음 · 앞으로 옴).
  // 화면 그리는 중(initState · RouteObserver.subscribe → didPush)에도 불리므로 마이크로태스크로 미룬다(한 번으로 묶음)
  bool _evalQueued = false;
  void reevaluate() {
    if (_evalQueued) return;
    _evalQueued = true;
    scheduleMicrotask(() {
      _evalQueued = false;
      final w = watching;
      if (w != null) _markRead(w);
    });
  }

  final Map<int, int> _readSent = {};
  Timer? _readTimer;

  // POST …/read {messageId = 그린 마지막 id}. 받은 메시지가 없으면 보내지 않는다(0 = 아무것도 안 바꿈 · W2-2)
  Future<void> _markRead(int roomId) async {
    final t = threads[roomId];
    final last = t?.lastId ?? 0;
    final r = room(roomId);
    if (last == 0 || (last <= (_readSent[roomId] ?? 0) && (r?.unread ?? 0) == 0)) return;
    _readSent[roomId] = last;
    if (r != null && r.unread != 0) {
      r.unread = 0;
      _recount();
      notifyListeners();
    }
    try {
      final j = await api.chatRead(roomId, last);
      final n = j['unreadRooms'];
      if (n is num && n.toInt() != unreadRooms.value) await refreshRooms();
    } on ApiError catch (e) {
      _readSent.remove(roomId);
      if (e.status == 401) unawaited(onUnauthorized());
    }
  }

  // 보고 있는 방에 새 메시지 — 1초 묶음(OQ-916)
  void _readSoon(int roomId) {
    _readTimer?.cancel();
    _readTimer = Timer(const Duration(seconds: 1), () {
      if (watching == roomId) _markRead(roomId);
    });
  }

  void setForeground(bool v) {
    foreground = v;
    if (!v) banner.value = null;
  }

  // ─── SSE(§7)
  void onEvent(String event, Map<String, dynamic> data) {
    switch (event) {
      case 'chat_message':
        final m = data['message'];
        if (m is Map) _onMessage(ChatMessage.fromJson(m.cast<String, dynamic>()));
      case 'chat_message_deleted':
        final rid = data['roomId'], mid = data['messageId'];
        if (rid is num && mid is num) _onDeleted(rid.toInt(), mid.toInt(), data['updatedAt'] is String ? data['updatedAt'] as String : null);
      case 'chat_room':
        final r = data['room'];
        if (r is Map) {
          _upsert(Room.fromJson(r.cast<String, dynamic>()));
          notifyListeners();
          reevaluate();
        }
      case 'chat_room_removed':
        final rid = data['roomId'];
        if (rid is num) {
          _remove(rid.toInt());
          notifyListeners();
        }
      case 'chat_read':
        final rid = data['roomId'], last = data['lastReadMessageId'];
        final r = rid is num ? room(rid.toInt()) : null;
        if (r != null && (last is! num || last.toInt() >= (r.lastMessage?.id ?? 0))) r.unread = 0;
        _recount();
        notifyListeners();
    }
  }

  void _onMessage(ChatMessage m) {
    final t = threads[m.roomId];
    var mine = isMine(m);
    if (t != null) {
      final before = t.pending.length;
      t.pending.removeWhere((p) => p.clientId == m.clientId && m.clientId != null);
      if (t.pending.length != before) {
        mine = true;
        meId ??= m.sender.id;
      }
      if (t.loaded) t.merge([m]);
    }
    final r = room(m.roomId);
    // 이미 센 메시지(chat_room 이 먼저 와서 미리보기 · 안 읽음에 들어 있음)는 다시 세지 않는다
    if (r != null && (r.lastMessage?.id ?? 0) < m.id) {
      r.lastMessage = Preview.of(m, mine: mine);
      r.lastMessageAt = m.createdAt;
      final counts = !mine && m.kind != MsgKind.system && !m.deleted;
      if (mine) {
        r.unread = 0; // 보낸 사람 읽음 = 그 메시지(§5 「보낸 뒤」)
      } else if (counts && watching != m.roomId) {
        r.unread++;
      }
      _sort();
      _recount();
    }
    if (watching == m.roomId) _readSoon(m.roomId);
    if (!mine && m.kind != MsgKind.system && !m.deleted) {
      final group = r?.group ?? false;
      offerBanner(ChatBanner(m.roomId, m.id, group && r != null ? '${m.sender.name} · ${roomTitle(r)}' : m.sender.name, bodyHead(m)));
    }
    notifyListeners();
  }

  // at = 서버가 준 updatedAt(SSE) — 없으면(DELETE 응답 = {ok}) 그 메시지의 updatedAt 을 그대로 둔다.
  // since 원천에 앱이 만든 시각을 섞지 않는다(오프셋 없는 로컬 시각 → since 가 미래 — review-code r1 FAIL-1)
  void _onDeleted(int roomId, int messageId, String? at) {
    final t = threads[roomId];
    final m = t?.byId[messageId];
    if (m != null && (at != null && at.isNotEmpty || !m.deleted)) {
      t!.byId[messageId] = m.asDeleted(at != null && at.isNotEmpty ? at : m.updatedAt);
      if (m.photo != null) photos.remove(m.photo!.id);
    }
    final r = room(roomId);
    if (r != null && r.lastMessage?.id == messageId) r.lastMessage = r.lastMessage!.asDeleted();
    // 지운 것이 안 읽음이었는지는 back 만 안다 — 안 읽음이 있으면 목록을 다시 읽는다
    if (r != null && r.unread > 0) unawaited(refreshRooms());
    notifyListeners();
  }

  // ─── 앱 안 배너(§10.12) — 원천 = SSE · 앞에서 받은 푸시 중 먼저 온 것 · messageId 로 한 번(OQ-938)
  final ValueNotifier<ChatBanner?> banner = ValueNotifier(null);
  final Set<int> _bannered = {};
  Timer? _bannerTimer;
  static const bannerFor = Duration(seconds: 4);

  void offerBanner(ChatBanner b) {
    if (!_bannered.add(b.messageId)) return;
    if (!foreground || openDisplayScreens.value > 0) return; // 띄우기 중 = 버림(쌓지 않음)
    final r = room(b.roomId);
    if (r != null && r.muted) return;
    if (watching == b.roomId) return;
    banner.value = b;
    _bannerTimer?.cancel();
    _bannerTimer = Timer(bannerFor, () {
      if (banner.value == b) banner.value = null;
    });
  }

  void _onDisplayScreens() {
    if (openDisplayScreens.value > 0) banner.value = null;
    reevaluate();
  }

  void openRoom(int roomId) {
    banner.value = null;
    openRequest.value = null;
    openRequest.value = roomId;
  }

  // ─── 보내기(§10.5 · §10.6)
  void sendText(int roomId, String text) {
    final p = PendingMessage(clientId: newClientId(), roomId: roomId, text: text);
    thread(roomId).pending.add(p);
    notifyListeners();
    _deliver(p);
  }

  void sendPhoto(int roomId, Uint8List jpeg, int width, int height) {
    final p = PendingMessage(clientId: newClientId(), roomId: roomId, photoBytes: jpeg, width: width, height: height)..progress = 0;
    thread(roomId).pending.add(p);
    notifyListeners();
    _deliver(p);
  }

  // [다시 보내기] — 같은 clientId(두 번 가지 않음 · D9-16) · 사진이 올라갔으면 보내기만
  void retry(PendingMessage p) => _deliver(p);

  Future<void> _deliver(PendingMessage p) async {
    p.state = SendState.sending;
    notifyListeners();
    try {
      if (p.isPhoto && p.photoId == null) {
        p.photoId = await api.chatUploadPhoto(p.roomId, p.photoBytes!, width: p.width, height: p.height, onProgress: (v) {
          p.progress = v;
          notifyListeners();
        });
        photos.put(p.photoId!, p.photoBytes!);
      }
      final m = await api.chatSend(p.roomId, p.clientId, text: p.isPhoto ? null : p.text, photoId: p.photoId);
      meId = m.sender.id;
      _onMessage(m); // SSE 로 같은 clientId 가 와도 하나(pending 이 이미 빠짐 · id 로 바꿔 끼움)
      thread(p.roomId).pending.remove(p);
    } on ApiError catch (e) {
      final t = thread(p.roomId);
      if (e.status == 401) {
        t.pending.remove(p);
        unawaited(onUnauthorized());
      } else if (e.status >= 400 && e.status < 500) {
        t.pending.remove(p); // 다시 보내도 같은 답(나간 방 404 · 비활성 409 …) — 토스트 + 지움(OQ-934)
        toaster.show(e.message);
      } else {
        p.state = SendState.failed; // 네트워크 · 5xx · 시간 넘김
      }
    }
    notifyListeners();
  }

  // 삭제(내 메시지만 · §10.7) — 화면은 SSE chat_message_deleted 로도 바뀐다
  Future<void> delete(ChatMessage m) async {
    await api.chatDelete(m.id);
    _onDeleted(m.roomId, m.id, null); // 응답에 시각이 없다 — 서버 updatedAt 은 SSE 가 넣는다
  }

  // ─── 방 바꾸기(§6.2 #3 ~ #8) — 오류는 화면이 app.run 으로 토스트
  Future<Room> openDirect(int accountId) async {
    final r = await api.chatOpenDirect(accountId);
    _upsert(r);
    notifyListeners();
    return r;
  }

  Future<Room> createGroup(List<int> ids, {String? title}) async {
    final r = await api.chatCreateGroup(ids, title: title);
    _upsert(r);
    notifyListeners();
    return r;
  }

  Future<Room> addMembers(int roomId, List<int> ids) async {
    final r = await api.chatAddMembers(roomId, ids);
    _upsert(r);
    notifyListeners();
    return r;
  }

  Future<void> leave(int roomId) async {
    await api.chatLeave(roomId);
    _remove(roomId);
    notifyListeners();
  }

  Future<void> hide(int roomId) async {
    await api.chatHide(roomId);
    _remove(roomId);
    notifyListeners();
  }

  Future<void> setMuted(int roomId, bool muted) async {
    await api.chatMute(roomId, muted);
    room(roomId)?.muted = muted;
    notifyListeners();
  }

  // 사진 바이트(메모리 캐시 · 같은 사진 동시 요청은 하나로)
  Future<Uint8List?> photo(int id) {
    final hit = photos.get(id);
    if (hit != null) return Future.value(hit);
    return _photoLoads.putIfAbsent(id, () async {
      try {
        final b = await api.chatPhoto(id);
        photos.put(id, b);
        return b;
      } on ApiError {
        return null;
      } finally {
        _photoLoads.remove(id);
      }
    });
  }

  // 로그아웃 · 계정 바뀜 — 메모리를 비운다(방 · 메시지 · 사진 · 실패 말풍선 · 열린 방 — §11 · D9-24 · D9-41).
  // 푸시로 들어온 열기 요청은 계정이 바뀌어도 남긴다(로그인 뒤 그 방 — §8 · 멤버 아니면 토스트) · 로그아웃만 keepOpen: false
  void clear({bool keepOpen = true}) {
    rooms = [];
    roomsLoaded = false;
    meId = null;
    threads.clear();
    photos.clear();
    _photoLoads.clear();
    _readSent.clear();
    _bannered.clear();
    _readTimer?.cancel();
    _bannerTimer?.cancel();
    banner.value = null;
    if (!keepOpen) openRequest.value = null;
    _top = null;
    _recount();
    notifyListeners();
  }

  @override
  void dispose() {
    _readTimer?.cancel();
    _bannerTimer?.cancel();
    rootRoutes.count.removeListener(reevaluate);
    openDisplayScreens.removeListener(_onDisplayScreens);
    super.dispose();
  }
}
