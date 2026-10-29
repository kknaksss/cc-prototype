// 채팅 모양(SPEC-007 §6.1) — back 응답 · SSE 페이로드 그대로. 모르는 필드는 무시(S4§7.2). 시각 = KST 오프셋 · 밀리초 ISO 문자열
import 'dart:typed_data';

import '../model/account.dart' show Role, roleOf, roleName;
import '../model/board.dart' show Json;

int? _int(Object? v) => v is num ? v.toInt() : (v is String ? int.tryParse(v) : null);
String? _str(Object? v) => v is String ? v : null;
Json _map(Object? v) => v is Map ? v.cast<String, dynamic>() : const {};

// 상대 후보(GET /api/chat/people) — {id, name, role}
class Person {
  final int id;
  final String name;
  final Role role;
  const Person(this.id, this.name, this.role);
  factory Person.fromJson(Json j) => Person(_int(j['id']) ?? 0, '${j['name'] ?? ''}', roleOf(j['role']));
  String get roleText => roleName[role]!;
}

// 방 멤버(지금 멤버만 · 「나」 맨 위) — {id, name, role, active, me}
class Member {
  final int id;
  final String name;
  final Role role;
  final bool active;
  final bool me;
  const Member(this.id, this.name, this.role, {this.active = true, this.me = false});
  factory Member.fromJson(Json j) =>
      Member(_int(j['id']) ?? 0, '${j['name'] ?? ''}', roleOf(j['role']), active: j['active'] != false, me: j['me'] == true);
}

enum MsgKind { text, photo, system }

MsgKind msgKindOf(Object? v) => switch (v) {
      'photo' => MsgKind.photo,
      'system' => MsgKind.system,
      _ => MsgKind.text,
    };

// 방 목록 미리보기(마지막 메시지) — {id, senderId, senderName, mine, kind, text|null, deleted, createdAt}
class Preview {
  final int id;
  final int senderId;
  final String senderName;
  final bool mine;
  final MsgKind kind;
  final String? text;
  final bool deleted;
  final String createdAt;
  const Preview(
      {required this.id,
      required this.senderId,
      required this.senderName,
      required this.mine,
      required this.kind,
      this.text,
      this.deleted = false,
      required this.createdAt});
  factory Preview.fromJson(Json j) => Preview(
        id: _int(j['id']) ?? 0,
        senderId: _int(j['senderId']) ?? 0,
        senderName: '${j['senderName'] ?? ''}',
        mine: j['mine'] == true,
        kind: msgKindOf(j['kind']),
        text: _str(j['text']),
        deleted: j['deleted'] == true,
        createdAt: '${j['createdAt'] ?? ''}',
      );
  // SSE chat_message 로 받은 메시지 → 방 목록 미리보기(본문 앞 100자 — §4.5)
  factory Preview.of(ChatMessage m, {required bool mine}) => Preview(
        id: m.id,
        senderId: m.sender.id,
        senderName: m.sender.name,
        mine: mine,
        kind: m.kind,
        text: m.text == null ? null : String.fromCharCodes(m.text!.runes.take(100)),
        deleted: m.deleted,
        createdAt: m.createdAt,
      );
  Preview asDeleted() =>
      Preview(id: id, senderId: senderId, senderName: senderName, mine: mine, kind: kind, deleted: true, createdAt: createdAt);
}

// 방(보는 계정 기준 — name · muted · unread · members[].me 가 계정마다 다름)
class Room {
  final int id;
  final bool group;
  final String? title;
  final String name;
  final List<Member> members;
  final int memberCount;
  bool muted;
  int unread;
  Preview? lastMessage;
  String? lastMessageAt;
  final String createdAt;
  Room({
    required this.id,
    required this.group,
    this.title,
    required this.name,
    this.members = const [],
    required this.memberCount,
    this.muted = false,
    this.unread = 0,
    this.lastMessage,
    this.lastMessageAt,
    required this.createdAt,
  });
  factory Room.fromJson(Json j) {
    final members = [for (final m in (j['members'] is List ? j['members'] as List : const [])) if (m is Map) Member.fromJson(m.cast<String, dynamic>())];
    return Room(
      id: _int(j['id']) ?? 0,
      group: j['kind'] == 'group',
      title: _str(j['title']),
      name: '${j['name'] ?? ''}',
      members: members,
      memberCount: _int(j['memberCount']) ?? members.length,
      muted: j['muted'] == true,
      unread: _int(j['unread']) ?? 0,
      lastMessage: j['lastMessage'] is Map ? Preview.fromJson(_map(j['lastMessage'])) : null,
      lastMessageAt: _str(j['lastMessageAt']),
      createdAt: '${j['createdAt'] ?? ''}',
    );
  }
  // 1:1 상대(나 아닌 멤버)
  Member? get peer => group ? null : members.where((m) => !m.me).firstOrNull;
  Member? get me => members.where((m) => m.me).firstOrNull;
  // 정렬 기준 — 마지막 메시지(없으면 만든 때)
  String get sortAt => lastMessageAt ?? createdAt;
}

class Sender {
  final int id;
  final String name;
  final Role role;
  final bool active;
  const Sender(this.id, this.name, this.role, {this.active = true});
  factory Sender.fromJson(Json j) => Sender(_int(j['id']) ?? 0, '${j['name'] ?? ''}', roleOf(j['role']), active: j['active'] != false);
}

class PhotoRef {
  final int id;
  final int width;
  final int height;
  const PhotoRef(this.id, this.width, this.height);
}

// 메시지 — {id, roomId, clientId|null, sender, kind, text|null, photo|null, createdAt, updatedAt, deletedAt|null}
class ChatMessage {
  final int id;
  final int roomId;
  final String? clientId;
  final Sender sender;
  final MsgKind kind;
  final String? text;
  final PhotoRef? photo;
  final String createdAt;
  final String updatedAt;
  final String? deletedAt;
  const ChatMessage({
    required this.id,
    required this.roomId,
    this.clientId,
    required this.sender,
    required this.kind,
    this.text,
    this.photo,
    required this.createdAt,
    required this.updatedAt,
    this.deletedAt,
  });
  factory ChatMessage.fromJson(Json j) {
    final p = j['photo'];
    return ChatMessage(
      id: _int(j['id']) ?? 0,
      roomId: _int(j['roomId']) ?? 0,
      clientId: _str(j['clientId']),
      sender: Sender.fromJson(_map(j['sender'])),
      kind: msgKindOf(j['kind']),
      text: _str(j['text']),
      photo: p is Map ? PhotoRef(_int(p['id']) ?? 0, _int(p['width']) ?? 0, _int(p['height']) ?? 0) : null,
      createdAt: '${j['createdAt'] ?? ''}',
      updatedAt: '${j['updatedAt'] ?? j['createdAt'] ?? ''}',
      deletedAt: _str(j['deletedAt']),
    );
  }
  bool get deleted => deletedAt != null;
  // SSE chat_message_deleted — 지운 자리(text · photo 없음 · updatedAt 올림)
  ChatMessage asDeleted(String at) => ChatMessage(
      id: id, roomId: roomId, clientId: clientId, sender: sender, kind: kind, createdAt: createdAt, updatedAt: at, deletedAt: at);
}

// 보내는 중 · 실패 말풍선(§10.5) — 기기에 저장하지 않는다(D9-41). 사진은 고른 바이트를 그대로 보여 준다
enum SendState { sending, failed }

class PendingMessage {
  final String clientId;
  final int roomId;
  final String? text;
  final Uint8List? photoBytes;
  final int width, height;
  int? photoId; // 올리기 끝남 — 다시 보내기는 보내기만(§10.6)
  SendState state = SendState.sending;
  double? progress; // 사진 올리는 중 0 ~ 1
  final DateTime at;
  PendingMessage({required this.clientId, required this.roomId, this.text, this.photoBytes, this.width = 0, this.height = 0, DateTime? at})
      : at = at ?? DateTime.now();
  bool get isPhoto => photoBytes != null;
}

// 앞에서 받은 채팅 · SSE 로 만든 앱 안 배너 한 개(§10.12)
class ChatBanner {
  final int roomId;
  final int messageId;
  final String title; // 1:1 = 보낸 사람 · 그룹 = 「보낸 사람 · 방 이름」
  final String body; // 본문 앞부분 · 사진 = 「사진」
  const ChatBanner(this.roomId, this.messageId, this.title, this.body);
  String get line => '$title — $body';
}
