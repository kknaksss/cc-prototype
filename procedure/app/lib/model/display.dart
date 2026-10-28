// 띄우기 요청(SPEC-004 §5-3 · 코디 확정 2026-10-27) — pending · claim 항목 = SSE display 와 같은 키 + 상태 · 만료
import 'board.dart' show Json;

int? _i(Object? v) => v is num ? v.toInt() : (v is String ? int.tryParse(v) : null);

class DisplayReq {
  final int requestId;
  final String kind; // questionnaire | scan
  final int reservationId;
  final int? customerId;
  final int? deviceId;
  final String status; // pending | opened | done | canceled | expired
  final String? expiresAt;
  const DisplayReq({required this.requestId, required this.kind, required this.reservationId, this.customerId, this.deviceId, this.status = 'pending', this.expiresAt});

  static DisplayReq? fromJson(Object? v) {
    if (v is! Map) return null;
    final j = v.cast<String, dynamic>();
    final id = _i(j['requestId']);
    final r = _i(j['reservationId']);
    final k = j['kind'];
    if (id == null || r == null || (k != 'questionnaire' && k != 'scan')) return null;
    return DisplayReq(
      requestId: id,
      kind: k as String,
      reservationId: r,
      customerId: _i(j['customerId']),
      deviceId: _i(j['deviceId']),
      status: '${j['status'] ?? 'pending'}',
      expiresAt: j['expiresAt'] as String?,
    );
  }

  static List<DisplayReq> listFrom(Json j) => [
        for (final e in (j['items'] is List ? j['items'] as List : const [])) ?DisplayReq.fromJson(e),
      ];
}

// QR 내용 = ccc://display?t=<qrToken> 만 받는다(§5-3) — 그 밖은 null
String? qrTokenOf(String? raw) {
  final u = Uri.tryParse((raw ?? '').trim());
  if (u == null || u.scheme != 'ccc' || u.host != 'display') return null;
  final t = u.queryParameters['t'];
  return t == null || t.isEmpty ? null : t;
}

// SSE display 프레임이 이 기기 것인가(§5-3 ① · 허브가 기기 단위로 보내도 한 번 더 본다)
bool isMyDisplay(Map<String, dynamic> data, int? myDeviceId) {
  if (myDeviceId == null) return false;
  final d = _i(data['deviceId']);
  return d == myDeviceId;
}
