// 통역 드로어(SPEC-004 §6.5) — 높이 92%. 열면 마이크 · WS 를 열고, 닫으면 대화를 기기에서 지운다(요약 한 줄만 남김)
import 'package:flutter/material.dart';

import '../app_state.dart';
import '../config/server.dart';
import '../interpret/audio_io.dart';
import '../interpret/interpret_client.dart';
import '../interpret/langs.dart';
import '../theme/tokens.dart';
import '../view/time.dart';
import 'interpret_bar.dart';
import 'ui.dart';

class InterpretDrawer extends StatefulWidget {
  final bool tablet;
  final String room;
  final String customerName;
  final String? nationality;
  final String langCode;
  final bool traditional;
  final String autoCode;
  final void Function(String code) onLang;
  final void Function(String? summary) onClose;
  const InterpretDrawer({
    super.key,
    required this.tablet,
    required this.room,
    required this.customerName,
    required this.nationality,
    required this.langCode,
    required this.traditional,
    required this.autoCode,
    required this.onLang,
    required this.onClose,
  });
  @override
  State<InterpretDrawer> createState() => _InterpretDrawerState();
}

class _Line {
  final String side;
  String original;
  String translation;
  bool isFinal;
  _Line(this.side, this.original, this.translation, this.isFinal);
}

class _InterpretDrawerState extends State<InterpretDrawer> {
  final Mic _mic = Mic();
  final PcmPlayer _player = PcmPlayer();
  InterpretClient? _client;
  InterpState _state = InterpState.connecting;
  String? _error;
  bool _micDenied = false;
  final Map<String, _Line> _lines = {}; // 삽입 순서 = 대화 순서
  int _local = 0;
  bool _langOpen = false;
  final DateTime _opened = DateTime.now();
  late final AppState _app;
  bool _shown = false;

  @override
  void initState() {
    super.initState();
    _app = AppScope.read(context);
    _app.backgrounded.addListener(_onBackground);
    WidgetsBinding.instance.addPostFrameCallback((_) => setState(() => _shown = true));
    _start();
  }

  @override
  void didUpdateWidget(InterpretDrawer old) {
    super.didUpdateWidget(old);
    // 언어를 바꾸면 지금 WS 를 stop 하고 새 start 로 다시 연다
    if (old.langCode != widget.langCode || old.traditional != widget.traditional) _restart();
  }

  @override
  void dispose() {
    _app.backgrounded.removeListener(_onBackground);
    _teardown();
    super.dispose();
  }

  void _onBackground() => _close(); // 앱이 백그라운드로 가면 닫는다(§4.3)

  Future<void> _start() async {
    setState(() {
      _state = InterpState.connecting;
      _error = null;
      _micDenied = false;
    });
    final token = _app.session?.token;
    if (token == null) return;
    if (!await _mic.permitted()) {
      if (!mounted) return;
      setState(() {
        _state = InterpState.error;
        _micDenied = true;
        _error = '마이크를 쓸 수 없어요 — 설정 → 시술 현황 → 마이크를 켜 주세요';
      });
      return;
    }
    try {
      await configureSession();
    } catch (_) {}
    final client = InterpretClient(
      uri: interpretUri(_app.server.base),
      token: token,
      lang: widget.langCode,
      traditional: widget.traditional,
      sink: _player,
      cb: InterpCallbacks(
        onState: (s) {
          if (mounted) setState(() => _state = s);
        },
        onCaption: (c) {
          if (!mounted) return;
          setState(() {
            final l = _lines[c.key];
            if (l == null) {
              _lines[c.key] = _Line(c.side, c.original, c.translation, c.isFinal);
            } else {
              l
                ..original = c.original
                ..translation = c.translation
                ..isFinal = c.isFinal;
            }
          });
        },
        onError: (kind, msg) {
          if (mounted) setState(() => _error = msg);
          if (kind == InterpErrorKind.auth) _app.toaster.show(msg);
        },
        onPlayback: (_) {
          if (mounted) setState(() {});
        },
      ),
    );
    _client = client;
    await client.connect();
    if (!mounted || _client != client || client.state == InterpState.error) return;
    try {
      await _mic.start((chunk) => _client?.sendPcm(chunk));
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _state = InterpState.error;
        _error = '마이크 소리를 받지 못했어요';
      });
      await client.close();
    }
  }

  Future<void> _teardown() async {
    final c = _client;
    _client = null;
    await _mic.stop();
    await c?.close();
    await _player.flush();
  }

  Future<void> _restart() async {
    await _teardown();
    if (mounted) await _start();
  }

  Future<void> _close() async {
    final n = _lines.values.where((l) => l.isFinal).length;
    final summary = n > 0 ? '마지막 통역 ${hmMs(DateTime.now().millisecondsSinceEpoch)} · $n문장' : null;
    setState(() => _shown = false);
    await _teardown();
    await Future<void>.delayed(const Duration(milliseconds: 220));
    widget.onClose(summary);
  }

  @override
  Widget build(BuildContext context) {
    final h = MediaQuery.sizeOf(context).height;
    return Stack(children: [
      Positioned.fill(
        child: GestureDetector(
          onTap: _close,
          child: AnimatedOpacity(opacity: _shown ? 1 : 0, duration: const Duration(milliseconds: 240), child: Container(color: Ms.dim)),
        ),
      ),
      AnimatedPositioned(
        duration: const Duration(milliseconds: 300),
        curve: const Cubic(0.2, 0.8, 0.2, 1),
        left: 0,
        right: 0,
        bottom: _shown ? 0 : -h * 0.92,
        height: h * 0.92,
        child: Material(
          color: Ms.white,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
          clipBehavior: Clip.antiAlias,
          elevation: 12,
          child: Column(children: [
            GestureDetector(onTap: _close, child: const SheetHandle()),
            _head(),
            if (_langOpen) _langChips(),
            Expanded(child: widget.tablet ? Row(children: [Expanded(child: _talk()), _sidePhrases()]) : _talk()),
            if (!widget.tablet)
              Container(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                decoration: const BoxDecoration(border: Border(top: BorderSide(color: Ms.gray200))),
                child: PhraseChips(langCode: widget.langCode, traditional: widget.traditional, height: 36, icon: false, onSaid: _said),
              ),
            if (_error != null) _errorLine(),
            _micRow(),
          ]),
        ),
      ),
    ]);
  }

  // 빠른 말하기 — 대화에 의료진 말로 한 줄(서버로는 안 보냄 · §5)
  void _said(Phrase p, String tr) {
    setState(() => _lines['local:${_local++}'] = _Line('me', p.ko, tr, true));
  }

  Widget _head() {
    final name = langLabel(widget.langCode, widget.traditional);
    final sub = widget.tablet
        ? '${widget.customerName} 님${(widget.nationality ?? '').isNotEmpty ? ' · ${widget.nationality}' : ''} · 국적으로 자동 선택 · 눌러서 변경'
        : null;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 0, 12, 10),
      decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Ms.gray200))),
      child: Row(children: [
        Expanded(
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => setState(() => _langOpen = !_langOpen),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text('통역 · ', style: Typo.headingMd500),
                Text(name, style: Typo.headingMd500.copyWith(color: Ms.primary)),
                AnimatedRotation(
                  turns: _langOpen ? 0.5 : 0,
                  duration: const Duration(milliseconds: 150),
                  child: const Icon(Icons.keyboard_arrow_down_rounded, color: Ms.primary, size: 20),
                ),
              ]),
              Ticker(
                builder: (_) => Text(
                  sub ?? '${widget.room} · ${mmss(DateTime.now().difference(_opened))}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Typo.caption400.copyWith(color: Ms.gray600),
                ),
              ),
            ]),
          ),
        ),
        MsButton(widget.tablet ? '통역 종료' : '종료', variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _close),
      ]),
    );
  }

  Widget _langChips() => Container(
        width: double.infinity,
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Ms.gray200))),
        child: Wrap(spacing: 8, runSpacing: 8, children: [
          for (final l in langs)
            GestureDetector(
              onTap: () {
                setState(() => _langOpen = false);
                if (l.code != widget.langCode) widget.onLang(l.code);
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(
                  color: l.code == widget.langCode ? Ms.primary100 : Ms.white,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: l.code == widget.langCode ? Ms.primary : Ms.gray300),
                ),
                child: Text(l.name + (l.code == widget.autoCode ? ' · 자동' : ''),
                    style: (l.code == widget.langCode ? Typo.caption600 : Typo.caption500)
                        .copyWith(fontSize: 13, color: l.code == widget.langCode ? Ms.primary : Ms.gray800)),
              ),
            ),
        ]),
      );

  Widget _talk() {
    final lines = _lines.values.toList().reversed.toList();
    final short = widget.customerName.replaceFirst(RegExp(r'^\[[A-Z]+\]\s*'), '');
    if (lines.isEmpty) {
      return Container(
        color: Ms.gray100,
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_state == InterpState.connecting ? '통역을 준비하고 있어요' : '말씀하시면 자막이 나와요', style: Typo.body500.copyWith(color: Ms.gray700)),
          const SizedBox(height: 6),
          Text('한국어는 ${langName(widget.langCode)}로, ${langName(widget.langCode)}는 한국어로 옮겨요',
              textAlign: TextAlign.center, style: Typo.caption400.copyWith(color: Ms.gray600)),
        ]),
      );
    }
    return Container(
      color: Ms.gray100,
      child: ListView.separated(
        reverse: true,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        itemCount: lines.length,
        separatorBuilder: (_, _) => const SizedBox(height: 10),
        itemBuilder: (_, i) {
          final l = lines[i];
          final me = l.side == 'me';
          final partial = !l.isFinal;
          return Column(crossAxisAlignment: me ? CrossAxisAlignment.end : CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Text(me ? '의료진' : '$short 님', style: Typo.caption400.copyWith(color: Ms.gray600)),
            ),
            const SizedBox(height: 3),
            ConstrainedBox(
              constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * (widget.tablet ? 0.5 : 0.84)),
              child: Container(
                padding: const EdgeInsets.fromLTRB(13, 10, 13, 10),
                decoration: BoxDecoration(
                  color: me ? Ms.primary : Ms.white,
                  borderRadius: me
                      ? const BorderRadius.only(
                          topLeft: Radius.circular(14), topRight: Radius.circular(4), bottomLeft: Radius.circular(14), bottomRight: Radius.circular(14))
                      : const BorderRadius.only(
                          topLeft: Radius.circular(4), topRight: Radius.circular(14), bottomLeft: Radius.circular(14), bottomRight: Radius.circular(14)),
                ),
                child: Opacity(
                  opacity: partial ? 0.7 : 1,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(partial ? '${l.original} …' : l.original,
                        style: Typo.titleSm600.copyWith(color: me ? Ms.white : partial ? Ms.gray600 : Ms.gray800)),
                    const SizedBox(height: 5),
                    Text(partial && l.translation.isEmpty ? '번역 중…' : l.translation,
                        style: Typo.body400.copyWith(color: me ? Ms.white : Ms.gray600)),
                  ]),
                ),
              ),
            ),
          ]);
        },
      ),
    );
  }

  // 태블릿 — 대화 옆 「빠른 말하기 · 누르면 읽어줘요」 세로 목록(한국어 + 번역)
  Widget _sidePhrases() {
    final key = phraseKey(widget.langCode, widget.traditional);
    return Container(
      width: 300,
      decoration: const BoxDecoration(border: Border(left: BorderSide(color: Ms.gray200))),
      child: ListView(padding: const EdgeInsets.all(14), children: [
        Text('빠른 말하기 · 누르면 읽어줘요', style: Typo.caption600.copyWith(color: Ms.gray700)),
        const SizedBox(height: 8),
        for (final p in phrases)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: GestureDetector(
              onTap: () async {
                final tr = p.tr[key] ?? p.ko;
                final ok = await _app.speech.say(tr, widget.langCode, widget.traditional);
                if (!ok) {
                  _app.toaster.show('이 기기에 ${langName(widget.langCode)} 음성이 없어요');
                } else {
                  _said(p, tr);
                }
              },
              child: Boxed(
                border: Ms.gray300,
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(p.ko, style: Typo.body600),
                  Text(p.tr[key] ?? '', style: Typo.caption400.copyWith(color: Ms.gray600)),
                ]),
              ),
            ),
          ),
      ]),
    );
  }

  Widget _errorLine() => Container(
        width: double.infinity,
        color: Ms.red100,
        padding: const EdgeInsets.fromLTRB(16, 8, 12, 8),
        child: Row(children: [
          Expanded(child: Text(_error!, style: Typo.caption600.copyWith(color: Ms.red))),
          if (!_micDenied) MsButton('다시 연결', size: BtnSize.sm, color: BtnColor.red, onPressed: _restart),
        ]),
      );

  Widget _micRow() {
    final speaking = _client?.speaking == true;
    final (text, color, hint) = switch (_state) {
      InterpState.listening => speaking
          ? ('번역 읽는 중', Ms.primary, '번역 음성이 나오는 동안은 듣지 않아요')
          : ('듣는 중', Ms.primary, '양쪽 말을 모두 들어요 · 누가 말했는지 자동으로 구분해요 · 누르면 멈춤'),
      InterpState.paused => ('멈춤', Ms.gray700, '누르면 다시 들어요 · 시술 중 잠깐 끌 때'),
      InterpState.error || InterpState.closed => ('연결 안 됨', Ms.red, '[다시 연결]을 눌러 주세요'),
      InterpState.connecting => ('연결 중', Ms.gray700, '마이크와 통역 서버를 연결하고 있어요'),
    };
    final listening = _state == InterpState.listening;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 12, 16, 12 + MediaQuery.paddingOf(context).bottom),
      child: Row(children: [
        GestureDetector(
          onTap: () {
            _client?.toggle();
          },
          child: Container(
            width: 60,
            height: 60,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: listening ? Ms.primary : _state == InterpState.paused ? Ms.white : Ms.gray100,
              border: Border.all(color: listening || _state == InterpState.paused ? Ms.primary : Ms.gray300, width: 2),
            ),
            child: Center(
              child: switch (_state) {
                InterpState.listening => const Icon(Icons.pause_rounded, color: Ms.white, size: 28),
                InterpState.paused => const Icon(Icons.mic_none_rounded, color: Ms.primary, size: 28),
                InterpState.connecting =>
                  const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2.4, color: Ms.gray600)),
                _ => const Icon(Icons.mic_off_rounded, color: Ms.gray600, size: 26),
              },
            ),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(color: listening ? Ms.primary : Ms.gray500, shape: BoxShape.circle)),
              const SizedBox(width: 6),
              Text(text, style: Typo.body600.copyWith(color: color)),
            ]),
            const SizedBox(height: 2),
            Text(hint, style: Typo.caption400.copyWith(color: Ms.gray600)),
          ]),
        ),
      ]),
    );
  }
}

