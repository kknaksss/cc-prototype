import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:procedure_app/api/api.dart';
import 'package:procedure_app/model/board.dart';
import 'package:procedure_app/view/view.dart';
import 'package:procedure_app/widgets/accept.dart';
import 'package:procedure_app/widgets/call_sheet.dart';

import 'fixture.dart';

void main() {
  OpenCall call(String kind, {int? target}) => OpenCall.fromJson(openCall(1, 1, kind, target: target));

  group('수락 doctorId(SPEC-004 §3.4 · A-15)', () {
    test('의사 = 본문에 doctorId 없음(자기 자신)', () {
      expect(acceptDoctorId(const Me(staffId: 7), call('all')), isNull);
      expect(acceptDoctorId(const Me(staffId: 7), call('one', target: 7)), isNull);
    });
    test('관리자 · 지정 호출 = 지정 원장으로(원장 고정)', () {
      expect(acceptDoctorId(const Me(admin: true), call('one', target: 2)), 2);
    });
    test('관리자 · 전체 호출 = 고른 원장(안 고르면 null → 시트로 고른다)', () {
      expect(fixedDoctor(call('all')), isNull);
      expect(acceptDoctorId(const Me(admin: true), call('all'), picked: 1), 1);
    });
  });

  test('원장 고르기 = 비어 있는 원장 먼저', () {
    expect(doctorsFreeFirst(board()).map((d) => d.id), [1, 2]);
  });

  group('호출 시트 [전체 선택](E2E A2)', () {
    test('pickable 만 고른다', () {
      expect(toggleAll({}, {1, 2}), {1, 2});
      expect(toggleAll({1}, {1, 2}), {1, 2});
    });
    test('다 골라져 있으면 해제', () {
      expect(toggleAll({1, 2}, {1, 2}), isEmpty);
    });
    test('고를 시술이 없으면 아무것도 안 고름', () {
      expect(toggleAll({}, {}), isEmpty);
    });
  });

  test('앱 화면 [수락] 요청 — 의사 본문 {} · 관리자 {doctorId} · X-Accept-Source: app', () async {
    final reqs = <http.Request>[];
    final api = Api(base: () => 'http://x', token: () => 't', client: MockClient((r) async {
      reqs.add(r);
      return http.Response('{"acceptedProcedureIds":[]}', 200);
    }));
    await api.accept(3);
    await api.accept(4, doctorId: 9);
    expect(reqs[0].url.path, '/api/calls/3/accept');
    expect(reqs[0].body, '{}');
    expect(reqs[1].body, '{"doctorId":9}');
    expect(reqs.every((r) => r.headers['X-Accept-Source'] == 'app'), isTrue);
    expect(reqs[0].headers['Authorization'], 'Bearer t');
  });

  test('앱 시작 me() 는 저장된 토큰을 싣는다(로그인 상태가 아직 없어도)', () async {
    String? auth;
    final api = Api(base: () => 'http://x', token: () => null, client: MockClient((r) async {
      auth = r.headers['Authorization'];
      return http.Response('{"id":"doctor","role":"doctor","name":"d","staffId":1}', 200);
    }));
    final s = await api.me('saved');
    expect(auth, 'Bearer saved');
    expect(s.token, 'saved');
  });
}
