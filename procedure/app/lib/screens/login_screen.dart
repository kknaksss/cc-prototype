// 로그인(SPEC-004 §6.1) — 로고 · 「시술 현황」 / 서버 주소 입력칸 · [연결 확인] / 계정 카드 → 누르면 로그인
// 앱 카드 = GET /api/auth/accounts 전부(관리자 · 의사 · 간호사 — §6.1 · 코디 확인 2026-10-21)
import 'package:flutter/material.dart';

import '../api/api.dart';
import '../app_state.dart';
import '../config/server.dart';
import '../model/account.dart';
import '../theme/tokens.dart';
import '../widgets/ui.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  late final TextEditingController _addr;
  List<AccountCard>? _cards;
  String? _error;
  String? _health; // 연결 확인 결과
  bool _healthOk = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _addr = TextEditingController(text: AppScope.read(context).server.base);
    _load();
  }

  @override
  void dispose() {
    _addr.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final app = AppScope.read(context);
    setState(() {
      _error = null;
      _cards = null;
    });
    try {
      final all = await app.api.accounts();
      if (!mounted) return;
      setState(() => _cards = all);
    } on ApiError catch (e) {
      if (!mounted) return;
      setState(() {
        _cards = const [];
        _error = e.message;
      });
    }
  }

  // [연결 확인] — 주소 저장 → GET /api/health → 카드 다시 읽기
  Future<void> _check() async {
    final app = AppScope.read(context);
    final v = normalizeBase(_addr.text);
    if (!isValidBase(v)) {
      setState(() {
        _health = '주소 형식이 맞지 않아요 — 예: http://<맥 IP>:8700';
        _healthOk = false;
      });
      return;
    }
    await app.server.save(v);
    _addr.text = app.server.base;
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
    await _load();
  }

  Future<void> _login(AccountCard a) async {
    if (_busy) return;
    final app = AppScope.read(context);
    setState(() => _busy = true);
    try {
      await app.login(a.id);
    } on ApiError catch (e) {
      app.toaster.show(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Ms.gray100,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Center(child: CeramiqueLogo(size: 26)),
                const SizedBox(height: 6),
                Center(child: Text('시술 현황', style: Typo.titleMd600)),
                const SizedBox(height: 28),
                Text('서버 주소', style: Typo.caption600.copyWith(color: Ms.gray700)),
                const SizedBox(height: 6),
                Row(children: [
                  Expanded(
                    child: TextField(
                      key: const Key('server-address'),
                      controller: _addr,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      style: Typo.body400,
                      onSubmitted: (_) => _check(),
                      decoration: InputDecoration(
                        isDense: true,
                        filled: true,
                        fillColor: Ms.white,
                        hintText: 'http://<맥 IP>:8700',
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Ms.gray300)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Ms.gray300)),
                        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: Ms.primary)),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  MsButton('연결 확인', variant: BtnVariant.outlined, color: BtnColor.gray, onPressed: _check),
                ]),
                if (_health != null) ...[
                  const SizedBox(height: 6),
                  Text(_health!, style: Typo.caption500.copyWith(color: _healthOk ? Ms.primary : Ms.gray600)),
                ],
                const SizedBox(height: 24),
                Text('계정', style: Typo.caption600.copyWith(color: Ms.gray700)),
                const SizedBox(height: 6),
                ..._cardList(),
              ]),
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _cardList() {
    final cards = _cards;
    if (cards == null) {
      return [const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator(strokeWidth: 2)))];
    }
    if (cards.isEmpty) {
      return [
        Boxed(
          child: Text(_error != null ? '계정을 불러오지 못했어요 · $_error' : '로그인할 수 있는 계정이 없어요',
              style: Typo.body400.copyWith(color: Ms.gray700)),
        ),
      ];
    }
    return [
      for (final a in cards)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: GestureDetector(
            onTap: () => _login(a),
            child: Boxed(
              border: Ms.gray200,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              child: Row(children: [
                Container(
                  width: 36,
                  height: 36,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(color: switch (a.role) { Role.doctor => Ms.purple100, Role.nurse => Ms.primary100, Role.admin => Ms.gray200 }, shape: BoxShape.circle),
                  child: Text(a.name.isEmpty ? '?' : a.name.characters.first,
                      style: Typo.body600.copyWith(color: switch (a.role) { Role.doctor => Ms.purple, Role.nurse => Ms.primary, Role.admin => Ms.gray700 })),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(a.name, style: Typo.headingMd500),
                    Text(a.label, style: Typo.caption400.copyWith(color: Ms.gray600)),
                  ]),
                ),
                const Icon(Icons.chevron_right, color: Ms.gray600),
              ]),
            ),
          ),
        ),
    ];
  }
}

// 로고 — 글자로(SVG 는 패키지 없이 그리지 않는다)
class CeramiqueLogo extends StatelessWidget {
  final double size;
  const CeramiqueLogo({super.key, this.size = 20});
  @override
  Widget build(BuildContext context) => Text('Céramique',
      style: TextStyle(fontFamily: 'Pretendard', fontSize: size, fontWeight: FontWeight.w700, color: Ms.primary, letterSpacing: -0.3, height: 1));
}
