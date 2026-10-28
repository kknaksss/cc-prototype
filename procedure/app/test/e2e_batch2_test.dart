// 실기기 E2E batch 2 — #3 이름 창 없음 · 기본 이름 = 기종 이름 · name 은 처음 등록 · 설정 저장 때만 / #4 [촬영] 사진에서 못 읽으면 손 입력
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/app_state.dart';
import 'package:procedure_app/push/push.dart';
import 'package:procedure_app/scan/scan_channel.dart';
import 'package:procedure_app/screens/scan_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'mrz_test.dart' show make;
import 'push_test.dart' show MemStore;
import 'scan_test.dart' show detail, png;

const ch = MethodChannel('procedure/push');
final json = {'content-type': 'application/json; charset=utf-8'};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  test('#3 기종 코드 → 이름 · 모르는 코드는 코드를 남김', () {
    expect(modelName('iPhone16,1'), 'iPhone 15 Pro');
    expect(modelName('iPhone18,3'), 'iPhone 17');
    expect(modelName('iPad16,3'), 'iPad Pro 11-inch (M4)');
    expect(modelName('iPhone99,1'), 'iPhone (iPhone99,1)');
    expect(modelName('iPad99,9'), 'iPad (iPad99,9)');
  });

  // 로그인 → 토큰 → 등록 본문들
  Future<(AppState, PushChannel, List<Map>)> start(Map<String, Object> prefs) async {
    SharedPreferences.setMockInitialValues(prefs);
    messenger.setMockMethodCallHandler(ch, (c) async => switch (c.method) {
          'status' => 'authorized',
          'requestPermission' => true,
          'deviceModel' => 'iPhone16,1',
          'installId' => 'iid',
          _ => null,
        });
    final bodies = <Map>[];
    late AppState app;
    final api = Api(
      base: () => 'http://x',
      token: () => app.session?.token,
      client: MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          return http.Response('{"token":"t","id":"coord","role":"coordinator","name":"코디","staffId":null}', 200, headers: json);
        }
        if (req.url.path == '/api/devices') {
          bodies.add(jsonDecode(req.body) as Map);
          return http.Response('{"ok":true,"deviceId":9}', 200);
        }
        return http.Response('{"ok":true,"unread":0,"items":[]}', 200);
      }),
    );
    final push = PushChannel(ch);
    app = AppState(store: MemStore([]), api: api, push: push);
    await app.boot();
    await app.login('coord', 'pw');
    return (app, push, bodies);
  }

  test('#3 이름 창 없이 기본 이름 = 기종 이름 · name 은 처음 등록 때만 · 다음 등록(토큰 바뀜)엔 안 실음', () async {
    final (app, push, bodies) = await start({});
    expect(app.deviceName, 'iPhone 15 Pro');
    push.onToken!('aa01');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    push.onToken!('aa02');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies.map((b) => b['token']).toSet(), {'aa01', 'aa02'}); // 시작 때 저장 토큰 재등록(멱등)이 겹칠 수 있음
    expect(bodies.where((b) => b.containsKey('name')).map((b) => b['name']), ['iPhone 15 Pro']); // 처음 한 번만
    expect(bodies.first['installId'], 'iid');
    expect(bodies.last.containsKey('name'), isFalse); // 설정에서 바꾼 이름을 덮지 않게
    expect((await SharedPreferences.getInstance()).getBool('device.nameSent'), isTrue);
    // 설정에서 저장 = name 실음
    await app.renameDevice('데스크 폰');
    expect(bodies.last['name'], '데스크 폰');
    app.stream.dispose();
  });

  test('#3 이미 이름을 정한 기기 = 그 이름 그대로(기종 이름으로 안 바꿈) · 이미 보낸 기기는 다시 안 실음', () async {
    final (app, push, bodies) = await start({'device.name': '코디 폰', 'device.nameSent': true});
    expect(app.deviceName, '코디 폰');
    push.onToken!('bb01');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies.any((b) => b.containsKey('name')), isFalse);
    app.stream.dispose();
  });

  test('#3 옛 빌드에서 넘어온 기기(이름 보낸 기록 없음) = 처음 한 번 기종 이름을 실어 「iPhone」을 바꾼다', () async {
    final (app, push, bodies) = await start({'push.deviceToken': 'cc01'});
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies.first['name'], 'iPhone 15 Pro');
    push.onToken!('cc02');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bodies.last.containsKey('name'), isFalse);
    app.stream.dispose();
  });

  group('#4 스캔 화면', () {
    const scan = MethodChannel('procedure/scan');
    Future<(AppState, List<Object?>)> pump(WidgetTester t, Object? Function(MethodCall) native) async {
      SharedPreferences.setMockInitialValues({});
      final args = <Object?>[];
      messenger.setMockMethodCallHandler(scan, (c) async {
        args.add(c.arguments);
        return native(c);
      });
      final app = AppState(api: Api(base: () => 'http://x', token: () => 't', client: MockClient((_) async => http.Response('{}', 200))));
      t.view.physicalSize = const Size(1179, 2556);
      t.view.devicePixelRatio = 3;
      await t.pumpWidget(AppScope(state: app, child: MaterialApp(home: ScanScreen(detail: detail(), channel: const ScanChannel(scan)))));
      await t.pumpAndSettle();
      return (app, args);
    }

    testWidgets('[촬영] 사진에서도 못 읽음 → 바로 손 입력(사진 없이)', (t) async {
      final (app, args) = await pump(t, (c) => {'photo': png, 'lines': ['PASSPORT', '흐림'], 'shutter': true});
      expect(find.text('손으로 입력'), findsOneWidget); // 확인 화면 제목
      expect(find.text('읽지 못했어요 · 다시 찍어 주세요'), findsNothing);
      expect(find.byType(Image), findsNothing); // 손 입력 = 사진 버림
      expect((args.single as Map)['debug'], isTrue); // 시험 = debug 빌드 → 인식 글자 오버레이 켬
      app.stream.dispose();
    });

    testWidgets('[촬영] 사진에서 읽힘 → 확인 화면(사진 있음)', (t) async {
      final (l1, l2) = make();
      final (app, _) = await pump(t, (c) => {'photo': png, 'lines': [l1, l2], 'shutter': true});
      expect(find.text('읽은 값을 확인하세요'), findsOneWidget);
      app.stream.dispose();
    });

    test('네이티브 판정 checkMrz — 같은 판독 두 번이면 confirmed', () async {
      final (l1, l2) = make();
      final replies = <String>[];
      messenger.setMockMethodCallHandler(scan, (c) async {
        for (final lines in [
          ['아무 글자'],
          [l1, l2],
          [l1, l2],
        ]) {
          await messenger.handlePlatformMessage('procedure/scan', const StandardMethodCodec().encodeMethodCall(MethodCall('checkMrz', lines)),
              (d) => replies.add(const StandardMethodCodec().decodeEnvelope(d!) as String));
        }
        return null;
      });
      await const ScanChannel(scan).scanPassport();
      expect(replies, ['none', 'pending', 'confirmed']);
    });
  });
}
