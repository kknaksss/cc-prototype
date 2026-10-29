// 판 스트림(SPEC-004 §7.1) — GET /api/board/stream?token= 를 http 스트림 요청으로. EventSource 없음.
// - 연결 직후 오는 board 하나로 첫 화면(GET /api/board 따로 안 부름)
// - version: 가진 것보다 작거나 같으면 버림 · 새 연결의 첫 board 는 무조건 받음(back 재시작이면 0 부터)
// - 끊기면 retry(기본 3000ms) 뒤 다시 · 연속 실패면 3s → 6s → 12s … 최대 30s · 45초 동안 바이트가 없으면 끊긴 것으로
// - 401 이면 onUnauthorized(토큰 지우고 로그인으로)
// - board 말고 display · notification(0.4.0 · `id:` 없음 · version 안 올림)은 version 규칙 없이 onEvent 로(§7.1 r2)
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../model/board.dart';
import 'sse_parser.dart';

// version 규칙 — 받을 것인가
bool acceptVersion({required int? incoming, required int current, required bool firstOfConnection}) {
  if (firstOfConnection) return true;
  if (incoming == null) return true;
  return incoming > current;
}

// 연속 실패 n 번째(1부터)의 다음 연결까지 기다림
Duration backoff(int failures, {int retryMs = 3000, int maxMs = 30000}) {
  if (failures <= 1) return Duration(milliseconds: retryMs.clamp(0, maxMs));
  var ms = retryMs;
  for (var i = 1; i < failures; i++) {
    ms *= 2;
    if (ms >= maxMs) return Duration(milliseconds: maxMs);
  }
  return Duration(milliseconds: ms);
}

class BoardStream extends ChangeNotifier {
  final Uri Function() uri;
  final VoidCallback onUnauthorized;
  final http.Client Function() clientFactory;
  final Duration idleTimeout;
  // board 밖 이벤트(display · notification) — data 를 JSON 으로 풀어서
  void Function(String event, Map<String, dynamic> data)? onEvent;

  BoardStream({
    required this.uri,
    required this.onUnauthorized,
    this.onEvent,
    http.Client Function()? clientFactory,
    this.idleTimeout = const Duration(seconds: 45),
  }) : clientFactory = clientFactory ?? http.Client.new;

  Board? board;
  int skewMs = 0; // 서버 시각 - 기기 시각(경과 시간 보정 · SPEC-003 §6.6)
  bool connected = false;

  int _version = -1;
  int _retryMs = 3000;
  int _failures = 0;
  bool _running = false;
  int _gen = 0; // 연결 세대 — 옛 연결의 콜백을 버린다
  http.Client? _client;
  StreamSubscription<List<int>>? _sub;
  Timer? _idle;
  Timer? _retry;

  bool get running => _running;

  void start() {
    if (_running) return;
    _running = true;
    _failures = 0;
    _open();
  }

  // 백그라운드 · 로그아웃 — 닫는다(마지막 스냅샷은 그대로 둔다)
  void stop() {
    _running = false;
    _close();
    _retry?.cancel();
    if (connected) {
      connected = false;
      notifyListeners();
    }
  }

  void reset() {
    stop();
    board = null;
    _version = -1;
    notifyListeners();
  }

  void _close() {
    _gen++;
    _idle?.cancel();
    _sub?.cancel();
    _sub = null;
    _client?.close();
    _client = null;
  }

  Future<void> _open() async {
    if (!_running) return;
    _close();
    final gen = _gen;
    final client = clientFactory();
    _client = client;
    var first = true;
    final parser = SseParser(onRetry: (ms) => _retryMs = ms);
    try {
      final req = http.Request('GET', uri())
        ..headers.addAll({'Accept': 'text/event-stream', 'Cache-Control': 'no-cache'});
      final res = await client.send(req).timeout(const Duration(seconds: 15));
      if (gen != _gen) return;
      if (res.statusCode == 401) {
        _running = false;
        _close();
        _setConnected(false);
        onUnauthorized();
        return;
      }
      if (res.statusCode != 200) throw StateError('status ${res.statusCode}');
      _armIdle(gen);
      _sub = res.stream.listen(
        (bytes) {
          if (gen != _gen) return;
          _armIdle(gen);
          for (final ev in parser.addBytes(bytes)) {
            if (ev.event != 'board') {
              _other(ev.event, ev.data);
              continue;
            }
            Board b;
            try {
              b = Board.fromJson((jsonDecode(ev.data) as Map).cast<String, dynamic>());
            } catch (_) {
              continue;
            }
            if (!acceptVersion(incoming: b.version, current: _version, firstOfConnection: first)) continue;
            first = false;
            _version = b.version ?? _version;
            _failures = 0;
            final server = DateTime.tryParse(b.now);
            skewMs = server == null ? 0 : server.millisecondsSinceEpoch - DateTime.now().millisecondsSinceEpoch;
            board = b;
            connected = true;
            notifyListeners();
          }
        },
        onError: (_) => _lost(gen),
        onDone: () => _lost(gen),
        cancelOnError: true,
      );
    } catch (_) {
      if (gen == _gen) _lost(gen);
    }
  }

  // board 말고 받는 이벤트 — id: 없음 · version 규칙 밖(§7.1 · SPEC-007 §7 채팅 6개 — r3 chat_message_edited)
  static const otherEvents = {
    'display',
    'notification',
    'chat_message',
    'chat_message_deleted',
    'chat_message_edited',
    'chat_room',
    'chat_room_removed',
    'chat_read',
  };

  void _other(String event, String data) {
    if (!otherEvents.contains(event)) return;
    try {
      final j = jsonDecode(data);
      if (j is Map) onEvent?.call(event, j.cast<String, dynamic>());
    } catch (_) {}
  }

  void _armIdle(int gen) {
    _idle?.cancel();
    _idle = Timer(idleTimeout, () => _lost(gen));
  }

  void _lost(int gen) {
    if (gen != _gen || !_running) return;
    _close();
    _setConnected(false);
    _failures++;
    _retry?.cancel();
    _retry = Timer(backoff(_failures, retryMs: _retryMs), _open);
  }

  void _setConnected(bool v) {
    if (connected == v) return;
    connected = v;
    notifyListeners();
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
