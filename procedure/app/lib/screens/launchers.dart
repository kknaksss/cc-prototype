// 예약 상세에서 여는 것(SPEC-004 §6.11) — [태블릿에 띄우기](문진 → 기기) · [이 기기에서 열기](문진) · [여권 스캔](이 기기 카메라).
// 앱엔 [스캔할 기기](다른 기기로 스캔 보내기) 없음 — 웹에서만(D7-72)
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../model/display.dart';
import '../model/reservation.dart';
import '../theme/tokens.dart';
import '../view/time.dart';
import '../widgets/ui.dart';
import 'board_screen.dart' show isTablet;
import 'questionnaire_screen.dart' show showQuestionnaire;
import 'scan_screen.dart' show showPassportScan;

// [태블릿에 띄우기] — 기기 고르기 시트(§5-3 targets · 이름 · 폰/태블릿 · 접속 중 점) → POST /api/display-requests {deviceId}
Future<void> sendQuestionnaireToDevice(BuildContext context, ResvDetail d) async {
  final app = AppScope.read(context);
  List<DisplayTarget> targets;
  try {
    targets = await app.api.displayTargets();
  } on ApiError catch (e) {
    app.toaster.show(e.message);
    return;
  }
  if (!context.mounted) return;
  final submitted = d.displays.where((x) => x.kind == 'questionnaire' && x.status == 'done').map((x) => x.closedAt).whereType<String>().toList();
  Widget body(BuildContext ctx) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 4),
          child: Text('태블릿에 띄우기', style: Typo.titleSm600),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
          child: Text(
              submitted.isEmpty ? '${d.customer.name} 님 문진을 띄울 기기를 고르세요' : '오늘 이미 제출함 · ${hm(submitted.last)}',
              style: Typo.body400.copyWith(color: submitted.isEmpty ? Ms.gray600 : Ms.yellow)),
        ),
        if (targets.isEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
            child: Text('띄울 수 있는 기기가 없어요 — 코디 계정으로 로그인한 기기가 보여요', style: Typo.body400.copyWith(color: Ms.gray500)),
          ),
        for (final t in targets)
          ListTile(
            leading: Icon(t.kind == 'phone' ? Icons.smartphone_rounded : Icons.tablet_mac_rounded, color: Ms.gray700),
            title: Text(t.name, style: Typo.body600),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(color: t.online ? Ms.cons : Ms.gray400, shape: BoxShape.circle)),
              const SizedBox(width: 6),
              Text(t.online ? '접속 중' : '꺼짐', style: Typo.caption500.copyWith(color: Ms.gray600)),
            ]),
            onTap: () => Navigator.of(ctx).pop(t),
          ),
        const SizedBox(height: 12),
      ]);
  final DisplayTarget? pick = isTablet(context)
      ? await showDialog<DisplayTarget>(
          context: context,
          barrierColor: Ms.dim,
          builder: (ctx) => Dialog(
            backgroundColor: Ms.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
            child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 460), child: SingleChildScrollView(child: body(ctx))),
          ),
        )
      : await showModalBottomSheet<DisplayTarget>(
          context: context,
          backgroundColor: Ms.white,
          barrierColor: Ms.dim,
          isScrollControlled: true,
          shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
          builder: (ctx) => SafeArea(top: false, child: SingleChildScrollView(child: Column(children: [const SheetHandle(), body(ctx)]))),
        );
  if (pick == null) return;
  await app.run(() => app.api.createDisplay(d.reservationId, 'questionnaire', deviceId: pick.deviceId), '${pick.name}에 표시 중');
}

// [이 기기에서 열기] — 띄우기 요청 없이 문진 화면(§6.15 · WP-APP5)
typedef QuestionnaireOpener = Future<void> Function(BuildContext context, int reservationId, {int? displayRequestId});
QuestionnaireOpener? openQuestionnaire = showQuestionnaire;

// [여권 스캔] — 이 기기 카메라(§6.16 · WP-APP6)
typedef ScanOpener = Future<void> Function(BuildContext context, ResvDetail d, {int? displayRequestId});
ScanOpener? openPassportScan = showPassportScan;

// 띄우기 요청 열기(§5-3 「열기」) — 문진 = 잠금 화면 · 스캔 = 그 예약 상세를 읽어 스캔 화면. 화면이 닫힐 때까지 기다린다
Future<void> openDisplay(BuildContext context, DisplayReq r) async {
  final app = AppScope.read(context);
  if (r.kind == 'questionnaire') {
    final f = openQuestionnaire;
    if (f == null) return;
    await f(context, r.reservationId, displayRequestId: r.requestId);
    return;
  }
  final f = openPassportScan;
  if (f == null) return;
  try {
    final d = await app.api.reservation(r.reservationId);
    if (!context.mounted) return;
    await f(context, d, displayRequestId: r.requestId);
  } on ApiError catch (e) {
    app.toaster.show(e.message);
  }
}
