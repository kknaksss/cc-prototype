import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/api/session_store.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/model/account.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/screens/login_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

class IdStore extends SessionStore {
  Session? s;
  String? lastId;
  final saved = <String>[];
  @override
  Future<Session?> read() async => s;
  @override
  Future<void> write(Session v) async {
    s = v;
    saved.add(jsonEncode(v.toJson()));
  }

  @override
  Future<void> clear() async => s = null;
  @override
  Future<String?> readLastId() async => lastId;
  @override
  Future<void> writeLastId(String id) async => lastId = id;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('로그인 실패 한 줄', () {
    test('401 · 429 는 back message 그대로', () {
      expect(loginErrorText(const ApiError(401, 'invalid_credentials', '아이디 또는 비밀번호가 맞지 않아요')), '아이디 또는 비밀번호가 맞지 않아요');
      expect(loginErrorText(const ApiError(429, 'too_many_attempts', '5분 뒤 다시 시도해 주세요')), '5분 뒤 다시 시도해 주세요');
    });
    test('본문이 없으면 기본 문구', () {
      expect(loginErrorText(const ApiError(401, 'error', '요청을 처리하지 못했어요')), '아이디 또는 비밀번호가 맞지 않아요');
      expect(loginErrorText(const ApiError(429, 'error', '요청을 처리하지 못했어요')), contains('잠시 뒤'));
      expect(loginErrorText(const ApiError(0, 'network', '서버에 연결할 수 없어요')), '서버에 연결할 수 없어요');
    });
  });

  test('POST /api/auth/login {id, password} · 아이디만 기억(비밀번호 저장 안 함)', () async {
    SharedPreferences.setMockInitialValues({});
    const ch = MethodChannel('procedure/push');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(ch, (call) async => call.method == 'status' ? 'denied' : false);
    String? body;
    final api = Api(
      base: () => 'http://x',
      token: () => null,
      client: MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          body = req.body;
          return http.Response('{"token":"t","expiresAt":"","id":"nurse1","role":"nurse","name":"n","staffId":null}', 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response('{"ok":true}', 200);
      }),
    );
    final store = IdStore();
    final app = AppState(store: store, api: api, push: PushChannel(ch));
    await app.boot();
    await app.login('nurse1', 's3cret');
    expect(jsonDecode(body!), {'id': 'nurse1', 'password': 's3cret'});
    expect(store.lastId, 'nurse1');
    expect(store.saved.any((j) => j.contains('s3cret')), isFalse);
    expect(app.notif, NotifStatus.denied);
    app.stream.dispose();
  });

  test('로그인 실패면 아이디를 기억하지 않는다 · 401 그대로 올라온다', () async {
    final api = Api(
      base: () => 'http://x',
      token: () => null,
      client: MockClient((req) async => http.Response(
          '{"error":{"code":"invalid_credentials","message":"아이디 또는 비밀번호가 맞지 않아요"}}', 401,
          headers: {'content-type': 'application/json; charset=utf-8'})),
    );
    final store = IdStore();
    final app = AppState(store: store, api: api, push: PushChannel(const MethodChannel('procedure/push')));
    await expectLater(app.login('x', 'y'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)));
    expect(store.lastId, isNull);
    app.stream.dispose();
  });
}
