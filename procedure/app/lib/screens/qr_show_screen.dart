// 문진 QR 화면(SPEC-006 §8.2 · SPEC-004 0.4.2 §5-3 「열기」 · 시안 없음 → DS 기본값) — 고객이 자기 휴대폰 카메라로 찍는다.
// 흰 바탕 전체 화면 · 가운데 큰 QR(짧은 변 60%) · 안내 한국어 + 영어 한 줄 · 남은 시간 mm:ss · 오른쪽 위 [닫기].
// 고객 이름 · 예약 정보 없음. 떠 있는 동안 화면 꺼짐 막기. 5초마다 예약 상세 displays[] 에서 그 요청이 pending 이 아니면
// 한 줄 알림 뒤 1.5초에 저절로 닫힌다. [닫기] = 화면만(요청은 그대로 — 데스크 웹 QR 은 계속 됨).
// qrUrl 에는 토큰이 들어 있다 — 로그 · 저장 · 토스트에 쓰지 않는다(SPEC-006 §7.5)
import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../scan/scan_channel.dart';
import '../theme/tokens.dart';

Future<void> showQrScreen(BuildContext context,
        {required int requestId, required int reservationId, required String qrUrl, String? expiresAt, ScanChannel channel = const ScanChannel()}) =>
    Navigator.of(context, rootNavigator: true).push(MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => QrShowScreen(requestId: requestId, reservationId: reservationId, qrUrl: qrUrl, expiresAt: expiresAt, channel: channel),
    ));

// pending 이 아닐 때 닫히며 보일 한 줄
String qrClosedLine(String status) => switch (status) {
      'opened' => '고객 폰에서 열렸어요',
      'done' => '제출됐어요',
      'expired' => '시간이 지났어요',
      _ => '닫혔어요',
    };

class QrShowScreen extends StatefulWidget {
  final int requestId;
  final int reservationId;
  final String qrUrl;
  final String? expiresAt;
  final ScanChannel channel;
  final Duration poll;
  const QrShowScreen({
    super.key,
    required this.requestId,
    required this.reservationId,
    required this.qrUrl,
    this.expiresAt,
    this.channel = const ScanChannel(),
    this.poll = const Duration(seconds: 5),
  });
  @override
  State<QrShowScreen> createState() => _QrShowScreenState();
}

class _QrShowScreenState extends State<QrShowScreen> {
  late final AppState _app;
  Uint8List? _png;
  bool _failed = false;
  String? _closing; // 닫히며 보일 한 줄
  Timer? _poll;
  Timer? _tick;
  Duration? _left;

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    widget.channel.keepAwake(true);
    widget.channel.qrImage(widget.qrUrl, size: 900).then((p) {
      if (mounted) setState(() => p == null ? _failed = true : _png = p);
    });
    final until = DateTime.tryParse(widget.expiresAt ?? '');
    if (until != null) {
      _left = _remain(until);
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() => _left = _remain(until));
      });
    }
    _poll = Timer.periodic(widget.poll, (_) => _check());
  }

  Duration _remain(DateTime until) {
    final d = until.difference(DateTime.now().add(Duration(milliseconds: _app.stream.skewMs)));
    return d.isNegative ? Duration.zero : d;
  }

  // 그 요청 상태 — pending 이 아니면 한 줄 → 1.5초 뒤 닫힘. 읽기 실패 · 목록에 없음 = 그대로 두고 다음 번에
  Future<void> _check() async {
    if (_closing != null) return;
    try {
      final d = await _app.api.reservation(widget.reservationId);
      final x = d.displays.where((x) => x.id == widget.requestId).firstOrNull;
      if (x == null || x.status == 'pending' || !mounted) return;
      setState(() => _closing = qrClosedLine(x.status));
      _poll?.cancel();
      Timer(const Duration(milliseconds: 1500), () {
        if (mounted) Navigator.of(context).pop();
      });
    } on ApiError {
      // 조용히 — 다음 폴링
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    _tick?.cancel();
    widget.channel.keepAwake(false);
    _png = null;
    super.dispose();
  }

  String _mmss(Duration d) => '${d.inMinutes.toString().padLeft(2, '0')}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final side = size.shortestSide * 0.6;
    final left = _left;
    return Scaffold(
      backgroundColor: Ms.white,
      body: SafeArea(
        child: Stack(children: [
          Align(
            alignment: Alignment.topRight,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 8, 12, 0),
              child: TextButton(
                onPressed: () => Navigator.of(context).pop(), // 화면만 — 요청은 그대로
                child: Text('닫기', style: Typo.headingMd600.copyWith(color: Ms.gray700)),
              ),
            ),
          ),
          Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 56),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Text('휴대폰 카메라로 QR 을 찍어 주세요', textAlign: TextAlign.center, style: Typo.titleSm600),
                const SizedBox(height: 6),
                Text('Scan with your phone camera', textAlign: TextAlign.center, style: Typo.body500.copyWith(color: Ms.gray600)),
                const SizedBox(height: 24),
                SizedBox(
                  key: const Key('qr-box'),
                  width: side,
                  height: side,
                  child: _closing != null
                      ? Center(child: Icon(Icons.check_circle_rounded, size: side * 0.3, color: Ms.primary))
                      : _png != null
                          ? Image.memory(_png!, filterQuality: FilterQuality.none, gaplessPlayback: true, semanticLabel: '문진 QR')
                          : _failed
                              ? Center(child: Text('QR 을 그리지 못했어요', style: Typo.body500.copyWith(color: Ms.red)))
                              : const Center(child: CircularProgressIndicator(strokeWidth: 2)),
                ),
                const SizedBox(height: 20),
                if (_closing != null)
                  Text(_closing!, style: Typo.headingMd600.copyWith(color: Ms.primary))
                else if (left != null)
                  Text(left == Duration.zero ? '시간이 지났어요' : '남은 시간 ${_mmss(left)}',
                      key: const Key('qr-left'),
                      style: Typo.headingMd600.copyWith(color: left == Duration.zero ? Ms.red : Ms.gray700)),
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}
