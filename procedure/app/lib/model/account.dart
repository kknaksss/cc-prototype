// 계정 · 로그인 모양(SPEC-004 §3.3) — GET /api/auth/accounts · POST /api/auth/login · GET /api/auth/me
import 'board.dart' show Json;

enum Role { admin, doctor, nurse }

Role roleOf(Object? v) => switch (v) {
      'doctor' => Role.doctor,
      'nurse' => Role.nurse,
      _ => Role.admin,
    };

// 로그인 카드
class AccountCard {
  final String id; // login_id
  final String name;
  final String label;
  final Role role;
  const AccountCard({required this.id, required this.name, required this.label, required this.role});
  factory AccountCard.fromJson(Json j) => AccountCard(
        id: '${j['id'] ?? ''}',
        name: '${j['name'] ?? ''}',
        label: '${j['label'] ?? ''}',
        role: roleOf(j['role']),
      );
}

// 로그인한 계정 — 토큰과 함께 기기에 저장
class Session {
  final String token;
  final String id;
  final Role role;
  final String name;
  final int? staffId;
  const Session({required this.token, required this.id, required this.role, required this.name, this.staffId});

  bool get isDoctor => role == Role.doctor;
  bool get isAdmin => role == Role.admin;

  factory Session.fromJson(Json j, {String? token}) => Session(
        token: token ?? '${j['token'] ?? ''}',
        id: '${j['id'] ?? ''}',
        role: roleOf(j['role']),
        name: '${j['name'] ?? j['id'] ?? ''}',
        staffId: j['staffId'] is num ? (j['staffId'] as num).toInt() : null,
      );

  Json toJson() => {'token': token, 'id': id, 'role': role.name, 'name': name, 'staffId': staffId};
}
