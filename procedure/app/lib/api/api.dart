// back REST — 이 모듈에서만 부른다(SPEC-003 §7 · SPEC-004 §3.3). 오류 본문 = {error:{code,message}}
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart' show Uint8List;
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;

import '../model/account.dart';
import '../model/board.dart' show Json;
import '../model/display.dart';
import '../model/reservation.dart';

class ApiError implements Exception {
  final int status;
  final String code;
  final String message;
  const ApiError(this.status, this.code, this.message);
  @override
  String toString() => 'ApiError($status $code: $message)';
}

typedef CallTarget = ({String kind, int? doctorId});

class Api {
  final String Function() base;
  final String? Function() token;
  final http.Client client;
  Api({required this.base, required this.token, http.Client? client}) : client = client ?? http.Client();

  static const _timeout = Duration(seconds: 12);

  Future<dynamic> _req(String method, String path, {Object? body, bool auth = true, Map<String, String>? extra, String? bearer}) async {
    final headers = <String, String>{'Accept': 'application/json', ...?extra};
    final t = bearer ?? token();
    if (auth && t != null) headers['Authorization'] = 'Bearer $t';
    if (body != null) headers['Content-Type'] = 'application/json';
    final uri = Uri.parse(base() + path);
    http.Response res;
    try {
      final req = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) req.body = jsonEncode(body);
      res = await http.Response.fromStream(await client.send(req).timeout(_timeout));
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    }
    dynamic data;
    try {
      data = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    } catch (_) {
      data = null;
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      final err = data is Map && data['error'] is Map ? data['error'] as Map : const {};
      throw ApiError(res.statusCode, '${err['code'] ?? 'error'}', '${err['message'] ?? '요청을 처리하지 못했어요'}');
    }
    return data;
  }

  Future<dynamic> _post(String path, [Object? body, Map<String, String>? extra]) => _req('POST', path, body: body, extra: extra);

  // §6.1 [연결 확인]
  Future<void> health() => _req('GET', '/api/health', auth: false);

  // 로그인 — 아이디 + 비밀번호(카드 없음 · 2026-10-21 사용자 결정). 실패 401 · 잠금 429 는 back message 를 그대로
  Future<Session> login(String id, String password) async {
    final data = await _req('POST', '/api/auth/login', body: {'id': id, 'password': password}, auth: false);
    return Session.fromJson((data as Map).cast<String, dynamic>());
  }

  // 앱 시작 때 — 아직 로그인 상태(session)가 없으므로 저장된 토큰을 직접 싣는다
  Future<Session> me(String tokenValue) async {
    final data = await _req('GET', '/api/auth/me', bearer: tokenValue);
    return Session.fromJson((data as Map).cast<String, dynamic>(), token: tokenValue);
  }

  // SPEC-003 §7.3 조작 8종 — 응답은 {ok…} 만. 화면은 뒤따르는 SSE board 로 바뀐다
  Future<void> anesStart(int visitId) => _post('/api/visits/$visitId/anesthesia/start');
  Future<void> anesEnd(int visitId) => _post('/api/visits/$visitId/anesthesia/end');
  Future<void> createCall(int visitId, List<int> procedureIds, CallTarget target) => _post('/api/visits/$visitId/calls', {
        'procedureIds': procedureIds,
        'target': target.kind == 'one' ? {'kind': 'one', 'doctorId': target.doctorId} : {'kind': 'all'},
      });
  // 의사 계정 = 자기 자신으로 수락 — doctorId 를 싣지 않는다(SPEC-004 §3.4 · A-07). back 이 JSON 본문을 요구해 빈 객체
  // 관리자 = 원장을 골라 doctorId 필수(웹 의국과 같음)
  Future<void> accept(int callId, {int? doctorId}) =>
      // X-Accept-Source: app — 앱 화면 [수락](알림 [수락] 은 push · back 기록용)
      _post('/api/calls/$callId/accept', doctorId == null ? const <String, Object>{} : {'doctorId': doctorId}, const {'X-Accept-Source': 'app'});
  Future<void> reassignAll(int callId) => _post('/api/calls/$callId/reassign-all');
  Future<void> startProcedure(int procedureId) => _post('/api/procedures/$procedureId/start');
  Future<void> finishProcedure(int procedureId) => _post('/api/procedures/$procedureId/finish');
  // [시작] · [종료] 되돌리기(SPEC-003 §5.13 · §7.3)
  Future<void> undoStart(int procedureId) => _post('/api/procedures/$procedureId/undo-start');
  Future<void> undoFinish(int procedureId) => _post('/api/procedures/$procedureId/undo-finish');
  Future<void> goHome(int visitId) => _post('/api/visits/$visitId/home');

  // §5-1.1 푸시 기기 토큰(16진) · 이름 · 배치 · 설치 단위 id → deviceId(§5-3 · 0.4.0 — 옛 back 은 없음 = null)
  // installId(E2E batch 1 #1) — 같은 설치의 옛 토큰 행을 back 이 새 토큰으로 바꿔 끼운다(행 하나)
  Future<int?> registerDevice(String deviceToken, {String? name, String? kind, String? installId}) async {
    final data = await _post('/api/devices', {'token': deviceToken, 'name': ?name, 'kind': ?kind, 'installId': ?installId});
    final id = data is Map ? data['deviceId'] : null;
    return id is num ? id.toInt() : null;
  }

  Future<void> unregisterDevice(String deviceToken) => _req('DELETE', '/api/devices/${Uri.encodeComponent(deviceToken)}');

  // §5-4 알림 목록 · 읽음 · 설정
  Future<Json> notifications() async => ((await _req('GET', '/api/notifications')) as Map).cast<String, dynamic>();
  // 읽음 — ids 없으면 전부 · 푸시를 눌러 열 때는 callId · reservationId 로(back 이 계정 + 발송으로 찾음 · 후속 #3)
  Future<void> readNotifications([List<int>? ids]) => _post('/api/notifications/read', ids == null ? const <String, Object>{} : {'ids': ids});
  Future<void> readNotificationOf({int? callId, int? reservationId}) =>
      _post('/api/notifications/read', {'callId': ?callId, 'reservationId': ?reservationId});
  Future<Json> notificationSettings() async =>
      ((await _req('GET', '/api/me/notification-settings')) as Map).cast<String, dynamic>();
  Future<void> setNotificationSetting(String kind, bool enabled) =>
      _req('PUT', '/api/me/notification-settings', body: {'kind': kind, 'enabled': enabled});

  // ─── 예약 현황(SPEC-005 §7.2 ~ §7.5 그대로 · SPEC-004 §6.10 ~ §6.12) — 수납 · 처방전 · 등록 · 이동 · 공지는 부르지 않는다
  Future<ResvBoard> reservationBoard(String date) async =>
      ResvBoard.fromJson(((await _req('GET', '/api/reservations/board?date=$date')) as Map).cast<String, dynamic>());
  Future<ResvDetail> reservation(int id) async =>
      ResvDetail.fromJson(((await _req('GET', '/api/reservations/$id')) as Map).cast<String, dynamic>());
  Future<void> cancelReservation(int id, String reason) => _post('/api/reservations/$id/cancel', {'reason': reason});
  Future<void> receive(int id, int roomId, String route) => _post('/api/reservations/$id/reception', {'roomId': roomId, 'route': route});
  Future<void> callCounselor(int id, int staffId) => _post('/api/reservations/$id/counselor-call', {'staffId': staffId});
  Future<void> addConsultation(int id) => _post('/api/reservations/$id/consultation-add');
  Future<void> discharge(int id) => _post('/api/reservations/$id/discharge');
  Future<void> saveMemo(int id, String memo) => _req('PUT', '/api/reservations/$id/memo', body: {'memo': memo});
  Future<void> saveRemark(int customerId, String memo) => _req('PUT', '/api/customers/$customerId/remark', body: {'memo': memo});
  Future<void> savePersonal(int customerId, Json personal) => _req('PUT', '/api/customers/$customerId/personal', body: {'personal': personal});
  Future<void> setIdentity(int customerId, String status) => _req('PUT', '/api/customers/$customerId/identity', body: {'status': status});

  // §5-3 띄우기 — 기기 목록 · 만들기(deviceId 없으면 QR 만)
  Future<List<DisplayTarget>> displayTargets() async {
    final d = await _req('GET', '/api/devices/targets');
    final l = d is List ? d : (d is Map ? d['items'] : null);
    return [for (final e in (l is List ? l : const [])) if (e is Map) DisplayTarget.fromJson(e.cast<String, dynamic>())];
  }

  Future<Json> createDisplay(int reservationId, String kind, {int? deviceId}) async =>
      ((await _post('/api/display-requests', {'reservationId': reservationId, 'kind': kind, 'deviceId': ?deviceId})) as Map).cast<String, dynamic>();

  // §5-3 이 기기 띄우기 — pending(deviceId 필수 · 돌려주며 opened) · QR claim · 닫기
  Future<List<DisplayReq>> pendingDisplays(int deviceId) async =>
      DisplayReq.listFrom(((await _req('GET', '/api/display-requests/pending?deviceId=$deviceId')) as Map).cast<String, dynamic>());
  Future<DisplayReq?> claimDisplay(String qrToken, {int? deviceId}) async =>
      DisplayReq.fromJson(await _post('/api/display-requests/claim', {'qrToken': qrToken, 'deviceId': ?deviceId}));
  Future<void> closeDisplay(int requestId, String status) => _post('/api/display-requests/$requestId/close', {'status': status});

  // 문진은 고객 폰 웹에서(SPEC-006) — 앱은 문진 API · unlock 을 부르지 않는다. 문진 띄우기 응답 = {id, qrToken: null, qrUrl, expiresAt}

  // §6.16 ④ 여권 스캔 저장 — multipart: fields(json · 바꿀 칸) · photo(JPEG) · reservationId · displayRequestId? · deviceId? · manual
  // 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 사진 바이트는 메모리에서 바로 요청 본문으로만(파일 · 캐시 없음)
  Future<Json> passportScan(int customerId,
      {required Json fields, Uint8List? photo, int? reservationId, int? displayRequestId, int? deviceId, bool manual = false}) async {
    final req = http.MultipartRequest('POST', Uri.parse('${base()}/api/customers/$customerId/passport-scan'));
    final t = token();
    req.headers['Accept'] = 'application/json';
    if (t != null) req.headers['Authorization'] = 'Bearer $t';
    req.fields['fields'] = jsonEncode(fields);
    if (reservationId != null) req.fields['reservationId'] = '$reservationId';
    if (displayRequestId != null) req.fields['displayRequestId'] = '$displayRequestId';
    if (deviceId != null) req.fields['deviceId'] = '$deviceId';
    req.fields['manual'] = manual ? 'true' : 'false';
    if (photo != null) req.files.add(http.MultipartFile.fromBytes('photo', photo, filename: 'scan.jpg', contentType: MediaType('image', 'jpeg')));
    http.Response res;
    try {
      res = await http.Response.fromStream(await client.send(req).timeout(const Duration(seconds: 40)));
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    }
    dynamic data;
    try {
      data = jsonDecode(utf8.decode(res.bodyBytes));
    } catch (_) {}
    if (res.statusCode < 200 || res.statusCode >= 300) {
      final err = data is Map && data['error'] is Map ? data['error'] as Map : const {};
      throw ApiError(res.statusCode, '${err['code'] ?? 'error'}', '${err['message'] ?? '요청을 처리하지 못했어요'}');
    }
    return (data as Map).cast<String, dynamic>();
  }

  // [사진 다시 올리기](KOS 사진 실패 · D7-56)
  Future<String> photoKosRetry(int photoId) async =>
      '${((await _post('/api/id-photos/$photoId/kos-retry')) as Map)['kos'] ?? 'failed'}';

  // §7.1 SSE 주소 — ?token= (+ deviceId · 0.4.0)
  Uri streamUri(String tokenValue, {int? deviceId}) => Uri.parse('${base()}/api/board/stream')
      .replace(queryParameters: {'token': tokenValue, 'deviceId': ?deviceId?.toString()});
}
