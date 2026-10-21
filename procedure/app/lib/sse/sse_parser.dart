// SSE 파서(SPEC-004 §7.1) — UTF-8 줄 단위 · 빈 줄 = 이벤트 끝.
// `event:` · `id:` · `data:`(여러 줄이면 \n 으로 이음) · `retry:`(ms) · `:` 로 시작 = 주석(ping) 무시.
// 조각(chunk)이 줄 중간에서 끊겨 와도 된다 — 남은 글자는 다음 조각과 잇는다.
import 'dart:convert';

class SseEvent {
  final String event; // 없으면 message
  final String data;
  final String? id;
  const SseEvent(this.event, this.data, {this.id});
  @override
  String toString() => 'SseEvent($event, $data)';
}

class SseParser {
  // retry: 값이 오면 부른다(재연결 간격)
  final void Function(int ms)? onRetry;
  SseParser({this.onRetry});

  final _decoder = const Utf8Decoder(allowMalformed: true);
  String _buf = '';
  String? _event;
  String? _id;
  final List<String> _data = [];
  bool _pendingCr = false;

  // 문자열 조각을 넣는다 — 끝난 이벤트들을 돌려준다
  List<SseEvent> addText(String chunk) {
    final out = <SseEvent>[];
    var text = _buf + chunk;
    _buf = '';
    // \r\n 이 두 조각에 걸칠 때 — 앞 조각 끝 \r 를 이미 줄 끝으로 처리했으면 이어 오는 \n 은 건너뛴다
    if (_pendingCr && text.startsWith('\n')) text = text.substring(1);
    _pendingCr = false;
    var start = 0;
    for (var i = 0; i < text.length; i++) {
      final ch = text.codeUnitAt(i);
      if (ch == 0x0A || ch == 0x0D) {
        _line(text.substring(start, i), out);
        if (ch == 0x0D) {
          if (i + 1 < text.length) {
            if (text.codeUnitAt(i + 1) == 0x0A) i++;
          } else {
            _pendingCr = true;
          }
        }
        start = i + 1;
      }
    }
    _buf = text.substring(start);
    return out;
  }

  // 바이트 조각 — 여러 바이트 글자가 조각 경계에 걸쳐도 되게 디코더 상태를 이어 간다
  late final _byteSink = _ChunkedUtf8(_decoder);
  List<SseEvent> addBytes(List<int> bytes) => addText(_byteSink.add(bytes));

  void _line(String line, List<SseEvent> out) {
    if (line.isEmpty) {
      _dispatch(out);
      return;
    }
    if (line.startsWith(':')) return; // 주석 · ping
    final colon = line.indexOf(':');
    final field = colon < 0 ? line : line.substring(0, colon);
    var value = colon < 0 ? '' : line.substring(colon + 1);
    if (value.startsWith(' ')) value = value.substring(1);
    switch (field) {
      case 'event':
        _event = value;
      case 'data':
        _data.add(value);
      case 'id':
        _id = value;
      case 'retry':
        final ms = int.tryParse(value);
        if (ms != null && ms >= 0) onRetry?.call(ms);
    }
  }

  void _dispatch(List<SseEvent> out) {
    if (_data.isNotEmpty) out.add(SseEvent(_event ?? 'message', _data.join('\n'), id: _id));
    _data.clear();
    _event = null;
  }
}

// 바이트 → 문자열, 끝이 잘린 UTF-8 글자는 다음 조각까지 들고 있는다
class _ChunkedUtf8 {
  final Utf8Decoder decoder;
  _ChunkedUtf8(this.decoder);
  final List<int> _rest = [];

  String add(List<int> bytes) {
    final all = [..._rest, ...bytes];
    _rest.clear();
    // 끝에서 덜 온 글자 바이트 수를 센다
    var cut = all.length;
    for (var back = 1; back <= 3 && back <= all.length; back++) {
      final b = all[all.length - back];
      if (b & 0xC0 == 0x80) continue; // 이어지는 바이트
      final need = b >= 0xF0 ? 4 : b >= 0xE0 ? 3 : b >= 0xC0 ? 2 : 1;
      if (need > back) cut = all.length - back;
      break;
    }
    _rest.addAll(all.sublist(cut));
    return decoder.convert(all.sublist(0, cut));
  }
}
