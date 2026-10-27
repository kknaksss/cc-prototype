// 계정 · 로그인 모양(SPEC-004 §3.3) — POST /api/auth/login {id, password} · GET /api/auth/me
import 'board.dart' show Json;

// 역할 다섯(SPEC-004 §3.4 0.4.0) — 탭 · 버튼은 역할로 숨기지 않는다(D7-11 · D7-24). 갈림 = 수락 · 받는 알림뿐
enum Role { admin, doctor, nurse, coordinator, counselor }

Role roleOf(Object? v) => switch (v) {
      'doctor' => Role.doctor,
      'nurse' => Role.nurse,
      'coordinator' => Role.coordinator,
      'counselor' => Role.counselor,
      _ => Role.admin,
    };

// 설정 「계정」 칸 역할 이름(§6.14)
const roleName = {
  Role.admin: '관리자',
  Role.doctor: '의사',
  Role.nurse: '간호사',
  Role.coordinator: '코디',
  Role.counselor: '상담사',
};

// 로그인한 계정 — 토큰과 함께 기기에 저장
class Session {
  final String token;
  final String id;
  final Role role;
  final String name;
  final int? staffId;
  const Session({required this.token, required this.id, required this.role, required this.name, this.staffId});

  bool get isDoctor => role == Role.doctor;
  // 수락 = 관리자 묶음(admin · coordinator · counselor) — 원장을 골라 doctorId 필수(§3.4 · D7-23 · back accept() 분기와 같음)
  bool get isAdmin => role == Role.admin || role == Role.coordinator || role == Role.counselor;

  factory Session.fromJson(Json j, {String? token}) => Session(
        token: token ?? '${j['token'] ?? ''}',
        id: '${j['id'] ?? ''}',
        role: roleOf(j['role']),
        name: '${j['name'] ?? j['id'] ?? ''}',
        staffId: j['staffId'] is num ? (j['staffId'] as num).toInt() : null,
      );

  Json toJson() => {'token': token, 'id': id, 'role': role.name, 'name': name, 'staffId': staffId};
}
