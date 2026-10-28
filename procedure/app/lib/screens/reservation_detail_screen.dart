// 예약 상세(SPEC-004 §6.11 · D7-05 · D7-06 · D7-32 ~ D7-35) — GET /api/reservations/{id} · 열려 있는 동안 5초 폴링.
// 켜짐 · 꺼짐 = 응답 can.* 그대로(앱이 다시 계산하지 않는다). 쓰기 = SPEC-005 §7.5 API 그대로 · 409 · 403 = 토스트 message + 다시 부름.
// 폰 = 전체 화면(위 막대 = 상태 색) · 태블릿 = 두 열(왼쪽 고객 · 오른쪽 건강 · 내원 현황).
// [수납하기 ›] · [처방전 출력] · [리포트 QR 전송] 없음 — 정산은 글자만(D7-06)
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api.dart';
import '../app_state.dart' hide Phase;
import '../model/reservation.dart';
import '../theme/tokens.dart';
import '../view/resv_view.dart';
import '../view/state.dart';
import '../view/time.dart';
import '../widgets/resv_ui.dart';
import '../widgets/ui.dart';
import 'board_screen.dart' show isTablet;
import '../widgets/header.dart' show DetailHeader;
import '../widgets/autosave.dart';
import 'launchers.dart';

class ReservationDetailScreen extends StatefulWidget {
  final int reservationId;
  final bool focusConsultation; // 상담사 호출 푸시로 열림 — 상담 카드가 보이게
  // 머리 [‹ 들어온 탭 이름](예약 현황 · 내원 현황 — 사용자 2026-10-28) · 제목 「예약 상세」 고정 · 상태는 본문 StateChip
  final String back;
  const ReservationDetailScreen({super.key, required this.reservationId, this.focusConsultation = false, this.back = '예약 현황'});
  @override
  State<ReservationDetailScreen> createState() => _ReservationDetailScreenState();
}

class _ReservationDetailScreenState extends State<ReservationDetailScreen> {
  late final AppState _app;
  ResvDetail? _d;
  String? _error;
  Timer? _poll;
  bool _busy = false;
  final _consKey = GlobalKey();
  bool _focused = false;

  // 접수 고르기 — 진행 경로(상담 필요 기본) · 방
  String _route = 'consultation';
  int? _room;
  int? _counselor;

  SaveState _funnelState = SaveState.idle; // 유입 채널 드롭다운 — 바로 저장

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _load();
    _poll = Timer.periodic(const Duration(seconds: 5), (_) {
      // 이 화면이 맨 위 · 앱이 앞일 때만
      final top = ModalRoute.of(context)?.isCurrent ?? false;
      final fg = WidgetsBinding.instance.lifecycleState == null || WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
      if (mounted && top && fg && !_busy) _load();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await _app.api.reservation(widget.reservationId);
      if (!mounted) return;
      setState(() {
        _d = d;
        _error = null;
      });
      if (widget.focusConsultation && !_focused) {
        _focused = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          final c = _consKey.currentContext;
          if (c != null) Scrollable.ensureVisible(c, duration: const Duration(milliseconds: 300), alignment: 0.2);
        });
      }
    } on ApiError catch (e) {
      if (!mounted) return;
      if (_d == null && e.status == 404) {
        _app.toaster.show('예약을 찾을 수 없어요');
        Navigator.of(context).maybePop();
        return;
      }
      setState(() => _error = e.message);
    }
  }

  // 쓰기 — 성공 토스트 · 실패(409 · 403)는 app.run 이 message 토스트. 어느 쪽이든 다시 부름
  Future<bool> _write(Future<void> Function() f, String? ok) async {
    setState(() => _busy = true);
    final res = await _app.run(f, ok);
    if (mounted) setState(() => _busy = false);
    await _load();
    return res;
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    final tablet = isTablet(context);
    if (d == null) {
      return _frame(
        Center(child: _error != null ? Text(_error!, style: Typo.body500.copyWith(color: Ms.gray600)) : const CircularProgressIndicator(strokeWidth: 2)),
      );
    }
    // 폰 = 지금 할 일(접수 · 내원 현황 단계) 먼저 → 고객 · 메모 · 건강 · 이전 방문
    final left = <Widget>[
      _customerHead(d),
      if (!tablet) ..._flowAll(d),
      _identity(d),
      _personal(d),
      _memoBox(d),
      _remarkBox(d),
      if (!tablet) _health(d),
      _previous(d),
      if (d.canDo('cancel')) _cancelRow(d),
    ];
    final right = <Widget>[..._flowAll(d), _health(d)];
    return _frame(
      RefreshIndicator(
        onRefresh: _load,
        child: tablet
            ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: _col(left)),
                Expanded(child: _col(right)),
              ])
            : _col(left),
      ),
    );
  }

  // 위 막대 = 흰 바탕 · 공통 헤더 높이 · [‹ 들어온 탭] 「예약 상세」(정가운데) — 상태 색 · 상태 제목 · 시각 없음(사용자 2026-10-28
  // 「보라 상태 색 헤더가 다른 앱 같다」) · 상태는 본문 고객 머리의 2계층 StateChip 으로만 · iOS 상태 바 = 어두운 글자
  Widget _frame(Widget body) => AnnotatedRegion<SystemUiOverlayStyle>(
        value: SystemUiOverlayStyle.dark,
        child: Scaffold(
          backgroundColor: Ms.gray100,
          body: Column(children: [
            Container(color: Ms.white, height: MediaQuery.paddingOf(context).top),
            DetailHeader(back: widget.back, title: '예약 상세'),
            Expanded(child: body),
          ]),
        ),
      );

  Widget _col(List<Widget> kids) => ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: 12), child: k)],
      );

  Widget _box({required String title, Widget? trailing, required List<Widget> children, Key? key}) => Container(
        key: key,
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
        decoration: BoxDecoration(color: Ms.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Ms.gray200)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [Expanded(child: Text(title, style: Typo.headingMd600)), ?trailing]),
          const SizedBox(height: 8),
          ...children,
        ]),
      );

  // 머리 — 성별 · 이름 · 발음 · 초진/재진 · 국기 / 국적 · 성별 · 만 n세 · No. · 날짜 시각 · 구역 · 방
  Widget _customerHead(ResvDetail d) {
    final c = d.customer;
    final g = c.gender == 'MALE' ? '남성' : c.gender == 'FEMALE' ? '여성' : null;
    final when = '${d.day.replaceAll('-', '.')} ${d.start != null ? hm(d.start) : ''}'.trim();
    final line = [
      nationName(c.nationality),
      ?g,
      if (c.age != null) '만 ${c.age}세',
      if ((c.chartNumber ?? '').isNotEmpty) 'No.${c.chartNumber}',
      when,
      ?d.zoneTitle,
      ?d.groupTitle,
      if ((d.flow?.roomTitle ?? '').isNotEmpty) d.flow!.roomTitle!,
    ].where((x) => x.isNotEmpty).join(' · ');
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(color: Ms.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Ms.gray200)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          genderIcon(c.gender),
          const SizedBox(width: 6),
          // 이름이 먼저 자리를 갖고 발음이 먼저 말줄임
          Expanded(
            child: Text.rich(
              TextSpan(children: [
                TextSpan(text: c.name, style: Typo.titleSm600),
                if ((c.phoneticName ?? '').isNotEmpty) TextSpan(text: '  ${c.phoneticName}', style: Typo.headingSm400.copyWith(color: Ms.gray500)),
              ]),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 6),
          visitChip(c.isNew),
          const SizedBox(width: 6),
          Flag(c.nationality),
          const SizedBox(width: 8),
          StateChip(d.state),
        ]),
        const SizedBox(height: 6),
        Text(line, style: Typo.body400.copyWith(color: Ms.gray600)),
        if (d.sedationRequired) ...[const SizedBox(height: 4), Text('수면 마취 필요', style: Typo.caption600.copyWith(color: Ms.purple))],
      ]),
    );
  }

  // 신분 확인 — [확인 완료] / [미확인으로](can.*) · [여권 스캔](이 기기 카메라 · D7-33)
  Widget _identity(ResvDetail d) {
    final id = d.customer.identity;
    final ok = id.status == 'confirmed';
    final how = switch (id.method) {
      'app_scan' => '앱 스캔${id.device != null ? ' · ${id.device}' : ''}',
      'app_manual' => '손으로 입력${id.device != null ? ' · ${id.device}' : ''}',
      _ => null,
    };
    return _box(
      title: '신분 확인',
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        Text(id.kind == 'foreign' ? '여권' : '신분증', style: Typo.body400.copyWith(color: Ms.gray500)),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(color: ok ? Ms.primary100 : Ms.yellow100, borderRadius: BorderRadius.circular(999)),
          child: Text(ok ? '확인 완료' : '미확인', style: Typo.caption600.copyWith(color: ok ? Ms.primary : Ms.yellow)),
        ),
      ]),
      children: [
        if (ok)
          Text(['확인 완료', ?id.checkedBy, if (id.checkedAt != null) hm(id.checkedAt), ?how].join(' · '),
              style: Typo.body400.copyWith(color: Ms.gray600)),
        if (id.fields.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Wrap(spacing: 6, runSpacing: 4, children: [
              for (final f in id.fields) MiniChip(f.label, f.filled ? Ms.primary100 : Ms.gray100, f.filled ? Ms.primary : Ms.gray500),
            ]),
          ),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (d.canDo('confirmIdentity') && !ok)
            MsButton('확인 완료',
                size: BtnSize.sm,
                variant: BtnVariant.outlined,
                onPressed: _busy ? null : () => _write(() => _app.api.setIdentity(d.customer.customerId, 'confirmed'), '저장했어요')),
          if (d.canDo('unconfirmIdentity') && ok)
            MsButton('미확인으로',
                size: BtnSize.sm,
                variant: BtnVariant.outlined,
                color: BtnColor.gray,
                onPressed: _busy ? null : () => _write(() => _app.api.setIdentity(d.customer.customerId, 'unconfirmed'), '저장했어요')),
          MsButton('여권 스캔', size: BtnSize.sm, onPressed: _busy ? null : () => _scan(d)),
          if (id.photoId != null)
            MsButton('사진 삭제', size: BtnSize.sm, variant: BtnVariant.outlined, color: BtnColor.red, onPressed: _busy ? null : () => _deletePhoto(id.photoId!)),
        ]),
      ],
    );
  }

  // 여권 사진 [삭제](웹 E2E batch 3 #1 과 같음) — 확인 한 번 → ccc 사진 · 그 사진으로 한 확인(→ 미확인) · KOS 이미지. 고객 값은 그대로
  // 실패(409 · 502) = 아무것도 안 지워짐 → 다시 누르면 됨
  Future<void> _deletePhoto(int photoId) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Ms.white,
        title: Text('여권 사진을 지울까요?', style: Typo.headingMd600),
        content: Text('KOS 사진도 지워지고 신분 확인이 「미확인」으로 바뀌어요. 고객 정보(여권번호 등)는 그대로예요.', style: Typo.body400),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('취소')),
          TextButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text('삭제', style: TextStyle(color: Ms.red))),
        ],
      ),
    );
    if (ok != true) return;
    String kos = '';
    await _write(() async => kos = await _app.api.deleteIdPhoto(photoId), null);
    if (kos.isNotEmpty) {
      _app.toaster.show(switch (kos) {
        'deleted' => '사진을 지웠어요 · KOS 사진도 지움',
        'not_found' => '사진을 지웠어요 · KOS 에는 없었어요',
        _ => '사진을 지웠어요',
      });
    }
  }

  // 자동 저장 실패 중 401 = 로그인 풀림
  void _saveError(ApiError e) {
    if (e.status == 401) _app.logout(message: '로그인이 풀렸어요 — 다시 로그인하세요');
  }

  Future<void> _scan(ResvDetail d) async {
    final f = openPassportScan;
    if (f == null) return _app.toaster.show('여권 스캔을 열 수 없어요');
    await f(context, d);
    await _load();
  }

  // [이 기기에 QR 보이기](SPEC-006 §8.2) — 고객이 휴대폰 카메라로 찍는 문진 QR
  Future<void> _questionnaireHere(ResvDetail d) async {
    await showQuestionnaireQrHere(context, d);
    await _load();
  }

  // 고객 기본 정보 — 웹과 같은 칸 · 연락처 보임(D7-32) · **늘 편집 · 칸마다 자동 저장**(웹 E2E batch 3 #4 — [수정] 없음) ·
  // 유입 채널 드롭다운(바로 저장 · #2) · [태블릿에 띄우기] · [이 기기에 QR 보이기]
  Widget _personal(ResvDetail d) {
    final p = d.customer.personal;
    final cid = d.customer.customerId;
    final edit = d.canDo('editPersonal') && p != null;
    String v(String? x) => (x ?? '').trim().isEmpty ? '-' : x!.trim();
    Widget row(String k, String val) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 104, child: Text(k, style: Typo.body400.copyWith(color: Ms.gray600))),
            Expanded(child: Text(val, style: Typo.body500.copyWith(color: val == '-' ? Ms.gray400 : Ms.gray800))),
          ]),
        );
    // 고칠 수 있는 글자 칸 — 그 칸 하나만 보낸다(back = 다시 읽은 묶음 전체 + 그 칸 · 같은 값이면 KOS 안 부름)
    Widget field(String key, String label, {String? hint, TextInputType? type}) => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: AutoSaveField(
            key: ValueKey('personal-$cid-$key'),
            label: label,
            hint: hint,
            keyboardType: type,
            enabled: edit,
            value: p?.s(key) ?? '',
            onSave: (x) => _app.api.savePersonal(cid, {key: x.trim().isEmpty ? null : x.trim()}),
            onError: _saveError,
          ),
        );
    final ph = p?.phone;
    final codes = d.funnelCodes;
    final funnel = codes.any((c) => c.funnelId == d.customer.funnelId) ? d.customer.funnelId : null;
    return _box(
      title: '고객 기본 정보',
      children: [
        if (d.customer.personalError != null)
          Text(d.customer.personalError!, style: Typo.caption600.copyWith(color: Ms.red))
        else ...[
          field('name', '이름'),
          field('phoneticName', '한글 발음'),
          row('성별', switch (p?.s('gender')) { 'MALE' => '남성', 'FEMALE' => '여성', _ => '-' }),
          field('dateOfBirth', '생년월일', hint: 'yyyy-MM-dd'),
          row('국적', v(nationName(p?.s('nationality')))),
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 8),
            child: AutoSaveField(
              key: ValueKey('personal-$cid-phone'),
              label: '휴대폰${(ph?.countryCode ?? '').isEmpty ? '' : ' (+${ph!.countryCode!.replaceAll('+', '')})'}',
              keyboardType: TextInputType.phone,
              enabled: edit,
              value: ph?.number ?? '',
              onSave: (x) => _app.api.savePersonal(cid, {'phone': {'countryCode': ph?.countryCode, 'number': x.trim()}}),
              onError: _saveError,
            ),
          ),
          row('SNS', [p?.sns['type'], p?.sns['accountId']].whereType<String>().where((x) => x.isNotEmpty).join(' · ').ifEmpty('-')),
          const SizedBox(height: 6),
          field('email', '이메일', type: TextInputType.emailAddress),
          field('passportSurname', '여권 영문 성'),
          field('passportGivenNames', '여권 영문 이름'),
          field('passportNumber', '여권번호'),
          field('passportExpiryDate', '여권 만료일', hint: 'yyyy-MM-dd'),
          // 유입 채널(KOS 고객 칸 · 예약 등록과 같은 코드) — 고르면 바로 저장
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(children: [
              Expanded(child: Text('유입 채널', style: Typo.body400.copyWith(color: Ms.gray600))),
              SaveStatus(_funnelState, onRetry: null),
            ]),
          ),
          DropdownButtonFormField<int?>(
            key: ValueKey('funnel-$cid-$funnel'),
            initialValue: funnel,
            isExpanded: true,
            hint: Text(d.customer.funnelName ?? '-', style: Typo.body400.copyWith(color: Ms.gray400)),
            items: [
              DropdownMenuItem<int?>(value: null, child: Text('-', style: Typo.body400)),
              for (final c in codes) DropdownMenuItem<int?>(value: c.funnelId, child: Text(c.name, style: Typo.body400)),
            ],
            onChanged: !edit || _funnelState == SaveState.saving
                ? null
                : (x) async {
                    if (x == funnel) return;
                    setState(() => _funnelState = SaveState.saving);
                    try {
                      await _app.api.saveFunnel(cid, x);
                      if (mounted) setState(() => _funnelState = SaveState.saved);
                      await _load();
                    } on ApiError catch (e) {
                      if (mounted) setState(() => _funnelState = SaveState.failed);
                      _saveError(e);
                      _app.toaster.show(e.message);
                    }
                  },
          ),
        ],
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          MsButton('태블릿에 띄우기', size: BtnSize.sm, variant: BtnVariant.outlined, onPressed: _busy ? null : () => sendQuestionnaireToDevice(context, d).then((_) => _load())),
          MsButton('이 기기에 QR 보이기', size: BtnSize.sm, variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _busy ? null : () => _questionnaireHere(d)),
        ]),
        for (final x in d.displays.where((x) => x.kind == 'questionnaire').take(1))
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(displayStep(x), style: Typo.caption500.copyWith(color: Ms.gray600)),
          ),
      ],
    );
  }

  // 예약 메모 · 주의사항 — [저장] 없음 · 자동 저장(웹 E2E batch 3 #3 · #5)
  Widget _memoBox(ResvDetail d) => _box(
        title: '예약 메모',
        children: [
          AutoSaveField(
            key: ValueKey('memo-${d.reservationId}'),
            value: d.memo ?? '',
            enabled: d.canDo('editMemo'),
            minLines: 2,
            maxLines: 6,
            hint: '예약 메모 없음',
            onSave: (x) => _app.api.saveMemo(d.reservationId, x),
            onError: _saveError,
          ),
        ],
      );

  Widget _remarkBox(ResvDetail d) => _box(
        title: '주의사항',
        children: [
          AutoSaveField(
            key: ValueKey('remark-${d.customer.customerId}'),
            value: d.customer.remark ?? '',
            enabled: d.canDo('editRemark'),
            minLines: 2,
            maxLines: 6,
            hint: '주의사항 없음',
            onSave: (x) => _app.api.saveRemark(d.customer.customerId, x),
            onError: _saveError,
          ),
        ],
      );

  Widget _health(ResvDetail d) => _box(
        title: '건강 정보',
        trailing: d.healthSubmittedAt != null ? Text('${hm(d.healthSubmittedAt)} 제출', style: Typo.caption400.copyWith(color: Ms.gray500)) : null,
        children: [
          if (d.healthState == 'none' || d.health.isEmpty)
            Text('고객이 문진을 작성하면 채워집니다', style: Typo.body400.copyWith(color: Ms.gray500))
          else if (d.healthState == 'error')
            Text('문진을 불러오지 못했어요', style: Typo.body400.copyWith(color: Ms.red))
          else
            for (final h in d.health)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(h.title, style: Typo.caption500.copyWith(color: Ms.gray600)),
                  Text(h.empty ? '미입력' : [h.answer, h.memo].whereType<String>().where((x) => x.isNotEmpty).join(' · '),
                      style: Typo.body500.copyWith(color: h.needsCheck ? Ms.red : (h.empty ? Ms.gray400 : Ms.gray800))),
                ]),
              ),
        ],
      );

  Widget _previous(ResvDetail d) => _box(
        title: '이전 방문 ${d.previousVisits.length}',
        children: [
          if (d.previousVisits.isEmpty) Text('없음', style: Typo.body400.copyWith(color: Ms.gray500)),
          for (final v in d.previousVisits.take(5))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                    '${v.date.replaceAll('-', '.')} · ${switch (v.result) { 'completed' => '방문 완료', 'noshow' => '노쇼', 'canceled' => '취소', _ => v.resultRaw ?? '' }}',
                    style: Typo.body600),
                if (v.procedures.isNotEmpty) Text(v.procedures.join(' · '), style: Typo.caption400.copyWith(color: Ms.gray700)),
                if ((v.consultationMemo ?? '').isNotEmpty) Text('상담 메모 · ${v.consultationMemo}', style: Typo.caption400.copyWith(color: Ms.gray600)),
              ]),
            ),
        ],
      );

  Widget _cancelRow(ResvDetail d) => MsButton('예약 취소',
      variant: BtnVariant.outlined,
      color: BtnColor.red,
      expand: true,
      onPressed: _busy
          ? null
          : () async {
              final reason = await showModalBottomSheet<String>(
                context: context,
                backgroundColor: Ms.white,
                barrierColor: Ms.dim,
                shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
                builder: (ctx) => SafeArea(
                  top: false,
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const SheetHandle(),
                    Padding(padding: const EdgeInsets.all(12), child: Text('${d.customer.name} 예약을 어떻게 닫을까요?', style: Typo.headingMd600)),
                    ListTile(title: Text('예약 취소', style: Typo.body600), onTap: () => Navigator.of(ctx).pop('CANCELED')),
                    ListTile(title: Text('예약 부도', style: Typo.body600.copyWith(color: Ms.red)), onTap: () => Navigator.of(ctx).pop('NO_SHOW')),
                    const SizedBox(height: 8),
                  ]),
                ),
              );
              if (reason != null) await _write(() => _app.api.cancelReservation(d.reservationId, reason), reason == 'NO_SHOW' ? '예약 부도' : '예약 취소');
            });

  // ── 접수(접수 전) + 내원 현황 단계 카드(접수 뒤 — SPEC-005 §6.6)
  List<Widget> _flowAll(ResvDetail d) => [
        // 웹 showReceiveBtn — receiveMode 있음(이어 하기) · 예약 · 부도
        if (d.receiveMode != null || d.state.main == ResvMain.reserved || d.state.main == ResvMain.noshow) _reception(d),
        if (d.flow != null) _flow(d),
      ];

  Widget _reception(ResvDetail d) {
    final selected = d.rooms.where((r) => r.selected).firstOrNull;
    final roomId = d.roomLocked ? selected?.roomId : (_room ?? selected?.roomId); // 잠긴 방 = 응답 값만
    final room = d.rooms.where((r) => r.roomId == roomId).firstOrNull;
    final can = d.canDo('receive') && roomId != null && !_busy;
    return _box(title: '접수', children: [
      Text('진행 경로', style: Typo.caption500.copyWith(color: Ms.gray600)),
      const SizedBox(height: 4),
      Row(children: [
        for (final o in const [('consultation', '상담 필요'), ('direct', '바로 시술')]) ...[
          Expanded(
            child: GestureDetector(
              onTap: d.canDo('editRoute') ? () => setState(() => _route = o.$1) : null,
              child: Container(
                height: 40,
                alignment: Alignment.center,
                margin: const EdgeInsets.only(right: 6),
                decoration: BoxDecoration(
                  color: _route == o.$1 ? Ms.primary100 : Ms.white,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: _route == o.$1 ? Ms.primary : Ms.gray300),
                ),
                child: Text(o.$2, style: Typo.body600.copyWith(color: _route == o.$1 ? Ms.primary : (d.canDo('editRoute') ? Ms.gray700 : Ms.gray400))),
              ),
            ),
          ),
        ],
      ]),
      const SizedBox(height: 10),
      MsButton(room != null ? '시술실 · ${room.title}' : '시술실 선택',
          variant: BtnVariant.outlined,
          color: room == null ? BtnColor.red : (d.roomLocked ? BtnColor.gray : BtnColor.blue),
          expand: true,
          onPressed: d.roomLocked ? null : () => _pickRoom(d)),
      const SizedBox(height: 8),
      MsButton(room != null ? '접수 완료 · ${room.title}' : '접수 완료',
          size: BtnSize.lg,
          expand: true,
          onPressed: can ? () => _write(() => _app.api.receive(d.reservationId, roomId, _route), '접수 완료 · ${room?.title ?? ''}') : null),
    ]);
  }

  // 시술실 시트 — 빈 방 아래 · 사용 중 위 회색 · 「{구역} · 빈 방 N개」(M:174-183 · SPEC-005 §5.7)
  Future<void> _pickRoom(ResvDetail d) async {
    final free = d.rooms.where((r) => !r.busy).length;
    final rooms = [...d.rooms]..sort((a, b) => (a.busy ? 0 : 1) - (b.busy ? 0 : 1)); // 사용 중 위
    final id = await showModalBottomSheet<int>(
      context: context,
      backgroundColor: Ms.white,
      barrierColor: Ms.dim,
      isScrollControlled: true,
      constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.7),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SheetHandle(),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 8),
            child: Row(children: [
              Expanded(child: Text('시술실 배정', style: Typo.headingMd500)),
              Text('${d.zoneTitle ?? ''} · 빈 방 $free개', style: Typo.body400.copyWith(color: Ms.gray500)),
            ]),
          ),
          if (rooms.isEmpty) Padding(padding: const EdgeInsets.all(20), child: Text('이 구역 방이 없어요', style: Typo.body400.copyWith(color: Ms.gray500))),
          Flexible(
            child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(12, 0, 12, 12), children: [
              for (final r in rooms)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Material(
                    color: r.busy ? Ms.gray100 : Ms.white,
                    borderRadius: BorderRadius.circular(8),
                    child: ListTile(
                    enabled: !r.busy,
                    title: Text(r.title, style: Typo.body600),
                    trailing: Text(r.busy ? '사용 중' : (r.roomId == _room ? '선택됨' : '비어있음'),
                        style: Typo.body500.copyWith(color: r.busy ? Ms.gray500 : Ms.primary)),
                    onTap: () => Navigator.of(ctx).pop(r.roomId),
                    ),
                  ),
                ),
            ]),
          ),
        ]),
      ),
    );
    if (id != null) setState(() => _room = id);
  }

  // 상담사 시트 — 비어있음 먼저 · 「{방} 상담 중」(M:254 · T:156-183)
  Future<void> _pickCounselor(ResvDetail d) async {
    final list = [...d.counselors]..sort((a, b) => (a.busyRoom == null ? 0 : 1) - (b.busyRoom == null ? 0 : 1));
    final id = await showModalBottomSheet<int>(
      context: context,
      backgroundColor: Ms.white,
      barrierColor: Ms.dim,
      isScrollControlled: true,
      constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.7),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SheetHandle(),
          Padding(padding: const EdgeInsets.fromLTRB(20, 8, 20, 8), child: Align(alignment: Alignment.centerLeft, child: Text('상담사 선택', style: Typo.headingMd500))),
          Flexible(
            child: ListView(shrinkWrap: true, padding: const EdgeInsets.fromLTRB(12, 0, 12, 12), children: [
              for (final x in list)
                ListTile(
                  leading: CircleAvatar(backgroundColor: Ms.cons100, child: Text(x.name.characters.first, style: Typo.body600.copyWith(color: Ms.cons))),
                  title: Text(x.name, style: Typo.body600),
                  trailing: Text(x.busyRoom != null ? '${x.busyRoom} 상담 중' : '비어있음',
                      style: Typo.body500.copyWith(color: x.busyRoom != null ? Ms.gray500 : Ms.cons)),
                  onTap: () => Navigator.of(ctx).pop(x.staffId),
                ),
            ]),
          ),
        ]),
      ),
    );
    if (id != null) setState(() => _counselor = id);
  }

  Widget _flow(ResvDetail d) {
    final f = d.flow!;
    final cons = f.consultation;
    final consActive = cons != null && (cons.state == 'waiting' || cons.state == 'doing');
    final consTitle = switch (cons?.state) { 'waiting' => '상담 대기', 'doing' => '상담 진행 중', 'done' => '상담 완료', _ => '상담' };
    final pick = d.counselors.where((x) => x.staffId == _counselor).firstOrNull;
    final procName = {'none': '시술', 'waiting': '시술 대기', 'doing': '시술 진행 중', 'done': '시술 완료'}[f.procedure] ?? '시술';
    final homeName = {'none': '귀가', 'waiting': '귀가 대기', 'done': '귀가 완료'}[f.home] ?? '귀가';
    final recPhase = d.state.main == ResvMain.reception ? Phase.waiting : Phase.done;
    final st = d.settlement;
    Phase ph(String s) => switch (s) { 'waiting' => Phase.waiting, 'doing' => Phase.doing, 'done' => Phase.done, _ => Phase.none };
    return _box(
      key: _consKey,
      title: '내원 현황',
      trailing: isClosed(d.state.main)
          ? null
          : MsButton('+ 상담 추가',
              size: BtnSize.sm,
              variant: BtnVariant.outlined,
              onPressed: d.canDo('addConsultation') && !_busy ? () => _write(() => _app.api.addConsultation(d.reservationId), '상담 추가') : null),
      children: [
        _Stage(
          name: '접수 완료',
          main: ResvMain.reception,
          phase: recPhase,
          detail: [if (f.roomTitle != null) '${f.roomTitle} 배정', if (f.receptionBy != null) '데스크 ${f.receptionBy}'].join(' · '),
          at: f.receptionAt,
        ),
        if (cons != null)
          _Stage(
            name: consTitle,
            main: ResvMain.consultation,
            phase: ph(cons.state),
            detail: (cons.counselorName ?? '상담사를 선택하세요') + (cons.calledAt != null ? ' · ${cons.counselorName ?? ''} 실장 호출됨 · ${hm(cons.calledAt)}' : ''),
            at: f.tCons ?? (cons.state == 'doing' ? cons.since : (cons.calledAt ?? cons.since)),
            action: consActive && d.counselors.isNotEmpty
                ? Wrap(spacing: 6, runSpacing: 6, children: [
                    MsButton(cons.counselorName != null ? '상담사 변경' : '상담사 선택',
                        size: BtnSize.sm, variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _busy ? null : () => _pickCounselor(d)),
                    if (pick != null)
                      MsButton('${pick.name} 실장 호출',
                          size: BtnSize.sm,
                          onPressed: d.canDo('callCounselor') && !_busy
                              ? () async {
                                  if (await _write(() => _app.api.callCounselor(d.reservationId, pick.staffId), '${pick.name} 실장 호출')) {
                                    setState(() => _counselor = null);
                                  }
                                }
                              : null),
                  ])
                : null,
          ),
        _Stage(
          name: procName,
          main: ResvMain.procedure,
          phase: ph(f.procedure),
          at: f.tProc,
          action: f.procedure == 'waiting' || f.procedure == 'doing'
              ? MsButton('시술 현황 ›', size: BtnSize.sm, variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: () => _toBoard(f.roomTitle))
              : null,
        ),
        _Stage(
          name: homeName,
          main: ResvMain.home,
          phase: ph(f.home),
          at: f.tHome,
          action: d.state.main == ResvMain.home && st != null
              ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  // 정산 — 글자만(수납 · 처방전 버튼 없음 · D7-06)
                  Row(children: [
                    _Pay('전체 금액', moneyOf(st.amount, true), false),
                    const SizedBox(width: 6),
                    _Pay('결제 금액', moneyOf(st.amount, false), false),
                    const SizedBox(width: 6),
                    _Pay('수납 필요', st.paymentRequiredCount > 0 ? '${st.paymentRequiredCount}건' : '-', st.paymentRequiredCount > 0),
                  ]),
                  const SizedBox(height: 6),
                  Text(st.prescriptionCount > 0 ? '처방전 ${st.prescriptionCount}건' : '오늘 처방전 없음', style: Typo.body400.copyWith(color: Ms.gray700)),
                  if (d.state.sub != ResvSub.done) ...[
                    const SizedBox(height: 8),
                    MsButton('귀가 완료',
                        size: BtnSize.lg,
                        expand: true,
                        onPressed: d.canDo('discharge') && !_busy
                            ? () async {
                                setState(() => _busy = true);
                                final ok = await _app.run(() => _app.api.discharge(d.reservationId), '${d.customer.name} 귀가 완료');
                                if (!mounted) return;
                                setState(() => _busy = false);
                                if (ok) {
                                  Navigator.of(context).maybePop();
                                } else {
                                  await _load();
                                }
                              }
                            : null),
                  ],
                ])
              : null,
        ),
      ],
    );
  }

  // [시술 현황] — 시술 현황 탭 그 방 룸 상세(M:257) · 방을 판에서 찾는다
  void _toBoard(String? roomTitle) {
    final b = _app.stream.board;
    final card = b?.cards.where((c) => c.room.title == roomTitle).firstOrNull;
    _app.tab.value = AppTab.board;
    if (card != null) {
      _app.openVisit.value = card.visitId;
    } else {
      _app.toaster.show('시술 현황에서 방을 찾지 못했어요');
    }
  }
}

// 띄우기 단계 글자(§6.17 과 같은 뜻) — 대기 → 열림 → 제출됨 · HH:MM
String displayStep(DisplayItem x) {
  final who = x.deviceName ?? 'QR';
  // 문진 = 고객 폰 웹(SPEC-006 §8.1 단계) — pending = QR 보이는 중 · opened = 고객이 입력 중
  return switch (x.status) {
    'pending' => '$who QR 표시 중',
    'opened' => '고객이 입력 중${x.openedAt == null ? '' : ' · ${hm(x.openedAt)}'}',
    'done' => '제출됨 · ${hm(x.closedAt)}',
    'canceled' => '$who 닫힘',
    'expired' => '$who 시간 지남',
    _ => '',
  };
}

// 단계 카드 — 지난 단계 회색 · 지금 단계만 그 색(phaseStyle · SPEC-005 §6.6)
class _Stage extends StatelessWidget {
  final String name;
  final ResvMain main;
  final Phase phase;
  final String detail;
  final String? at;
  final Widget? action;
  const _Stage({required this.name, required this.main, required this.phase, this.detail = '', this.at, this.action});

  @override
  Widget build(BuildContext context) {
    final p = phaseStyle(main, phase);
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(color: p.cardBg, borderRadius: BorderRadius.circular(10), border: Border.all(color: p.cardBorder)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(color: p.dotFill, shape: BoxShape.circle, border: Border.all(color: p.dotBorder, width: 2)),
          ),
          const SizedBox(width: 8),
          Text(name, style: Typo.body600.copyWith(color: p.title)),
          const SizedBox(width: 8),
          Expanded(child: Text(detail, maxLines: 2, overflow: TextOverflow.ellipsis, style: Typo.caption500.copyWith(color: p.sub))),
          if (at != null) Text(hm(at), style: Typo.caption500.copyWith(color: p.sub, fontFeatures: tabular)),
        ]),
        if (action != null) ...[const SizedBox(height: 8), action!],
      ]),
    );
  }
}

class _Pay extends StatelessWidget {
  final String k, v;
  final bool red;
  const _Pay(this.k, this.v, this.red);
  @override
  Widget build(BuildContext context) => Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(color: red ? Ms.red100 : Ms.gray100, borderRadius: BorderRadius.circular(6)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(k, style: Typo.caption400.copyWith(color: Ms.gray500)),
            Text(v, maxLines: 1, overflow: TextOverflow.ellipsis, style: Typo.body600.copyWith(color: red ? Ms.red : Ms.gray800, fontFeatures: tabular)),
          ]),
        ),
      );
}

extension on String {
  String ifEmpty(String v) => isEmpty ? v : this;
}
