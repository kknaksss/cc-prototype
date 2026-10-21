// 시각 표시 — 웹 lib/time.ts 와 같다. 화면 시각은 KST(기기 시간대와 상관없이)
String pad2(int n) => n.toString().padLeft(2, '0');

int? toMs(String? v) {
  if (v == null || v.isEmpty) return null;
  return DateTime.tryParse(v)?.millisecondsSinceEpoch;
}

const _kst = 9 * 3600 * 1000;

String hmMs(int? t) {
  if (t == null) return '';
  final d = DateTime.fromMillisecondsSinceEpoch(t + _kst, isUtc: true);
  return '${pad2(d.hour)}:${pad2(d.minute)}';
}

String hm(String? v) => hmMs(toMs(v));

// 지난 분(내림)
int minutesSince(String? since, int now) {
  final t = toMs(since);
  if (t == null) return 0;
  final m = (now - t) ~/ 60000;
  return m < 0 ? 0 : m;
}

// 경과 mm:ss(한 시간 넘으면 h:mm:ss)
String elapsed(String? since, int now) {
  final t = toMs(since);
  if (t == null) return '';
  var s = (now - t) ~/ 1000;
  if (s < 0) s = 0;
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = s % 60;
  return h > 0 ? '$h:${pad2(m)}:${pad2(sec)}' : '${pad2(m)}:${pad2(sec)}';
}

String mmss(Duration d) => '${pad2(d.inMinutes)}:${pad2(d.inSeconds % 60)}';
