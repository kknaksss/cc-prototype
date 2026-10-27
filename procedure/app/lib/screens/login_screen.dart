// 로그인(SPEC-004 §6.1 · 2026-10-21 사용자 결정) — 로고 · 「예약 · 시술 현황」 / 서버 주소 입력칸 · [연결 확인] / 아이디 · 비밀번호 → [로그인]
// 계정 카드 없음. 실패 401 · 잠금 429 = 폼 아래 빨간 한 줄. 아이디만 기억(키체인) — 비밀번호는 저장하지 않는다
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../config/server.dart';
import '../theme/tokens.dart';
import '../widgets/ui.dart';

// 로그인 실패 한 줄 — back message 가 있으면 그대로, 없으면 기본 문구
String loginErrorText(ApiError e) {
  final m = e.message.trim();
  return switch (e.status) {
    401 => e.code == 'error' || m.isEmpty ? '아이디 또는 비밀번호가 맞지 않아요' : m,
    429 => e.code == 'error' || m.isEmpty ? '로그인 시도가 너무 많아요 — 잠시 뒤 다시 시도해 주세요' : m,
    _ => m.isEmpty ? '로그인하지 못했어요' : m,
  };
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  late final TextEditingController _addr;
  final _id = TextEditingController();
  final _pw = TextEditingController();
  final _pwFocus = FocusNode();
  final _idFocus = FocusNode();
  String? _error; // 로그인 실패 한 줄
  String? _health; // 연결 확인 결과
  bool _healthOk = false;
  bool _busy = false;
  bool _showPw = false;

  @override
  void initState() {
    super.initState();
    final app = AppScope.read(context);
    _addr = TextEditingController(text: app.server.base);
    app.store.readLastId().then((v) {
      if (!mounted || v == null || _id.text.isNotEmpty) return;
      _id.text = v;
      _pwFocus.requestFocus();
    });
  }

  @override
  void dispose() {
    _addr.dispose();
    _id.dispose();
    _pw.dispose();
    _pwFocus.dispose();
    _idFocus.dispose();
    super.dispose();
  }

  // 입력칸 주소가 바뀌었으면 저장 — 형식이 틀리면 false · release 는 입력칸이 없다(API_BASE 고정)
  Future<bool> _saveAddr() async {
    final app = AppScope.read(context);
    if (!app.server.editable) return true;
    final v = normalizeBase(_addr.text);
    if (!isValidBase(v)) {
      setState(() {
        _health = '주소 형식이 맞지 않아요 — 예: http://<맥 IP>:8700';
        _healthOk = false;
      });
      return false;
    }
    if (v != app.server.base) await app.server.save(v);
    _addr.text = app.server.base;
    return true;
  }

  // [연결 확인] — 주소 저장 → GET /api/health
  Future<void> _check() async {
    final app = AppScope.read(context);
    if (!await _saveAddr()) return;
    setState(() => _health = '확인 중…');
    try {
      await app.api.health();
      if (!mounted) return;
      setState(() {
        _health = '연결됨';
        _healthOk = true;
      });
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() {
        _health = '연결 안 됨 · ${e.message}';
        _healthOk = false;
      });
    }
  }

  Future<void> _login() async {
    if (_busy) return;
    final id = _id.text.trim();
    final pw = _pw.text;
    if (id.isEmpty || pw.isEmpty) {
      setState(() => _error = id.isEmpty ? '아이디를 입력하세요' : '비밀번호를 입력하세요');
      (id.isEmpty ? _idFocus : _pwFocus).requestFocus();
      return;
    }
    final app = AppScope.read(context);
    if (!await _saveAddr() || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await app.login(id, pw);
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() => _error = loginErrorText(e));
      _pw.clear();
      _pwFocus.requestFocus();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  InputDecoration _deco(String hint, {Widget? suffix}) => InputDecoration(
    isDense: true,
    filled: true,
    fillColor: Ms.white,
    hintText: hint,
    hintStyle: Typo.body400.copyWith(color: Ms.gray600),
    suffixIcon: suffix,
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Ms.gray300),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Ms.gray300),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Ms.primary),
    ),
  );

  // 서버 주소 · [연결 확인] — debug 빌드만
  List<Widget> _serverRow(TextStyle label) => [
    Text('서버 주소', style: label),
    const SizedBox(height: 6),
    Row(
      children: [
        Expanded(
          child: TextField(
            key: const Key('server-address'),
            controller: _addr,
            keyboardType: TextInputType.url,
            autocorrect: false,
            enableSuggestions: false,
            textInputAction: TextInputAction.next,
            style: Typo.body400,
            onSubmitted: (_) => _idFocus.requestFocus(),
            decoration: _deco('http://<맥 IP>:8700'),
          ),
        ),
        const SizedBox(width: 8),
        MsButton('연결 확인', variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _check),
      ],
    ),
    if (_health != null) ...[
      const SizedBox(height: 6),
      Text(_health!, style: Typo.caption500.copyWith(color: _healthOk ? Ms.primary : Ms.gray600)),
    ],
    const SizedBox(height: 24),
  ];

  @override
  Widget build(BuildContext context) {
    final label = Typo.caption600.copyWith(color: Ms.gray700);
    return Scaffold(
      backgroundColor: Ms.gray100,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: BoxConstraints(maxWidth: 420 * uiScale(MediaQuery.sizeOf(context))),
              child: AutofillGroup(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Center(child: CeramiqueLogo(size: 26)),
                    const SizedBox(height: 6),
                    Center(child: Text('예약 · 시술 현황', style: Typo.titleMd600)),
                    const SizedBox(height: 28),
                    // 서버 주소 · [연결 확인] — debug 빌드만(로컬 시뮬레이터 확인용)
                    if (AppScope.read(context).server.editable) ..._serverRow(label),
                    Text('아이디', style: label),
                    const SizedBox(height: 6),
                    TextField(
                      key: const Key('login-id'),
                      controller: _id,
                      focusNode: _idFocus,
                      autocorrect: false,
                      enableSuggestions: false,
                      textCapitalization: TextCapitalization.none,
                      // 영문 자판(iOS ASCIICapable) — 한글 자판이면 아이디가 자모로 조합된다(시뮬레이터 확인 2026-10-21)
                      keyboardType: TextInputType.visiblePassword,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [AutofillHints.username],
                      style: Typo.body400,
                      onSubmitted: (_) => _pwFocus.requestFocus(),
                      decoration: _deco('아이디'),
                    ),
                    const SizedBox(height: 12),
                    Text('비밀번호', style: label),
                    const SizedBox(height: 6),
                    TextField(
                      key: const Key('login-password'),
                      controller: _pw,
                      focusNode: _pwFocus,
                      obscureText: !_showPw,
                      autocorrect: false,
                      enableSuggestions: false,
                      textInputAction: TextInputAction.done,
                      autofillHints: const [AutofillHints.password],
                      style: Typo.body400,
                      onSubmitted: (_) => _login(),
                      decoration: _deco(
                        '비밀번호',
                        suffix: IconButton(
                          tooltip: _showPw ? '비밀번호 숨기기' : '비밀번호 보기',
                          icon: Icon(_showPw ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: 20, color: Ms.gray600),
                          onPressed: () => setState(() => _showPw = !_showPw),
                        ),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 10),
                      Text(
                        _error!,
                        key: const Key('login-error'),
                        style: Typo.caption600.copyWith(color: Ms.red, fontSize: 13),
                      ),
                    ],
                    const SizedBox(height: 20),
                    MsButton(_busy ? '로그인 중…' : '로그인', size: BtnSize.lg, expand: true, onPressed: _busy ? null : _login),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// 로고 — 글자로(SVG 는 패키지 없이 그리지 않는다)
class CeramiqueLogo extends StatelessWidget {
  final double size;
  const CeramiqueLogo({super.key, this.size = 20});
  @override
  Widget build(BuildContext context) => Text(
    'Céramique',
    style: TextStyle(
      fontFamily: 'Pretendard',
      fontSize: size,
      fontWeight: FontWeight.w700,
      color: Ms.primary,
      letterSpacing: -0.3,
      height: 1,
    ),
  );
}
