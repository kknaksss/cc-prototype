// 문진 화면 — 고객용(SPEC-004 §6.15 · D7-13 ~ D7-16 · D7-45 ~ D7-47 · 시안 없음 → DS 기본값).
// 잠금: 탭바 · 레일 · 공통 헤더(루트 내비게이터 전체 화면이라 가려짐) · 앱 안 배너(토스트 끔) · 뒤로 가기 · 가장자리 밀기 막음.
// 나가기 = 오른쪽 위 작은 [직원] 1.5초 길게 → 지금 로그인 아이디의 비밀번호 → POST /api/auth/unlock {password, deviceId}(기기별 5회 · 1분).
// 차례: 언어 칩 6 · 「{이름} 님」 · [시작] → 기본 정보(미리 채움) → KOS 양식 쪽마다 → 동의 → 제출 → 「감사합니다」 → 3초 뒤 잠긴 대기 화면
import 'dart:async';

import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../l10n/questionnaire_text.dart';
import '../model/display.dart';
import '../model/questionnaire.dart';
import '../theme/tokens.dart';
import '../widgets/ui.dart';

// 이 기기에서 문진을 연다(띄우기 · QR · 예약 상세 [이 기기에서 열기]) — 나갈 때까지 기다린다
Future<void> showQuestionnaire(BuildContext context, int reservationId, {int? displayRequestId}) =>
    Navigator.of(context, rootNavigator: true).push(PageRouteBuilder(
      opaque: true,
      fullscreenDialog: true,
      pageBuilder: (_, _, _) => QuestionnaireScreen(reservationId: reservationId, displayRequestId: displayRequestId),
    ));

enum _Step { loading, loadFailed, start, basic, page, agree, thanks, waiting }

class QuestionnaireScreen extends StatefulWidget {
  final int reservationId;
  final int? displayRequestId;
  const QuestionnaireScreen({super.key, required this.reservationId, this.displayRequestId});
  @override
  State<QuestionnaireScreen> createState() => _QuestionnaireScreenState();
}

class _QuestionnaireScreenState extends State<QuestionnaireScreen> {
  late final AppState _app;
  late int _rid = widget.reservationId;
  late int? _req = widget.displayRequestId;
  QForm? _form;
  String _lang = 'en';
  _Step _step = _Step.loading;
  int _page = 0;
  bool _sending = false, _failed = false, _submitted = false;
  QAnswers _ans = QAnswers();
  final Map<String, bool> _agreed = {};
  Timer? _toWait;

  // 기본 정보(미리 채움 · 고객이 고칠 수 있음)
  final _name = TextEditingController();
  final _dob = TextEditingController();
  final _cc = TextEditingController();
  final _phone = TextEditingController();
  final _addr = TextEditingController();
  final _addr2 = TextEditingController();
  String? _gender;
  final Map<String, TextEditingController> _texts = {};

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.toaster.muted = true;
    _app.displays.addListener(_onDisplays);
    _load();
  }

  @override
  void dispose() {
    _toWait?.cancel();
    _app.toaster.muted = false;
    _app.displays.removeListener(_onDisplays);
    for (final c in [_name, _dob, _cc, _phone, _addr, _addr2, ..._texts.values]) {
      c.dispose();
    }
    super.dispose();
  }

  // 대기 화면에서 다음 문진 요청이 오면 바로 연다(§6.15 ⑦)
  void _onDisplays() {
    if (_step != _Step.waiting) return;
    final next = _app.displays.value.where((x) => x.kind == 'questionnaire').firstOrNull;
    if (next == null) return;
    _app.markDisplayOpened(next.requestId); // 대기 화면이 직접 연 것도 다시 열지 않게(r1 W1)
    _openNext(next);
  }

  void _openNext(DisplayReq r) {
    setState(() {
      _rid = r.reservationId;
      _req = r.requestId;
      _ans = QAnswers();
      _agreed.clear();
      _texts.clear();
      _submitted = false;
      _failed = false;
      _page = 0;
      _step = _Step.loading;
    });
    _load();
  }

  Future<void> _load() async {
    try {
      final f = await _app.api.questionnaire(_rid, deviceId: _app.deviceId);
      if (!mounted) return;
      final p = f.prefill;
      final ph = p['phone'] is Map ? (p['phone'] as Map) : const {};
      _name.text = '${p['name'] ?? ''}';
      _dob.text = '${p['dateOfBirth'] ?? ''}'; // yyyyMMdd(후속 #2)
      _cc.text = '${ph['countryCode'] ?? ''}';
      _phone.text = '${ph['phoneNumber'] ?? ''}'; // KOS 값 그대로(앞 0 빠질 수 있음 · r2)
      _addr.text = '${p['address'] ?? ''}';
      _addr2.text = '${p['addressDetail'] ?? ''}';
      _gender = p['gender'] as String?;
      setState(() {
        _form = f;
        _lang = f.options.contains(f.language) ? f.language : 'en';
        _step = _Step.start;
      });
    } on ApiError {
      if (mounted) setState(() => _step = _Step.loadFailed);
    }
  }

  // ── 제출(§6.15 ⑥)
  bool get _basicOk => _name.text.trim().isNotEmpty && RegExp(r'^\d{8}$').hasMatch(_dob.text.trim()) && _gender != null;
  bool get _agreeOk => (_form?.agreements ?? const []).where((a) => a['required'] == true).every((a) => _agreed['${a['id']}'] == true);

  Future<void> _submit() async {
    final f = _form!;
    for (final e in _texts.entries) {
      _ans.text[e.key] = e.value.text;
    }
    setState(() {
      _sending = true;
      _failed = false;
    });
    final body = <String, dynamic>{
      'displayRequestId': ?_req,
      'deviceId': ?_app.deviceId,
      'language': _lang,
      'name': _name.text.trim(),
      'dateOfBirth': _dob.text.trim(),
      'gender': _gender,
      'phone': {'countryCode': _cc.text.trim(), 'phoneNumber': _phone.text.trim()},
      'address': _addr.text.trim(),
      'addressDetail': _addr2.text.trim(),
      'agreements': [for (final a in f.agreements) {...a, 'agreed': _agreed['${a['id']}'] == true}],
      'answers': _ans.toJson(f.pages),
    };
    try {
      await _app.api.submitQuestionnaire(_rid, body);
      if (!mounted) return;
      setState(() {
        _sending = false;
        _submitted = true;
        _step = _Step.thanks;
      });
      _toWait = Timer(const Duration(seconds: 3), () {
        if (!mounted) return;
        setState(() => _step = _Step.waiting);
        _onDisplays();
      });
    } on ApiError {
      // KOS 400 · 5xx = 「제출하지 못했어요 · 직원에게」 + [다시 제출] · 입력값 유지
      if (mounted) {
        setState(() {
          _sending = false;
          _failed = true;
        });
      }
    }
  }

  // ── 나가기 — [직원] 길게 → 비밀번호 → unlock
  Future<void> _staff() async {
    final ctl = TextEditingController();
    String? err;
    var busy = false;
    final ok = await showDialog<bool>(
      context: context,
      barrierDismissible: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          backgroundColor: Ms.white,
          title: Text('직원 확인', style: Typo.headingMd600),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('${_app.session?.id ?? ''} 비밀번호를 넣으면 문진 화면을 나가요', style: Typo.body400.copyWith(color: Ms.gray700)),
            const SizedBox(height: 8),
            TextField(key: const Key('unlock-password'), controller: ctl, obscureText: true, autofocus: true, decoration: const InputDecoration(hintText: '비밀번호')),
            if (err != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(err!, style: Typo.caption600.copyWith(color: Ms.red))),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('취소')),
            TextButton(
              onPressed: busy
                  ? null
                  : () async {
                      set(() => busy = true);
                      try {
                        await _app.api.unlock(ctl.text, deviceId: _app.deviceId);
                        if (ctx.mounted) Navigator.of(ctx).pop(true);
                      } on ApiError catch (e) {
                        set(() {
                          busy = false;
                          err = e.message; // 401 「아이디 또는 비밀번호가 맞지 않아요」 · 429 「여러 번 틀렸어요. 1분 뒤 다시 시도해 주세요」
                        });
                      }
                    },
              child: const Text('나가기'),
            ),
          ],
        ),
      ),
    );
    Future<void>.delayed(const Duration(milliseconds: 400), ctl.dispose); // 닫히는 애니메이션 동안 칸이 아직 쓴다
    if (ok != true || !mounted) return;
    // 제출 전이면 띄우기 요청 canceled
    final r = _req;
    if (r != null && !_submitted) {
      try {
        await _app.api.closeDisplay(r, 'canceled');
      } on ApiError {
        // 이미 닫힘 · 만료 — 그대로 나간다
      }
    }
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final f = _form;
    return PopScope(
      canPop: false, // 뒤로 가기 · 가장자리 밀기 막음
      child: Scaffold(
        backgroundColor: Ms.white,
        body: SafeArea(
          child: Column(children: [
            // 위 — 언어 칩(문진 단계 동안) · 오른쪽 작은 [직원]
            SizedBox(
              height: 52,
              child: Row(children: [
                Expanded(
                  child: f == null || _step == _Step.waiting || _step == _Step.thanks
                      ? const SizedBox()
                      : ListView(
                          scrollDirection: Axis.horizontal,
                          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
                          children: [
                            for (final l in f.options)
                              Padding(
                                padding: const EdgeInsets.only(right: 6),
                                child: _LangChip(qLangName[l] ?? l, l == _lang, () => setState(() => _lang = l)),
                              ),
                          ],
                        ),
                ),
                _StaffButton(onTrigger: _staff),
              ]),
            ),
            Expanded(child: _body(f)),
          ]),
        ),
      ),
    );
  }

  Widget _body(QForm? f) {
    final l = _lang;
    switch (_step) {
      case _Step.loading:
        return const Center(child: CircularProgressIndicator(strokeWidth: 2));
      case _Step.loadFailed:
        return _center([
          Text(qt('loadFailed', l), textAlign: TextAlign.center, style: Typo.titleSm600.copyWith(color: Ms.red)),
          const SizedBox(height: 16),
          MsButton(qt('retry', l), onPressed: () {
            setState(() => _step = _Step.loading);
            _load();
          }),
        ]);
      case _Step.start:
        return _center([
          Text(qt('hello', l, name: f!.customerName), textAlign: TextAlign.center, style: Typo.titleMd600.copyWith(fontSize: 28)),
          const SizedBox(height: 12),
          Text(qt('intro', l), textAlign: TextAlign.center, style: Typo.headingMd400.copyWith(color: Ms.gray700)),
          const SizedBox(height: 32),
          SizedBox(width: 280, child: MsButton(qt('start', l), size: BtnSize.lg, expand: true, onPressed: () => setState(() => _step = _Step.basic))),
        ]);
      case _Step.basic:
        return _frame(
          title: qt('basic', l),
          progress: 0,
          body: [
            _field(qt('name', l), _name, req: true),
            _field('${qt('dob', l)} (YYYYMMDD)', _dob, req: true, keyboard: TextInputType.number),
            _label(qt('gender', l), req: true),
            Wrap(spacing: 8, children: [
              for (final g in const ['FEMALE', 'MALE'])
                _Choice(qt(g == 'FEMALE' ? 'female' : 'male', l), _gender == g, () => setState(() => _gender = g)),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              SizedBox(width: 96, child: _field('+', _cc, keyboard: TextInputType.number)),
              const SizedBox(width: 8),
              Expanded(child: _field(qt('phone', l), _phone, keyboard: TextInputType.phone)),
            ]),
            _field(qt('address', l), _addr),
            _field(qt('addressDetail', l), _addr2),
          ],
          canNext: _basicOk,
          onPrev: () => setState(() => _step = _Step.start),
          onNext: () => setState(() {
            _page = 0;
            _step = f!.pages.isEmpty ? _Step.agree : _Step.page;
          }),
        );
      case _Step.page:
        final p = f!.pages[_page];
        for (final q in p.questions) {
          for (final a in q.answers.where((a) => a.isInput || a.isSubText)) {
            _texts.putIfAbsent(a.id, () => TextEditingController());
          }
        }
        return _frame(
          title: p.label(l),
          progress: _page + 1,
          body: [for (final q in p.questions) _question(q)],
          canNext: _ans.pageDone(p),
          onPrev: () => setState(() => _page == 0 ? _step = _Step.basic : _page--),
          onNext: () => setState(() => _page + 1 < f.pages.length ? _page++ : _step = _Step.agree),
        );
      case _Step.agree:
        final ag = f!.agreements;
        final key = agreementLang(l);
        return _frame(
          title: qt('agree', l),
          progress: f.pages.length + 1,
          body: [
            if (ag.length > 1)
              _Check(qt('agreeAll', l), ag.every((a) => _agreed['${a['id']}'] == true), () {
                final all = ag.every((a) => _agreed['${a['id']}'] == true);
                setState(() {
                  for (final a in ag) {
                    _agreed['${a['id']}'] = !all;
                  }
                });
              }),
            for (final a in ag)
              _Check(
                '${key.isEmpty ? a['title'] : trOf(a, 'title', key, '${a['title'] ?? ''}')}${a['required'] == true ? ' (${qt('required', l)})' : ''}',
                _agreed['${a['id']}'] == true,
                () => setState(() => _agreed['${a['id']}'] = !(_agreed['${a['id']}'] ?? false)),
              ),
            if (_failed)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(qt('failed', l), style: Typo.headingMd600.copyWith(color: Ms.red)),
              ),
          ],
          canNext: _agreeOk && !_sending,
          nextLabel: _sending ? qt('sending', l) : (_failed ? qt('retry', l) : qt('submit', l)),
          onPrev: () => setState(() {
            if (f.pages.isEmpty) {
              _step = _Step.basic;
            } else {
              _page = f.pages.length - 1;
              _step = _Step.page;
            }
          }),
          onNext: _submit,
        );
      case _Step.thanks:
        return _center([
          const Icon(Icons.check_circle_rounded, size: 72, color: Ms.primary),
          const SizedBox(height: 16),
          Text(qt('thanks', l), style: Typo.titleMd600.copyWith(fontSize: 28)),
          const SizedBox(height: 8),
          Text(qt('thanksSub', l), style: Typo.headingMd400.copyWith(color: Ms.gray700)),
        ]);
      case _Step.waiting:
        // 잠긴 대기 화면 — 나가는 길은 [직원] 길게뿐(r2)
        return _center([
          Text('Céramique', style: Typo.titleMd600.copyWith(fontSize: 32, color: Ms.primary, fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),
          Text(qt('waiting', l), style: Typo.headingMd400.copyWith(color: Ms.gray600)),
        ]);
    }
  }

  Widget _center(List<Widget> kids) => Center(
        child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, children: kids)),
      );

  // 한 쪽 꼴 — 제목 · 진행 점 · 내용 · [이전] [다음]
  Widget _frame({
    required String title,
    required int progress,
    required List<Widget> body,
    required bool canNext,
    required VoidCallback onPrev,
    required VoidCallback onNext,
    String? nextLabel,
  }) {
    final total = (_form?.pages.length ?? 0) + 2;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 8, 24, 8),
            child: Row(children: [
              Expanded(child: Text(title, style: Typo.titleMd600.copyWith(fontSize: 24))),
              Text('${progress + 1} / $total', style: Typo.body500.copyWith(color: Ms.gray600, fontFeatures: tabular)),
            ]),
          ),
          Expanded(
            child: ListView(padding: const EdgeInsets.fromLTRB(24, 8, 24, 24), children: body),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
            child: Row(children: [
              Expanded(child: MsButton(qt('prev', _lang), size: BtnSize.lg, variant: BtnVariant.outlined, color: BtnColor.gray, expand: true, onPressed: _sending ? null : onPrev)),
              const SizedBox(width: 12),
              Expanded(flex: 2, child: MsButton(nextLabel ?? qt('next', _lang), size: BtnSize.lg, expand: true, onPressed: canNext ? onNext : null)),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _label(String t, {bool req = false}) => Padding(
        padding: const EdgeInsets.only(bottom: 6, top: 4),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: t, style: Typo.headingMd600),
          if (req) TextSpan(text: ' *', style: Typo.headingMd600.copyWith(color: Ms.red)),
        ])),
      );

  Widget _field(String label, TextEditingController c, {bool req = false, TextInputType? keyboard}) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _label(label, req: req),
          TextField(
            controller: c,
            keyboardType: keyboard,
            style: Typo.headingMd400,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
          ),
        ]),
      );

  // KOS 질문 — CHECK_BOX 여럿 · SELECT_BOX 하나 · INPUT_BOX 글 · isSubText 고르면 글칸
  Widget _question(QQuestion q) {
    final l = _lang;
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _label(q.label(l), req: q.required),
        if (q.input)
          TextField(
            controller: _texts[q.answers.first.id],
            style: Typo.headingMd400,
            onChanged: (v) => setState(() => _ans.text[q.answers.first.id] = v),
            decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
          )
        else ...[
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final a in q.answers) _Choice(a.label(l), _ans.isPicked(q, a), () => setState(() => _ans.toggle(q, a)), square: !q.single),
          ]),
          for (final a in q.answers.where((a) => a.isSubText && _ans.isPicked(q, a)))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: TextField(
                controller: _texts[a.id],
                style: Typo.headingMd400,
                onChanged: (v) => _ans.text[a.id] = v,
                decoration: InputDecoration(border: const OutlineInputBorder(), isDense: true, hintText: '${a.label(l)} · ${qt('other', l)}'),
              ),
            ),
        ],
      ]),
    );
  }
}

class _LangChip extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback onTap;
  const _LangChip(this.text, this.on, this.onTap);
  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: on ? Ms.primary : Ms.white,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: on ? Ms.primary : Ms.gray300),
          ),
          child: Text(text, style: Typo.body600.copyWith(color: on ? Ms.white : Ms.gray700, height: 1.2)),
        ),
      );
}

class _Choice extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback onTap;
  final bool square;
  const _Choice(this.text, this.on, this.onTap, {this.square = false});
  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: BoxDecoration(
            color: on ? Ms.primary100 : Ms.white,
            borderRadius: BorderRadius.circular(square ? 10 : 24),
            border: Border.all(color: on ? Ms.primary : Ms.gray300, width: on ? 2 : 1),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(on ? (square ? Icons.check_box_rounded : Icons.radio_button_checked_rounded) : (square ? Icons.check_box_outline_blank_rounded : Icons.radio_button_off_rounded),
                size: 20, color: on ? Ms.primary : Ms.gray500),
            const SizedBox(width: 8),
            Flexible(child: Text(text, style: Typo.headingMd500.copyWith(color: on ? Ms.primary : Ms.gray800))),
          ]),
        ),
      );
}

class _Check extends StatelessWidget {
  final String text;
  final bool on;
  final VoidCallback onTap;
  const _Check(this.text, this.on, this.onTap);
  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(on ? Icons.check_box_rounded : Icons.check_box_outline_blank_rounded, size: 26, color: on ? Ms.primary : Ms.gray500),
            const SizedBox(width: 10),
            Expanded(child: Text(text, style: Typo.headingMd500)),
          ]),
        ),
      );
}

// 오른쪽 위 작은 [직원] — 1.5초 길게 눌러야 열린다
class _StaffButton extends StatefulWidget {
  final VoidCallback onTrigger;
  const _StaffButton({required this.onTrigger});
  @override
  State<_StaffButton> createState() => _StaffButtonState();
}

class _StaffButtonState extends State<_StaffButton> {
  Timer? _t;
  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Listener(
        onPointerDown: (_) => _t = Timer(const Duration(milliseconds: 1500), widget.onTrigger),
        onPointerUp: (_) => _t?.cancel(),
        onPointerCancel: (_) => _t?.cancel(),
        child: Semantics(
          button: true,
          label: '직원',
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 8, 16, 8),
            child: Text('직원', style: Typo.caption500.copyWith(color: Ms.gray400)),
          ),
        ),
      );
}
