// back REST — 이 모듈에서만 부른다(SPEC-003 §7 · SPEC-004 §3.3). 오류 본문 = {error:{code,message}}
import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../model/account.dart';

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

  // §3.3 로그인 — 카드를 누르면 바로(비밀번호 없음)
  Future<List<AccountCard>> accounts() async {
    final data = await _req('GET', '/api/auth/accounts', auth: false);
    return data is List ? data.whereType<Map>().map((e) => AccountCard.fromJson(e.cast<String, dynamic>())).toList() : [];
  }

  Future<Session> login(String id) async {
    final data = await _req('POST', '/api/auth/login', body: {'id': id}, auth: false);
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
  Future<void> goHome(int visitId) => _post('/api/visits/$visitId/home');

  // §5-1.1 원장 호출 푸시 기기 토큰(16진)
  Future<void> registerDevice(String deviceToken) => _post('/api/devices', {'token': deviceToken});
  Future<void> unregisterDevice(String deviceToken) => _req('DELETE', '/api/devices/${Uri.encodeComponent(deviceToken)}');

  // §7.1 SSE 주소 — ?token=
  Uri streamUri(String tokenValue) =>
      Uri.parse('${base()}/api/board/stream').replace(queryParameters: {'token': tokenValue});
}
