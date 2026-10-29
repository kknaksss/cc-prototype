// 채팅 화면 규칙(순수 함수 · 시험) — 방 이름 · 미리보기(§4.5) · 시각 글자(§10.0) · 이름 묶기(§10.4) · 입력 한도(§5) · clientId(§10.5)
import 'dart:math';

import 'package:flutter/services.dart';

import 'chat_model.dart';

// 안 읽음 수 글자 — 99 넘으면 「99+」(S4§5-4 와 같게)
String countText(int n) => n > 99 ? '99+' : '$n';

// 방 이름 — 그룹 = back 이 만든 이름(이름 없는 그룹 = 보는 사람 뺀 나열) · 1:1 = 상대 이름(「(비활성)」은 화면이 따로 붙임)
String roomTitle(Room r) => r.group ? r.name : (r.peer?.name ?? r.name);

// 1:1 상대가 비활성(D9-14 · D9-42)
bool peerInactive(Room r) => !r.group && r.peer != null && !r.peer!.active;

// 미리보기 한 줄(§4.5) — (앞붙임, 본문, 첨부 아이콘 종류). 1:1 상대 = 본문 · 내 것 = 「나: 」 · 그룹 = 「<보낸 사람>: 」 ·
// 사진 = 아이콘 + 「사진」 · 동영상 = 아이콘 + 「동영상」(r3) · 지운 것 = 「삭제된 메시지예요」(1:1 은 앞붙임 없음) · 시스템 줄 = 문구 그대로 ·
// 고친 글 = 고친 본문(「수정됨」 없음 · OQ-951)
({String prefix, String body, MsgKind? media}) previewOf(Room r) {
  final p = r.lastMessage;
  if (p == null) return (prefix: '', body: '', media: null);
  if (p.kind == MsgKind.system) return (prefix: '', body: p.text ?? '', media: null);
  final who = p.mine ? '나: ' : (r.group ? '${p.senderName}: ' : '');
  if (p.deleted) return (prefix: r.group ? who : '', body: '삭제된 메시지예요', media: null);
  if (p.kind == MsgKind.photo) return (prefix: who, body: '사진', media: MsgKind.photo);
  if (p.kind == MsgKind.video) return (prefix: who, body: '동영상', media: MsgKind.video);
  return (prefix: who, body: (p.text ?? '').replaceAll('\n', ' '), media: null);
}

// ─── 시각 글자(KST) — 받은 ISO 가 어느 오프셋이든 KST 벽시계로 읽는다
DateTime? kst(String? iso) {
  if (iso == null || iso.isEmpty) return null;
  final t = DateTime.tryParse(iso);
  if (t == null) return null;
  final u = t.toUtc().add(const Duration(hours: 9));
  return DateTime(u.year, u.month, u.day, u.hour, u.minute, u.second, u.millisecond);
}

DateTime kstNow([DateTime? now]) => kst((now ?? DateTime.now()).toUtc().toIso8601String())!;

String _two(int n) => n.toString().padLeft(2, '0');
const _weekday = ['월', '화', '수', '목', '금', '토', '일'];

// 방 목록 — 오늘 「HH:MM」 · 어제 「어제」 · 올해 「M. D」 · 그 전 「YYYY. M. D」
String listTime(String? iso, {DateTime? now}) {
  final t = kst(iso);
  if (t == null) return '';
  final n = kstNow(now);
  final today = DateTime(n.year, n.month, n.day);
  final day = DateTime(t.year, t.month, t.day);
  if (day == today) return '${_two(t.hour)}:${_two(t.minute)}';
  if (day == today.subtract(const Duration(days: 1))) return '어제';
  if (t.year == n.year) return '${t.month}. ${t.day}';
  return '${t.year}. ${t.month}. ${t.day}';
}

// 말풍선 「HH:MM」
String bubbleTime(String? iso) {
  final t = kst(iso);
  return t == null ? '' : '${_two(t.hour)}:${_two(t.minute)}';
}

// 날짜 구분선 「M월 D일 (요일)」
String dayLabel(String? iso) {
  final t = kst(iso);
  return t == null ? '' : '${t.month}월 ${t.day}일 (${_weekday[t.weekday - 1]})';
}

// 크게 보기 「M월 D일 HH:MM」
String viewerTime(String? iso) {
  final t = kst(iso);
  return t == null ? '' : '${t.month}월 ${t.day}일 ${_two(t.hour)}:${_two(t.minute)}';
}

bool sameDay(String? a, String? b) {
  final x = kst(a), y = kst(b);
  return x != null && y != null && x.year == y.year && x.month == y.month && x.day == y.day;
}

// 그룹 — 남의 말풍선 위 보낸 사람 이름. 같은 사람이 연달아 보내면 첫 번째만(사이에 시스템 줄 · 날짜 구분선이 끼면 다시)
bool showSenderName({required bool group, required ChatMessage cur, ChatMessage? prev, required bool mine}) {
  if (!group || mine || cur.kind == MsgKind.system) return false;
  if (prev == null || prev.kind == MsgKind.system) return true;
  if (prev.sender.id != cur.sender.id) return true;
  return !sameDay(prev.createdAt, cur.createdAt);
}

// 2000 코드 포인트(§5 — Flutter maxLength 는 글자 묶음으로 세어 이모지에서 갈린다)
const maxMessageRunes = 2000;

class RuneLimitFormatter extends TextInputFormatter {
  final int max;
  const RuneLimitFormatter([this.max = maxMessageRunes]);
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) {
    if (newValue.text.runes.length <= max) return newValue;
    final cut = String.fromCharCodes(newValue.text.runes.take(max));
    return TextEditingValue(text: cut, selection: TextSelection.collapsed(offset: cut.length));
  }
}

// clientId = UUID v4(36자 · OQ-937)
final _rnd = Random.secure();
String newClientId() {
  final b = List<int>.generate(16, (_) => _rnd.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
}

// 배너 · 푸시 본문 앞부분(§8 · §10.12) — 앞 100자 · 넘으면 「…」 · 줄바꿈은 공백
String bodyHead(ChatMessage m) {
  if (m.kind == MsgKind.photo) return '사진';
  if (m.kind == MsgKind.video) return '동영상';
  final t = (m.text ?? '').replaceAll('\n', ' ');
  return t.runes.length > 100 ? '${String.fromCharCodes(t.runes.take(100))}…' : t;
}

// 동영상 길이 「m:ss」(말풍선 · 최근 줄 · 재생 막대 — OQ-953)
String durationText(int ms) {
  final s = (ms / 1000).round();
  return '${s ~/ 60}:${_two(s % 60)}';
}

// 텍스트 안 링크(D9-46 · r3 U-3) — `http://` · `https://` 뒤 ASCII 주소 문자만(한글 · 공백에서 끊음) ·
// 끝 문장부호 `.,)!?'"` 는 링크에서 뺀다(「」』 는 ASCII 밖이라 이미 끊김). `www.` · 메일은 글자 그대로
final _link = RegExp(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+");
const _trailing = '.,)!?\'"';

List<({int start, int end})> findLinks(String text) {
  final out = <({int start, int end})>[];
  for (final m in _link.allMatches(text)) {
    var end = m.end;
    while (end > m.start && _trailing.contains(text[end - 1])) {
      end--;
    }
    final scheme = text.startsWith('https', m.start) ? 8 : 7;
    if (end - m.start > scheme) out.add((start: m.start, end: end));
  }
  return out;
}
