import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:procedure_app/interpret/audio_io.dart' show Chunker;
import 'package:procedure_app/interpret/interpret_client.dart';
import 'package:procedure_app/interpret/langs.dart';

// 가짜 통역 서버 — 앱이 보낸 것을 모으고, 서버 프레임을 흘려 준다
class FakeTransport implements InterpTransport {
  final ctl = StreamController<dynamic>();
  final sent = <Object>[];
  bool closed = false;
  @override
  Stream<dynamic> get messages => ctl.stream;
  @override
  void send(Object data) => sent.add(data);
  @override
  Future<void> close() async {
    closed = true;
    await ctl.close();
  }

  List<Map<String, dynamic>> get json => sent.whereType<String>().map((s) => (jsonDecode(s) as Map).cast<String, dynamic>()).toList();
  List<List<int>> get binary => sent.whereType<List<int>>().toList();
  void server(Map<String, Object?> m) => ctl.add(jsonEncode(m));
}

class FakeSink implements PcmSink {
  final fed = <int>[];
  int flushes = 0;
  @override
  Future<Duration> feed(Uint8List pcm, int sampleRate) async {
    fed.add(pcm.length);
    return Duration.zero;
  }

  @override
  Future<void> flush() async => flushes++;
}

Future<void> tick([int ms = 0]) => Future<void>.delayed(Duration(milliseconds: ms));

void main() {
  late FakeTransport t;
  late FakeSink sink;
  late List<InterpState> states;
  late List<Caption> caps;
  late List<String> errors;
  late List<bool> playback;
  Uri? openedUri;
  String? openedToken;

  InterpretClient make({TransportOpener? opener}) => InterpretClient(
        uri: Uri.parse('ws://x/api/interpret'),
        token: 'tok',
        lang: 'zh',
        traditional: true,
        sink: sink,
        resumeAfter: const Duration(milliseconds: 20),
        opener: opener ??
            (uri, token) async {
              openedUri = uri;
              openedToken = token;
              return t;
            },
        cb: InterpCallbacks(
          onState: states.add,
          onCaption: caps.add,
          onError: (k, m) => errors.add('${k.name}:$m'),
          onPlayback: playback.add,
        ),
      );

  setUp(() {
    t = FakeTransport();
    sink = FakeSink();
    states = [];
    caps = [];
    errors = [];
    playback = [];
  });

  test('연결하면 토큰으로 열고 첫 텍스트 = start{lang, traditional}', () async {
    final c = make();
    await c.connect();
    expect(openedUri.toString(), 'ws://x/api/interpret');
    expect(openedToken, 'tok');
    expect(t.json.first, {'type': 'start', 'lang': 'zh', 'traditional': true});
    expect(c.state, InterpState.connecting);
  });

  test('ready 전에는 마이크 조각을 안 보내고, ready 뒤 보낸다', () async {
    final c = make();
    await c.connect();
    expect(c.sendPcm(Uint8List(1280)), isFalse);
    t.server({'type': 'ready'});
    await tick();
    expect(states.last, InterpState.listening);
    expect(c.sendPcm(Uint8List(1280)), isTrue);
    expect(t.binary.single, hasLength(1280));
  });

  test('caption — 같은 id 는 같은 key(덮어쓰기) · side me/them', () async {
    final c = make();
    await c.connect();
    t.server({'type': 'caption', 'id': 7, 'side': 'them', 'original': '你好', 'translation': '안녕', 'final': false});
    t.server({'type': 'caption', 'id': 7, 'side': 'them', 'original': '你好嗎', 'translation': '안녕하세요', 'final': true});
    t.server({'type': 'caption', 'id': 8, 'side': 'me', 'original': '네', 'translation': '是', 'final': true});
    await tick();
    expect(caps.map((x) => x.key).toSet(), hasLength(2));
    expect(caps[0].key, caps[1].key);
    expect(caps[1].isFinal, isTrue);
    expect(caps[2].side, 'me');
    expect(c.state, isNot(InterpState.error));
  });

  test('번역 음성 재생 중(audio_start ~ 끝 + 여유)에는 마이크를 막는다 · 홀수 바이트 이어 붙이기', () async {
    final c = make();
    await c.connect();
    t.server({'type': 'ready'});
    t.server({'type': 'audio_start', 'id': 1, 'sampleRate': 24000});
    await tick();
    expect(playback, [true]);
    expect(c.sendPcm(Uint8List(1280)), isFalse);
    t.ctl.add(Uint8List(481)); // 홀수 — 1바이트는 다음 조각과
    t.ctl.add(Uint8List(481));
    await tick();
    expect(sink.fed, [480, 482]);
    t.server({'type': 'audio_end', 'id': 1});
    await tick(5);
    expect(c.speaking, isTrue); // 962바이트 = 20ms 재생 + 20ms 여유
    await tick(80);
    expect(c.speaking, isFalse);
    expect(playback, [true, false]);
    expect(c.sendPcm(Uint8List(1280)), isTrue);
  });

  test('pause/resume/stop 메시지 · 멈춤이면 재생 큐 비움', () async {
    final c = make();
    await c.connect();
    t.server({'type': 'ready'});
    await tick();
    c.toggle();
    expect(c.state, InterpState.paused);
    expect(c.sendPcm(Uint8List(1280)), isFalse);
    c.toggle();
    expect(c.state, InterpState.listening);
    await c.close();
    expect(t.json.map((m) => m['type']), ['start', 'pause', 'resume', 'stop']);
    expect(sink.flushes, greaterThanOrEqualTo(2));
    expect(t.closed, isTrue);
  });

  test('error 프레임 → 오류 상태 · 연결 닫음', () async {
    final c = make();
    await c.connect();
    t.server({'type': 'error', 'code': 'no_api_key', 'message': '통역 키가 없어요'});
    await tick();
    expect(c.state, InterpState.error);
    expect(errors.single, 'server:통역 키가 없어요');
    expect(t.closed, isTrue);
  });

  test('서버가 끊으면 closed 오류', () async {
    final c = make();
    await c.connect();
    await t.ctl.close();
    await tick();
    expect(c.state, InterpState.error);
    expect(errors.single, startsWith('closed:'));
  });

  test('핸드셰이크 403(토큰 거절) → auth 오류', () async {
    final c = make(opener: (_, _) async => throw const WebSocketException('Connection was not upgraded to websocket, HTTP status code: 403'));
    await c.connect();
    expect(c.state, InterpState.error);
    expect(errors.single, startsWith('auth:'));
  });

  test('마이크 조각은 40ms(1280바이트)로 다시 자른다', () {
    final ch = Chunker();
    expect(ch.add(Uint8List(1000)), isEmpty);
    final out = ch.add(Uint8List(2000));
    expect(out.map((e) => e.length), [1280, 1280]);
    expect(ch.add(Uint8List(840)).map((e) => e.length), [1280]);
  });

  group('언어', () {
    test('국적 → 자동 언어 · 번체', () {
      expect(autoLang('TW').code, 'zh');
      expect(autoLang('TW').traditional, isTrue);
      expect(autoLang('CN').traditional, isFalse);
      expect(autoLang('JP').code, 'ja');
      expect(autoLang('KR').code, 'en');
      expect(autoLang(null).code, 'en');
      expect(autoLang('DE').code, 'en');
    });
    test('빠른 말하기 6개 × 언어 9 키 모두 있음', () {
      expect(phrases, hasLength(6));
      for (final p in phrases) {
        for (final k in ['zhTW', 'zhCN', 'en', 'ja', 'th', 'fr', 'es', 'tl', 'hi']) {
          expect(p.tr[k], isNotNull, reason: '${p.ko} $k');
        }
      }
      expect(phraseKey('zh', true), 'zhTW');
      expect(ttsLocale('tl', false), 'fil-PH');
    });
  });
}
