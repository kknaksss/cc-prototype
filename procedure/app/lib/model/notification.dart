// 알림(SPEC-004 §5-4) — 종류 둘뿐(doctor_call · counselor_call). display 는 목록 밖
import 'board.dart' show Json;

int? _int(Object? v) => v is num ? v.toInt() : null;

class AppNotification {
  final int id;
  final String kind; // doctor_call | counselor_call
  final String title;
  final String body;
  final String createdAt;
  final String? readAt;
  final int? visitId;
  final int? callId; // 후속 #4
  final int? reservationId;
  const AppNotification({
    required this.id,
    required this.kind,
    required this.title,
    required this.body,
    required this.createdAt,
    this.readAt,
    this.visitId,
    this.callId,
    this.reservationId,
  });

  bool get unread => readAt == null;

  factory AppNotification.fromJson(Json j) {
    final t = j['target'] is Map ? (j['target'] as Map).cast<String, dynamic>() : const <String, dynamic>{};
    return AppNotification(
      id: _int(j['id']) ?? 0,
      kind: '${j['kind'] ?? ''}',
      title: '${j['title'] ?? ''}',
      body: '${j['body'] ?? ''}',
      createdAt: '${j['createdAt'] ?? ''}',
      readAt: j['readAt'] as String?,
      visitId: _int(t['visitId']),
      callId: _int(t['callId']),
      reservationId: _int(t['reservationId']),
    );
  }
}

// GET /api/notifications → {unread, items}. 모르는 kind 는 버린다(목록 = 둘만)
class NotificationList {
  final int unread;
  final List<AppNotification> items;
  const NotificationList(this.unread, this.items);

  factory NotificationList.fromJson(Json j) => NotificationList(
        _int(j['unread']) ?? 0,
        [
          for (final e in (j['items'] is List ? j['items'] as List : const []))
            if (e is Map) AppNotification.fromJson(e.cast<String, dynamic>()),
        ].where((n) => n.kind == 'doctor_call' || n.kind == 'counselor_call').toList(),
      );
}

// 설정(§5-4) — 그 역할이 받는 종류만 · 이름
const notifKindName = {'doctor_call': '원장 호출', 'counselor_call': '상담사 호출'};

class NotifSetting {
  final String kind;
  final bool enabled;
  const NotifSetting(this.kind, this.enabled);

  static List<NotifSetting> listFrom(Json j) => [
        for (final e in (j['items'] is List ? j['items'] as List : const []))
          if (e is Map && notifKindName.containsKey(e['kind'])) NotifSetting('${e['kind']}', e['enabled'] != false),
      ];
}
