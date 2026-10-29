// back REST — 이 모듈에서만 부른다(SPEC-003 §7 · SPEC-004 §3.3). 오류 본문 = {error:{code,message}}
import 'dart:async';
import 'dart:convert';
import 'dart:io' show File;
import 'dart:math' show min;

import 'package:flutter/foundation.dart' show Uint8List;
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;

import '../chat/chat_model.dart';
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
  // 유입 채널(E2E batch 3 #2) — KOS 고객 칸 · null = 비움 · 같은 값이면 back 이 KOS 안 부름
  Future<void> saveFunnel(int customerId, int? funnelId) => _req('PUT', '/api/customers/$customerId/funnel', body: {'funnelId': funnelId});
  // 여권 사진 삭제(E2E batch 3 #1) — ccc 사진 · 그 사진으로 한 신분 확인(→ 미확인) · KOS 이미지. 응답 kos = deleted | not_found | skipped
  Future<String> deleteIdPhoto(int photoId) async => '${((await _req('DELETE', '/api/id-photos/$photoId')) as Map)['kos'] ?? ''}';

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

  // ─── 채팅(SPEC-007 §6.2) — 18 경로(r3) · JSON = 12초 · 사진 올리기 = 40초 · 동영상 올리기 = 300초(§9)
  Future<List<Person>> chatPeople() async {
    final d = await _req('GET', '/api/chat/people');
    final l = d is Map ? d['items'] : null;
    return [for (final e in (l is List ? l : const [])) if (e is Map) Person.fromJson(e.cast<String, dynamic>())];
  }

  Future<({List<Room> items, int unreadRooms})> chatRooms() async {
    final d = await _req('GET', '/api/chat/rooms');
    final l = d is Map ? d['items'] : null;
    final items = [for (final e in (l is List ? l : const [])) if (e is Map) Room.fromJson(e.cast<String, dynamic>())];
    final n = d is Map ? d['unreadRooms'] : null;
    return (items: items, unreadRooms: n is num ? n.toInt() : items.where((r) => r.unread > 0).length);
  }

  Future<Room> _room(Future<dynamic> f) async => Room.fromJson(((await f) as Map).cast<String, dynamic>());
  Future<Room> chatOpenDirect(int accountId) => _room(_post('/api/chat/rooms/direct', {'accountId': accountId}));
  Future<Room> chatCreateGroup(List<int> accountIds, {String? title}) =>
      _room(_post('/api/chat/rooms', {'accountIds': accountIds, if (title != null && title.trim().isNotEmpty) 'title': title.trim()}));
  Future<Room> chatAddMembers(int roomId, List<int> accountIds) => _room(_post('/api/chat/rooms/$roomId/members', {'accountIds': accountIds}));
  Future<void> chatLeave(int roomId) => _post('/api/chat/rooms/$roomId/leave');
  Future<void> chatHide(int roomId) => _post('/api/chat/rooms/$roomId/hide');
  Future<void> chatMute(int roomId, bool muted) => _req('PUT', '/api/chat/rooms/$roomId/mute', body: {'muted': muted});

  // before = id < before · since = updatedAt >= since(KST · 밀리초 — `+` 가 공백으로 읽히지 않게 queryParameters 로 %2B)
  Future<({List<ChatMessage> items, bool hasMore})> chatMessages(int roomId, {int? before, String? since, int? limit}) async {
    final q = Uri(queryParameters: {'before': ?before?.toString(), 'since': ?since, 'limit': ?limit?.toString()}).query;
    final d = await _req('GET', '/api/chat/rooms/$roomId/messages${q.isEmpty ? '' : '?$q'}');
    final l = d is Map ? d['items'] : null;
    return (
      items: [for (final e in (l is List ? l : const [])) if (e is Map) ChatMessage.fromJson(e.cast<String, dynamic>())],
      hasMore: d is Map && d['hasMore'] == true,
    );
  }

  Future<ChatMessage> chatSend(int roomId, String clientId, {String? text, int? photoId, int? videoId}) async => ChatMessage.fromJson(
      ((await _post('/api/chat/rooms/$roomId/messages', {'clientId': clientId, 'text': ?text, 'photoId': ?photoId, 'videoId': ?videoId})) as Map)
          .cast<String, dynamic>());
  // 수정(r3 · 내 텍스트만) — 응답 = 고친 Message(editedAt · 서버 updatedAt — W-6)
  Future<ChatMessage> chatEdit(int messageId, String text) async =>
      ChatMessage.fromJson(((await _req('PATCH', '/api/chat/messages/$messageId', body: {'text': text})) as Map).cast<String, dynamic>());
  Future<void> chatDelete(int messageId) => _req('DELETE', '/api/chat/messages/$messageId');
  Future<Json> chatRead(int roomId, int messageId) async =>
      ((await _post('/api/chat/rooms/$roomId/read', {'messageId': messageId})) as Map).cast<String, dynamic>();

  static const photoTimeout = Duration(seconds: 40);

  // 사진 올리기(multipart) — 진행률을 알려고 본문 바이트를 직접 흘린다(MultipartRequest 는 보낸 바이트를 알려 주지 않음 · A27)
  Future<int> chatUploadPhoto(int roomId, Uint8List jpeg, {required int width, required int height, void Function(double)? onProgress}) async {
    final boundary = 'ccc-${DateTime.now().microsecondsSinceEpoch}';
    List<int> field(String k, String v) => utf8.encode('--$boundary\r\nContent-Disposition: form-data; name="$k"\r\n\r\n$v\r\n');
    final head = <int>[
      ...field('roomId', '$roomId'),
      ...field('width', '$width'),
      ...field('height', '$height'),
      ...utf8.encode('--$boundary\r\nContent-Disposition: form-data; name="photo"; filename="photo.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'),
    ];
    final tail = utf8.encode('\r\n--$boundary--\r\n');
    final req = http.StreamedRequest('POST', Uri.parse('${base()}/api/chat/photos'));
    final t = token();
    req.headers['Accept'] = 'application/json';
    req.headers['Content-Type'] = 'multipart/form-data; boundary=$boundary';
    if (t != null) req.headers['Authorization'] = 'Bearer $t';
    final total = head.length + jpeg.length + tail.length;
    req.contentLength = total;
    http.Response res;
    try {
      final sending = client.send(req).timeout(photoTimeout);
      const chunk = 64 * 1024;
      final body = Stream<List<int>>.fromIterable([
        head,
        for (var i = 0; i < jpeg.length; i += chunk) Uint8List.sublistView(jpeg, i, min(i + chunk, jpeg.length)),
        tail,
      ]);
      await _pump(req, body, total, onProgress);
      res = await http.Response.fromStream(await sending);
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    }
    final data = _decode(res);
    final id = data is Map ? data['photoId'] : null;
    if (id is! num) throw const ApiError(0, 'error', '사진을 올리지 못했어요');
    return id.toInt();
  }

  // 사진 바이트(Bearer 헤더만 · 쿠키 · ?token= 없음 — D9-23). 앱은 메모리에만 둔다(D9-24)
  Future<Uint8List> chatPhoto(int photoId) async {
    final headers = <String, String>{'Accept': 'image/jpeg'};
    final t = token();
    if (t != null) headers['Authorization'] = 'Bearer $t';
    http.Response res;
    try {
      final req = http.Request('GET', Uri.parse('${base()}/api/chat/photos/$photoId'))..headers.addAll(headers);
      res = await http.Response.fromStream(await client.send(req).timeout(photoTimeout));
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) _decode(res);
    return res.bodyBytes;
  }

  static const videoTimeout = Duration(seconds: 300);

  // 동영상 올리기(r3 · #16) — 변환 뒤 MP4 를 파일에서 되밀기 있게 흘린다(메모리에 다 올리지 않음 · 진행률 = 보낸 바이트 · W-2) · Content-Length 를 싣는다(청크 금지 — 서버가 413 을 먼저 거름 · r3 처분)
  Future<int> chatUploadVideo(int roomId, String path,
      {required Uint8List thumb, required int width, required int height, required int durationMs, void Function(double)? onProgress}) async {
    final file = File(path);
    final size = await file.length();
    final boundary = 'ccc-${DateTime.now().microsecondsSinceEpoch}';
    List<int> field(String k, String v) => utf8.encode('--$boundary\r\nContent-Disposition: form-data; name="$k"\r\n\r\n$v\r\n');
    final head = <int>[
      ...field('roomId', '$roomId'),
      ...field('width', '$width'),
      ...field('height', '$height'),
      ...field('durationMs', '$durationMs'),
      ...utf8.encode('--$boundary\r\nContent-Disposition: form-data; name="thumb"; filename="thumb.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'),
      ...thumb,
      ...utf8.encode('\r\n--$boundary\r\nContent-Disposition: form-data; name="video"; filename="video.mp4"\r\nContent-Type: video/mp4\r\n\r\n'),
    ];
    final tail = utf8.encode('\r\n--$boundary--\r\n');
    final req = http.StreamedRequest('POST', Uri.parse('${base()}/api/chat/videos'));
    final t = token();
    req.headers['Accept'] = 'application/json';
    req.headers['Content-Type'] = 'multipart/form-data; boundary=$boundary';
    if (t != null) req.headers['Authorization'] = 'Bearer $t';
    final total = head.length + size + tail.length;
    req.contentLength = total;
    http.Response res;
    try {
      final sending = client.send(req).timeout(videoTimeout);
      Stream<List<int>> body() async* {
        yield head;
        yield* file.openRead(); // 받는 쪽이 멈추면 파일 읽기도 멈춤
        yield tail;
      }

      await _pump(req, body(), total, onProgress);
      res = await http.Response.fromStream(await sending);
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    }
    final data = _decode(res);
    final id = data is Map ? data['videoId'] : null;
    if (id is! num) throw const ApiError(0, 'error', '동영상을 올리지 못했어요');
    return id.toInt();
  }

  // 재생 · 썸네일 · 공유 — Bearer 헤더만(쿠키 · ?token= 없음 — D9-23 · §6.2)
  Uri chatVideoUri(int videoId) => Uri.parse('${base()}/api/chat/videos/$videoId');
  Map<String, String> get authHeaders {
    final t = token();
    return {if (t != null) 'Authorization': 'Bearer $t'};
  }

  // 썸네일 바이트(#18) — 메모리에만(사진과 같은 캐시 · 키는 따로)
  Future<Uint8List> chatVideoThumb(int videoId) async {
    http.Response res;
    try {
      final req = http.Request('GET', Uri.parse('${base()}/api/chat/videos/$videoId/thumbnail'))
        ..headers.addAll({'Accept': 'image/jpeg', ...authHeaders});
      res = await http.Response.fromStream(await client.send(req).timeout(photoTimeout));
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) _decode(res);
    return res.bodyBytes;
  }

  // 동영상 공유용 받기(r3 U-4) — #17 을 Bearer 로 받아 파일로 흘려 쓴다(메모리에 다 올리지 않음) · 진행률 · cancelled 면 멈추고 파일 지움
  Future<void> chatVideoDownload(int videoId, File out, {void Function(double)? onProgress, bool Function()? cancelled}) async {
    final sink = out.openWrite();
    var ok = false;
    try {
      final req = http.Request('GET', chatVideoUri(videoId))..headers.addAll({'Accept': 'video/mp4', ...authHeaders});
      final res = await client.send(req).timeout(videoTimeout);
      if (res.statusCode < 200 || res.statusCode >= 300) {
        _decode(await http.Response.fromStream(res));
      }
      final total = res.contentLength ?? 0;
      var got = 0;
      await for (final b in res.stream.timeout(videoTimeout)) {
        if (cancelled?.call() ?? false) throw const ApiError(0, 'cancelled', '');
        sink.add(b);
        got += b.length;
        if (total > 0) onProgress?.call(got / total);
      }
      ok = true;
    } on ApiError {
      rethrow;
    } on TimeoutException {
      throw const ApiError(0, 'network', '서버 응답이 없어요');
    } catch (_) {
      throw const ApiError(0, 'network', '서버에 연결할 수 없어요');
    } finally {
      await sink.close();
      if (!ok) {
        try {
          await out.delete();
        } catch (_) {}
      }
    }
  }

  // 본문을 요청에 흘린다 — sink.addStream 은 받는 쪽(소켓)이 멈추면 원천(파일 읽기)도 멈춘다(되밀기) → 메모리에 다 쌓이지 않고,
  // 진행률 = 요청 스트림이 실제로 가져간 바이트(소켓 버퍼 몫만큼 앞섬 · review-code r2 W-2). Content-Length 는 부르는 쪽이 싣는다
  Future<void> _pump(http.StreamedRequest req, Stream<List<int>> body, int total, void Function(double)? onProgress) async {
    var sent = 0;
    await req.sink.addStream(body.map((b) {
      sent += b.length;
      onProgress?.call(sent / total);
      return b;
    }));
    unawaited(req.sink.close());
  }

  // 오류 본문 → ApiError(2xx 면 JSON 그대로)
  dynamic _decode(http.Response res) {
    dynamic data;
    try {
      data = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    } catch (_) {}
    if (res.statusCode < 200 || res.statusCode >= 300) {
      final err = data is Map && data['error'] is Map ? data['error'] as Map : const {};
      throw ApiError(res.statusCode, '${err['code'] ?? 'error'}', '${err['message'] ?? '요청을 처리하지 못했어요'}');
    }
    return data;
  }

  // §7.1 SSE 주소 — ?token= (+ deviceId · 0.4.0)
  Uri streamUri(String tokenValue, {int? deviceId}) => Uri.parse('${base()}/api/board/stream')
      .replace(queryParameters: {'token': tokenValue, 'deviceId': ?deviceId?.toString()});
}
