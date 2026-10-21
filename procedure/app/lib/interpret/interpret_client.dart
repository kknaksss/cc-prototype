// 통역 세션(SPEC-004 §4.3) — WS /api/interpret. 메시지 모양 = procedure/back 통역 코드(이전 PoC 복사분)
//   앱 → back: 첫 텍스트 {type:start, lang, traditional} · 바이너리 PCM s16le 16kHz mono(40ms = 640 샘플) · {type:pause|resume|stop}
//   back → 앱: {type:ready} · {type:caption, id, side, original, translation, final} · {type:audio_start, id, sampleRate}
//             · 바이너리 PCM s16le 24kHz · {type:audio_end, id} · {type:error, code, message}
// 반이중 — 번역 음성 재생 중(audio_start ~ 재생 끝 + 400ms)에는 마이크 조각을 보내지 않는다(A-04)
// 인증 — 핸드셰이크 헤더 Authorization: Bearer <토큰>(앱은 Origin 을 보내지 않는다 · §4.2)
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

enum InterpState { connecting, listening, paused, error, closed }

enum InterpErrorKind { mic, server, closed, auth }

class Caption {
  final String key; // 세션 번호 + 발화 id
  final String side; // me | them
  final String original;
  final String translation;
  final bool isFinal;
  const Caption(this.key, this.side, this.original, this.translation, this.isFinal);
}

// WS 한 줄 — 시험에서 가짜로 바꾼다
abstract class InterpTransport {
  Stream<dynamic> get messages; // String | List<int>
  void send(Object data); // String | List<int>
  Future<void> close();
}

typedef TransportOpener = Future<InterpTransport> Function(Uri uri, String token);

class IoTransport implements InterpTransport {
  final WebSocket ws;
  IoTransport(this.ws);
  static Future<InterpTransport> open(Uri uri, String token) async {
    final ws = await WebSocket.connect(uri.toString(), headers: {'Authorization': 'Bearer $token'})
        .timeout(const Duration(seconds: 10));
    ws.pingInterval = const Duration(seconds: 20);
    return IoTransport(ws);
  }

  @override
  Stream<dynamic> get messages => ws;
  @override
  void send(Object data) => ws.add(data);
  @override
  Future<void> close() => ws.close();
}

// 재생 쪽 — 플랫폼 플레이어(audio_io.dart) · 시험 가짜
abstract class PcmSink {
  // 24kHz 등 sampleRate PCM s16le 조각을 넣는다 · 이 조각이 다 재생될 때까지 남은 시간(대략)
  Future<Duration> feed(Uint8List pcm, int sampleRate);
  Future<void> flush(); // 재생 큐 비우기
}

class InterpCallbacks {
  final void Function(InterpState s) onState;
  final void Function(Caption c) onCaption;
  final void Function(InterpErrorKind kind, String message) onError;
  final void Function(bool playing) onPlayback;
  const InterpCallbacks({required this.onState, required this.onCaption, required this.onError, required this.onPlayback});
}

int _seq = 0;

class InterpretClient {
  final Uri uri;
  final String token;
  final String lang;
  final bool traditional;
  final InterpCallbacks cb;
  final TransportOpener opener;
  final PcmSink? sink;
  final Duration resumeAfter;

  InterpretClient({
    required this.uri,
    required this.token,
    required this.lang,
    required this.traditional,
    required this.cb,
    TransportOpener? opener,
    this.sink,
    this.resumeAfter = const Duration(milliseconds: 400),
  }) : opener = opener ?? IoTransport.open;

  final int _id = ++_seq;
  InterpTransport? _t;
  StreamSubscription<dynamic>? _sub;
  InterpState state = InterpState.connecting;
  bool _closed = false;
  bool speaking = false;
  bool _audioOpen = false;
  int _outRate = 24000;
  Uint8List? _carry; // 조각 경계에 걸린 1바이트
  DateTime _playEnd = DateTime.fromMillisecondsSinceEpoch(0);
  Timer? _resumeT;

  Future<void> connect() async {
    _set(InterpState.connecting);
    try {
      _t = await opener(uri, token);
    } on WebSocketException catch (e) {
      final auth = e.toString().contains('403') || e.toString().contains('401');
      _fail(auth ? InterpErrorKind.auth : InterpErrorKind.closed,
          auth ? '통역 서버가 로그인을 받지 않았어요 — 다시 로그인해 주세요' : '통역 서버에 연결할 수 없어요');
      return;
    } catch (_) {
      _fail(InterpErrorKind.closed, '통역 서버에 연결할 수 없어요');
      return;
    }
    if (_closed) {
      await _t?.close();
      return;
    }
    _sub = _t!.messages.listen(
      (m) {
        if (m is String) {
          _onText(m);
        } else if (m is List<int>) {
          _onAudio(m is Uint8List ? m : Uint8List.fromList(m));
        }
      },
      onDone: () {
        if (!_closed && state != InterpState.error) _fail(InterpErrorKind.closed, '통역 서버와 연결이 끊겼어요');
      },
      onError: (_) {
        if (!_closed && state != InterpState.error) _fail(InterpErrorKind.closed, '통역 서버와 연결이 끊겼어요');
      },
    );
    _sendJson({'type': 'start', 'lang': lang, 'traditional': traditional});
  }

  // 마이크 조각 — 듣는 중 · 재생 중 아님 · 연결됨일 때만 보낸다
  bool sendPcm(Uint8List chunk) {
    if (state != InterpState.listening || speaking || _closed || _t == null) return false;
    _t!.send(chunk);
    return true;
  }

  void _onText(String raw) {
    Map<String, dynamic> m;
    try {
      m = (jsonDecode(raw) as Map).cast<String, dynamic>();
    } catch (_) {
      return;
    }
    switch (m['type']) {
      case 'ready':
        if (state == InterpState.connecting) _set(InterpState.listening);
      case 'caption':
        cb.onCaption(Caption(
          '$_id:${m['id']}',
          m['side'] == 'me' ? 'me' : 'them',
          '${m['original'] ?? ''}',
          '${m['translation'] ?? ''}',
          m['final'] == true,
        ));
      case 'audio_start':
        _outRate = m['sampleRate'] is num ? (m['sampleRate'] as num).toInt() : 24000;
        _carry = null;
        _audioOpen = true;
        _mute();
      case 'audio_end':
        _audioOpen = false;
        _carry = null;
        _maybeUnmute();
      case 'error':
        _fail(InterpErrorKind.server, '${m['message'] ?? '통역 서버 오류'}');
    }
  }

  void _onAudio(Uint8List bytes) {
    if (_closed) return;
    var b = bytes;
    if (_carry != null) {
      b = Uint8List.fromList([..._carry!, ...b]);
      _carry = null;
    }
    if (b.length.isOdd) {
      _carry = Uint8List.fromList([b.last]);
      b = Uint8List.sublistView(b, 0, b.length - 1);
    }
    if (b.isEmpty) return;
    final dur = Duration(microseconds: (b.length ~/ 2) * 1000000 ~/ _outRate);
    final now = DateTime.now();
    _playEnd = (_playEnd.isAfter(now) ? _playEnd : now).add(dur);
    sink?.feed(Uint8List.fromList(b), _outRate);
  }

  void _mute() {
    _resumeT?.cancel();
    _resumeT = null;
    if (!speaking) {
      speaking = true;
      if (!_closed) cb.onPlayback(true);
    }
  }

  // 발화가 끝났고(audio_end) 재생이 끝나면 400ms 뒤 송신 재개
  void _maybeUnmute() {
    if (!speaking || _audioOpen) return;
    _resumeT?.cancel();
    final left = _playEnd.difference(DateTime.now());
    _resumeT = Timer((left.isNegative ? Duration.zero : left) + resumeAfter, () {
      _resumeT = null;
      if (_audioOpen) return;
      if (_playEnd.isAfter(DateTime.now())) return _maybeUnmute();
      speaking = false;
      if (!_closed) cb.onPlayback(false);
    });
  }

  void _stopPlayback() {
    _resumeT?.cancel();
    _resumeT = null;
    _audioOpen = false;
    _playEnd = DateTime.fromMillisecondsSinceEpoch(0);
    sink?.flush();
    if (speaking) {
      speaking = false;
      if (!_closed) cb.onPlayback(false);
    }
  }

  // [멈춤] / [다시 듣기] — 연결은 두고 마이크만
  void toggle() {
    if (state == InterpState.listening) {
      _stopPlayback();
      _sendJson({'type': 'pause'});
      _set(InterpState.paused);
    } else if (state == InterpState.paused) {
      _sendJson({'type': 'resume'});
      _set(InterpState.listening);
    }
  }

  // [종료] — stop 보내고 닫음
  Future<void> close() async {
    if (_closed) return;
    _sendJson({'type': 'stop'});
    _stopPlayback();
    _closed = true;
    state = InterpState.closed;
    await _release();
  }

  Future<void> _release() async {
    await _sub?.cancel();
    _sub = null;
    final t = _t;
    _t = null;
    try {
      await t?.close();
    } catch (_) {}
  }

  void _sendJson(Map<String, Object?> m) {
    if (_t == null || _closed) return;
    try {
      _t!.send(jsonEncode(m));
    } catch (_) {}
  }

  void _set(InterpState s) {
    state = s;
    if (!_closed) cb.onState(s);
  }

  void _fail(InterpErrorKind kind, String message) {
    if (_closed) return;
    _set(InterpState.error);
    cb.onError(kind, message);
    _stopPlayback();
    _closed = true;
    _release();
  }
}
