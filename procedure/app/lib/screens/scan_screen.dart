// 여권 스캔 · 스캔 확인(SPEC-004 §6.16 · D7-17 ~ D7-20 · D7-48 ~ D7-56 · 시안 없음 → DS 기본값).
// ① 카메라(가이드 틀 125 × 88 · MRZ 자리 · 빛 반사 안내 — Runner TextScanner.swift · AVCaptureSession 연속 · 자동 매크로) →
// ② 영상 프레임의 MRZ 자리를 기기 안에서 계속 읽어 같은 판독이 연속 두 번이면 자동 촬영(E2E batch 1 #6 · batch 2 #4) ·
//   [촬영] 버튼은 늘 — 찍은 사진에서 다시 읽고 못 읽으면 바로 손 입력 →
// 정해진 시간 3번(또는 [손으로 입력]) 못 읽음 → 「읽지 못했어요」 + [손으로 입력](빈 확인 화면) → ③ 「읽은 값」 ↔ 「KOS 지금 값」 나란히 · 다른 칸 강조 ·
// 고칠 수 있음 · name(카드 이름) 칸 없음 → ④ multipart 저장 → ⑤ 「저장했어요」 + ccc · KOS 사진 결과 따로 · KOS 실패면 [사진 다시 올리기].
//
// 법적 검토 필요: 신분증 이미지 · 주민번호 처리 — 찍은 원본은 이 화면 상태(메모리)에만 둔다. 사진첩 · 파일 · 캐시에 쓰지 않고
// 저장 성공 · [다시 찍기] · [닫기] 때 바로 버린다(D7-50). 가리지 않는다(여권 · D7-19 · 가림 기능 없음 D7-51). 보관 기간은 back(D7-55)
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../chat/chat_state.dart' show whileDisplayScreen;
import '../model/board.dart' show Json;
import '../model/reservation.dart';
import '../scan/mrz.dart';
import '../scan/scan_channel.dart';
import '../theme/tokens.dart';
import '../view/resv_view.dart' show nationName;
import '../widgets/ui.dart';
import 'board_screen.dart' show isTablet;

// 예약 상세 [여권 스캔] · 띄우기(kind = scan) · QR — 나갈 때까지 기다린다. 떠 있는 동안 띄우기 화면 수를 올린다(채팅 배너 없음 · D9-44)
Future<void> showPassportScan(BuildContext context, ResvDetail d, {int? displayRequestId}) =>
    whileDisplayScreen(() => Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(
          fullscreenDialog: true,
          builder: (_) => ScanScreen(detail: d, displayRequestId: displayRequestId),
        )));

// 스캔 확인 칸(§6.16 ③) — name 없음(D7-53)
const scanFields = [
  ('passportSurname', '여권 영문 성'),
  ('passportGivenNames', '여권 영문 이름'),
  ('passportNumber', '여권번호'),
  ('nationality', '국적'),
  ('dateOfBirth', '생년월일'),
  ('gender', '성별'),
  ('passportExpiryDate', '만료일'),
];

Map<String, String> mrzValues(Mrz? m) => m == null
    ? {for (final f in scanFields) f.$1: ''}
    : {
        'passportSurname': m.surname,
        'passportGivenNames': m.givenNames,
        'passportNumber': m.passportNumber,
        'nationality': m.nationality,
        'dateOfBirth': m.dateOfBirth,
        'gender': m.gender ?? '',
        'passportExpiryDate': m.expiryDate,
      };

// 바꿀 칸만(KOS 지금 값과 다르고 비지 않은 것)
Map<String, dynamic> changedFields(Map<String, String> read, Map<String, String> kos) => {
      for (final f in scanFields)
        if ((read[f.$1] ?? '').trim().isNotEmpty && (read[f.$1] ?? '').trim() != (kos[f.$1] ?? '').trim()) f.$1: read[f.$1]!.trim(),
    };

enum _Stage { capture, reading, failed, noCamera, confirm, saving, saved }

class ScanScreen extends StatefulWidget {
  final ResvDetail detail;
  final int? displayRequestId;
  final ScanChannel channel;
  const ScanScreen({super.key, required this.detail, this.displayRequestId, this.channel = const ScanChannel()});
  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  late final AppState _app;
  _Stage _stage = _Stage.capture;
  int _fails = 0;
  bool _manual = false;
  Uint8List? _photo; // 메모리만(법적 검토 필요 — 위 머리 주석)
  final Map<String, TextEditingController> _ctl = {for (final f in scanFields) f.$1: TextEditingController()};
  String? _saveError;
  Json? _result;
  bool _retrying = false;

  Map<String, String> get _kos {
    final p = widget.detail.customer.personal;
    return {for (final f in scanFields) f.$1: p?.s(f.$1) ?? ''};
  }

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    WidgetsBinding.instance.addPostFrameCallback((_) => _capture());
  }

  @override
  void dispose() {
    _photo = null;
    for (final c in _ctl.values) {
      c.dispose();
    }
    super.dispose();
  }

  // ① · ② 연속 스캔 — 네이티브가 MRZ 검사 숫자가 맞는 프레임을 자동으로 찍어 온다(E2E batch 1 #6)
  // 정해진 시간 동안 못 읽음 · [손으로 입력] = 실패 화면(3 / 3 · [손으로 입력] · [다시 찍기])
  Future<void> _capture() async {
    setState(() {
      _photo = null; // [다시 찍기] = 앞 사진 버림
      _stage = _Stage.capture;
    });
    PassportShot? shot;
    try {
      shot = await widget.channel.scanPassport();
    } on NoCamera {
      if (mounted) setState(() => _stage = _Stage.noCamera);
      return;
    }
    if (!mounted) return;
    if (shot == null) return _close(); // 카메라 [닫기] = 닫기
    final m = shot.failed ? null : findMrz(shot.lines);
    if (m == null && shot.shutter) return _manualEntry(); // [촬영] 사진에서도 못 읽음 → 바로 손 입력(E2E batch 2 #4)
    if (m == null) {
      setState(() {
        _fails = shot!.failed ? 3 : _fails + 1;
        _stage = _Stage.failed;
      });
      return;
    }
    _fill(mrzValues(m));
    setState(() {
      _photo = shot!.photo;
      _manual = false;
      _stage = _Stage.confirm;
    });
  }

  void _fill(Map<String, String> v) {
    for (final e in v.entries) {
      _ctl[e.key]!.text = e.value;
    }
  }

  // 3번 실패 → [손으로 입력](빈 확인 화면 · D7-56)
  // 손 입력 = 사진 없이 저장(app_manual · photo = null — r1 FAIL-2 코디 기본값) · 읽지 못한 사진은 여기서 버린다
  void _manualEntry() {
    _fill(mrzValues(null));
    setState(() {
      _photo = null;
      _manual = true;
      _stage = _Stage.confirm;
    });
  }

  Map<String, String> get _read => {for (final e in _ctl.entries) e.key: e.value.text};

  // ④ 저장 — 실패(409 kos_rejected · 502) = 아무것도 저장 안 됨 → [다시 저장]
  Future<void> _save() async {
    setState(() {
      _stage = _Stage.saving;
      _saveError = null;
    });
    try {
      final r = await _app.api.passportScan(
        widget.detail.customer.customerId,
        fields: changedFields(_read, _kos),
        photo: _manual ? null : _photo, // 사진 없으면 photo 칸을 보내지 않는다
        reservationId: widget.detail.reservationId,
        displayRequestId: widget.displayRequestId,
        deviceId: _app.deviceId,
        manual: _manual,
      );
      if (!mounted) return;
      setState(() {
        _photo = null; // 저장 성공 = 원본 버림(D7-50)
        _result = r;
        _stage = _Stage.saved;
      });
    } on ApiError catch (e) {
      if (mounted) {
        setState(() {
          _saveError = '저장하지 못했어요 · ${e.message}';
          _stage = _Stage.confirm;
        });
      }
    }
  }

  Future<void> _retryKos() async {
    final id = _result?['photoId'];
    if (id is! num) return;
    setState(() => _retrying = true);
    try {
      final k = await _app.api.photoKosRetry(id.toInt());
      if (!mounted) return;
      final photo = Map<String, dynamic>.from(_result!['photo'] as Map)..['kos'] = k;
      setState(() => _result = {..._result!, 'photo': photo});
    } on ApiError catch (e) {
      _app.toaster.show(e.message);
    } finally {
      if (mounted) setState(() => _retrying = false);
    }
  }

  void _close() {
    _photo = null; // [닫기] = 원본 버림
    final r = widget.displayRequestId;
    if (r != null && _stage != _Stage.saved) {
      _app.api.closeDisplay(r, 'canceled').catchError((_) {}); // 띄우기로 열렸으면 나가기 = canceled
    }
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Ms.white,
      appBar: AppBar(
        backgroundColor: Ms.white,
        surfaceTintColor: Ms.white,
        automaticallyImplyLeading: false,
        title: Text('여권 스캔 · ${widget.detail.customer.name}', style: Typo.headingMd600),
        actions: [TextButton(onPressed: _close, child: Text('닫기', style: Typo.body500.copyWith(color: Ms.gray700)))],
      ),
      body: SafeArea(child: _body()),
    );
  }

  Widget _center(List<Widget> kids) => Center(
        child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, children: kids)),
      );

  Widget _body() {
    switch (_stage) {
      case _Stage.capture:
      case _Stage.reading:
        return _center([
          const CircularProgressIndicator(strokeWidth: 2),
          const SizedBox(height: 16),
          Text(_stage == _Stage.reading ? '여권을 읽는 중…' : '카메라를 여는 중…', style: Typo.headingMd500.copyWith(color: Ms.gray700)),
        ]);
      case _Stage.noCamera:
        return _center([
          const Icon(Icons.no_photography_outlined, size: 48, color: Ms.gray500),
          const SizedBox(height: 12),
          Text('이 기기는 카메라를 쓸 수 없어요', style: Typo.headingMd600),
          const SizedBox(height: 20),
          MsButton('손으로 입력', size: BtnSize.lg, onPressed: _manualEntry),
        ]);
      case _Stage.failed:
        return _center([
          const Icon(Icons.error_outline_rounded, size: 48, color: Ms.red),
          const SizedBox(height: 12),
          Text('읽지 못했어요 · 다시 찍어 주세요', style: Typo.headingMd600),
          const SizedBox(height: 6),
          Text('사진면 아래 두 줄이 점선 안에 · 빛 반사가 없게 ($_fails / 3)', style: Typo.body400.copyWith(color: Ms.gray600)),
          const SizedBox(height: 20),
          Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
            MsButton('다시 찍기', size: BtnSize.lg, onPressed: _capture),
            if (_fails >= 3) MsButton('손으로 입력', size: BtnSize.lg, variant: BtnVariant.outlined, onPressed: _manualEntry),
          ]),
        ]);
      case _Stage.confirm:
      case _Stage.saving:
        return _confirm();
      case _Stage.saved:
        return _saved();
    }
  }

  // ③ 스캔 확인 — 「읽은 값」(고칠 수 있음) ↔ 「KOS 지금 값」 · 다른 칸 강조
  Widget _confirm() {
    final kos = _kos;
    final tablet = isTablet(context);
    final saving = _stage == _Stage.saving;
    String show(String k, String v) => switch (k) {
          'nationality' => v.isEmpty ? '' : '$v ${nationName(v)}',
          'gender' => v == 'MALE' ? '남성' : v == 'FEMALE' ? '여성' : v,
          _ => v,
        };
    return ListView(
      padding: EdgeInsets.fromLTRB(tablet ? 32 : 16, 12, tablet ? 32 : 16, 24),
      children: [
        Row(children: [
          Expanded(child: Text(_manual ? '손으로 입력' : '읽은 값을 확인하세요', style: Typo.titleSm600)),
          if (_photo != null)
            ClipRRect(borderRadius: BorderRadius.circular(6), child: Image.memory(_photo!,
                    width: 88,
                    height: 62,
                    fit: BoxFit.cover,
                    gaplessPlayback: true,
                    errorBuilder: (_, _, _) => Container(width: 88, height: 62, color: Ms.gray200))),
        ]),
        const SizedBox(height: 4),
        Text('다른 칸만 강조돼요 · 고칠 수 있어요', style: Typo.caption500.copyWith(color: Ms.gray600)),
        const SizedBox(height: 12),
        Row(children: [
          const SizedBox(width: 104),
          Expanded(child: Text('읽은 값', style: Typo.caption600.copyWith(color: Ms.gray600))),
          const SizedBox(width: 8),
          Expanded(child: Text('KOS 지금 값', style: Typo.caption600.copyWith(color: Ms.gray600))),
        ]),
        for (final f in scanFields)
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: _ctl[f.$1]!,
            builder: (_, v, _) {
              final diff = v.text.trim().isNotEmpty && v.text.trim() != (kos[f.$1] ?? '').trim();
              return Container(
                margin: const EdgeInsets.only(top: 6),
                padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
                decoration: BoxDecoration(
                  color: diff ? Ms.yellow100 : Ms.white,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: diff ? Ms.yellow : Ms.gray200),
                ),
                child: Row(children: [
                  SizedBox(width: 94, child: Text(f.$2, style: Typo.body500.copyWith(color: Ms.gray700))),
                  Expanded(
                    child: TextField(
                      key: Key('scan-${f.$1}'),
                      controller: _ctl[f.$1],
                      enabled: !saving,
                      style: Typo.body600,
                      decoration: InputDecoration(
                        isDense: true,
                        border: InputBorder.none,
                        hintStyle: Typo.body400.copyWith(color: Ms.gray400),
                        hintText: switch (f.$1) {
                          'nationality' => '예: KR',
                          'gender' => 'MALE / FEMALE',
                          'dateOfBirth' || 'passportExpiryDate' => 'yyyy-MM-dd',
                          _ => '',
                        },
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: Text(show(f.$1, kos[f.$1] ?? '').ifEmpty('-'), style: Typo.body400.copyWith(color: Ms.gray600))),
                ]),
              );
            },
          ),
        if (_saveError != null) ...[
          const SizedBox(height: 12),
          Text(_saveError!, style: Typo.body600.copyWith(color: Ms.red)),
        ],
        const SizedBox(height: 20),
        Row(children: [
          Expanded(
            child: MsButton('다시 찍기', size: BtnSize.lg, variant: BtnVariant.outlined, color: BtnColor.gray, expand: true, onPressed: saving ? null : _capture),
          ),
          const SizedBox(width: 10),
          Expanded(
            flex: 2,
            child: MsButton(saving ? '저장 중…' : (_saveError != null ? '다시 저장' : '저장'), size: BtnSize.lg, expand: true, onPressed: saving ? null : _save),
          ),
        ]),
      ],
    );
  }

  // ⑤ 결과 — ccc · KOS 사진을 따로 한 줄씩(D7-56)
  Widget _saved() {
    final r = _result ?? const {};
    final photo = r['photo'] is Map ? (r['photo'] as Map) : const {};
    final ccc = '${photo['ccc'] ?? ''}';
    final kos = '${photo['kos'] ?? ''}';
    return _center([
      const Icon(Icons.check_circle_rounded, size: 56, color: Ms.primary),
      const SizedBox(height: 12),
      Text('저장했어요', style: Typo.titleSm600),
      const SizedBox(height: 12),
      Text('고객 정보 · KOS 반영', style: Typo.body500.copyWith(color: Ms.gray700)),
      if (r['photo'] == null)
        // 손 입력 = 사진 없이 저장(r1 FAIL-2 · photo: null)
        Text('사진 없음 · 손으로 입력', style: Typo.body500.copyWith(color: Ms.gray700))
      else ...[
        Text('ccc 사진 · ${ccc == 'ok' ? '저장됨' : ccc == 'disabled' ? '저장 꺼짐' : ccc}', style: Typo.body500.copyWith(color: Ms.gray700)),
        Text('KOS 사진 · ${kos == 'ok' ? '올림' : kos == 'skipped' ? '안 올림(ccc 사진 꺼짐)' : '실패'}',
            style: Typo.body500.copyWith(color: kos == 'failed' ? Ms.red : Ms.gray700)),
      ],
      const SizedBox(height: 20),
      Wrap(spacing: 10, runSpacing: 10, alignment: WrapAlignment.center, children: [
        if (kos == 'failed' && r['photoId'] != null)
          MsButton(_retrying ? '올리는 중…' : '사진 다시 올리기', size: BtnSize.lg, variant: BtnVariant.outlined, onPressed: _retrying ? null : _retryKos),
        MsButton('예약 상세로', size: BtnSize.lg, onPressed: () => Navigator.of(context).pop()),
      ]),
    ]);
  }
}

extension on String {
  String ifEmpty(String v) => isEmpty ? v : this;
}
